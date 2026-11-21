"""Logged-out Threads scraper (Playwright).

Strategy (docs/feasibility.md):
  1. Open the profile page once, no scrolling. Logged out, only the first screen (~7-9 posts) is
     served and the first scroll triggers a login wall, so we never scroll. Read post codes from
     the embedded SSR JSON.
  2. Open each post page and read its SSR JSON (likes/replies/reposts/quotes/text/time) plus the
     view count shown in the page header (DOM only; >= 10,000 is shown rounded, e.g. "1.5 萬").

Rules: never log in, never dismiss/remove/bypass the login-wall modal, 2-3 s between page loads,
30 s timeout, exponential back-off (3 retries) on 429 / timeouts.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import Error as PWError
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

from . import config

log = logging.getLogger("pipeline.scraper")
TAIPEI = ZoneInfo("Asia/Taipei")

JSON_SCRIPTS_JS = """() => [...document.querySelectorAll('script[type="application/json"]')]
    .map(s => s.textContent || '').filter(t => t.includes('"like_count"'))"""
PAGE_TOP_JS = "() => document.body.innerText.slice(0, 3000)"
META_DESC_JS = """() => (document.querySelector('meta[property="og:description"]') || {}).content || null"""

VIEWS_RE = re.compile(r"(\d[\d.,]*)\s*([KkMm萬万]?)\s*(?:次瀏覽|次觀看|views)", re.I)
LOGIN_WALL_RE = re.compile(r"透過 ?Threads ?暢所欲言|say more with threads", re.I)
MULTIPLIER = {"": 1, "K": 1e3, "k": 1e3, "M": 1e6, "m": 1e6, "萬": 1e4, "万": 1e4}


class RateLimited(Exception):
    pass


class ScrapeError(Exception):
    pass


def parse_views(text: str | None) -> tuple[int | None, bool]:
    """'1,479 次瀏覽' -> (1479, False); '1.5 萬次瀏覽' -> (15000, True). Unknown -> (None, False)."""
    if not text:
        return None, False
    m = VIEWS_RE.search(text.replace("\xa0", " "))
    if not m:
        return None, False
    num, unit = m.group(1).replace(",", ""), m.group(2)
    try:
        value = float(num)
    except ValueError:
        return None, False
    return int(round(value * MULTIPLIER[unit])), bool(unit)  # a unit means Threads rounded the number


def to_taipei_iso(taken_at: int | float | None) -> str | None:
    if not isinstance(taken_at, (int, float)):
        return None
    return datetime.fromtimestamp(taken_at, tz=timezone.utc).astimezone(TAIPEI).isoformat()


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _parse_json_blobs(text: str) -> list:
    try:
        return [json.loads(text)]
    except ValueError:
        return []


def _is_post(d: dict) -> bool:
    return (
        isinstance(d.get("code"), str)
        and ("taken_at" in d or "caption" in d)
        and ("like_count" in d or "text_post_app_info" in d)
    )


def _int(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def json_to_record(d: dict, username: str) -> dict:
    tpai = d.get("text_post_app_info") or {}
    caption = d.get("caption") if isinstance(d.get("caption"), dict) else {}
    code = d["code"]
    return {
        "code": code,
        "owner": ((d.get("user") or {}).get("username") or "").lower(),
        "post_url": f"https://www.threads.com/@{username}/post/{code}",
        "taken_at": d.get("taken_at"),
        "text": caption.get("text"),
        "likes": _int(d.get("like_count")),
        "replies": _int(tpai.get("direct_reply_count")),
        "reposts": _int(tpai.get("repost_count")),
        "quotes": _int(tpai.get("quote_count")),
    }


def extract_posts(script_texts: list[str], username: str) -> dict[str, dict]:
    """All posts by `username` found in the embedded JSON, keyed by code."""
    found: dict[str, dict] = {}
    for txt in script_texts:
        for blob in _parse_json_blobs(txt):
            for d in _walk(blob):
                if _is_post(d):
                    rec = json_to_record(d, username)
                    if rec["owner"] != username.lower():
                        continue
                    # Skip stubs (deleted/unavailable posts have a code but no time or counts):
                    # a missing number must never turn into a 0.
                    if not isinstance(rec["taken_at"], (int, float)) or rec["likes"] is None:
                        log.warning("skipping incomplete post %s (taken_at=%s likes=%s)", rec["code"], rec["taken_at"], rec["likes"])
                        continue
                    found.setdefault(rec["code"], rec)
    return found


def default_executable() -> str | None:
    env = os.environ.get("PW_CHROMIUM_PATH")
    if env:
        return env
    pre = Path("/opt/pw-browsers/chromium")  # pre-installed in the cloud sandbox
    return str(pre) if pre.exists() else None  # elsewhere: `playwright install chromium`


class ThreadsScraper:
    def __init__(self, headless: bool = True, executable_path: str | None = None):
        self.headless = headless
        self.executable_path = executable_path or default_executable()
        self._last_load = 0.0
        self.stats = {"pages": 0, "retries": 0, "login_wall_pages": 0}

    def __enter__(self):
        self._pw = sync_playwright().start()
        kw: dict = {"headless": self.headless}
        if self.executable_path:
            kw["executable_path"] = self.executable_path
        self._browser = self._pw.chromium.launch(**kw)
        ctx = self._browser.new_context(locale="zh-TW", viewport={"width": 1280, "height": 900})
        self.page = ctx.new_page()
        return self

    def __exit__(self, *exc):
        self._browser.close()
        self._pw.stop()

    # -- navigation ---------------------------------------------------------
    def _polite_wait(self) -> None:
        """2-3 s between page loads."""
        gap = random.uniform(config.MIN_DELAY_S, config.MAX_DELAY_S)
        remaining = self._last_load + gap - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)

    def _open(self, url: str) -> None:
        """goto + wait for content. 429 / timeouts -> exponential back-off, MAX_RETRIES retries."""
        for attempt in range(config.MAX_RETRIES + 1):
            self._polite_wait()
            try:
                resp = self.page.goto(url, wait_until="domcontentloaded", timeout=config.PAGE_TIMEOUT_MS)
                self._last_load = time.monotonic()
                self.stats["pages"] += 1
                status = resp.status if resp else None
                if status == 429:
                    raise RateLimited("HTTP 429")
                if status and status >= 500:
                    raise RateLimited(f"HTTP {status}")
                self.page.wait_for_selector("time", timeout=config.PAGE_TIMEOUT_MS)
                time.sleep(1)  # let the SSR JSON / header settle
                return
            except (PWTimeout, RateLimited) as e:
                self._last_load = time.monotonic()
                if attempt == config.MAX_RETRIES:
                    raise ScrapeError(f"{url}: {type(e).__name__} after {attempt + 1} attempts: {e}") from e
                wait = config.BACKOFF_BASE_S * 2**attempt + random.uniform(0, 1)
                self.stats["retries"] += 1
                log.warning("%s: %s (attempt %d/%d), backing off %.1fs", url, e, attempt + 1, config.MAX_RETRIES + 1, wait)
                time.sleep(wait)
            except PWError as e:
                raise ScrapeError(f"{url}: {e}") from e

    def _login_wall(self) -> bool:
        """Detect only. The modal is never closed, removed or worked around."""
        try:
            loc = self.page.get_by_text(LOGIN_WALL_RE)
            hit = bool(loc.count() and loc.first.is_visible())
        except PWError:
            hit = False
        if hit:
            self.stats["login_wall_pages"] += 1
        return hit

    # -- public API ---------------------------------------------------------
    def profile_posts(self, username: str) -> dict[str, dict]:
        """Posts visible on the logged-out profile first screen, keyed by code."""
        url = f"https://www.threads.com/@{username}"
        self._open(url)
        wall = self._login_wall()
        posts = extract_posts(self.page.evaluate(JSON_SCRIPTS_JS), username)
        log.info("profile @%s: %d posts in first screen (login wall on load: %s)", username, len(posts), wall)
        return posts

    def post_page(self, username: str, code: str, fallback: dict | None = None) -> dict:
        """Full record for one post. `fallback` = the profile-page record, used if the page fails."""
        url = f"https://www.threads.com/@{username}/post/{code}"
        try:
            self._open(url)
        except ScrapeError as e:
            if fallback:
                log.warning("post page failed, using profile-page data without views: %s", e)
                return {**fallback, "views": None, "views_rounded": False, "page_ok": False}
            raise
        wall = self._login_wall()
        rec = extract_posts(self.page.evaluate(JSON_SCRIPTS_JS), username).get(code) or dict(fallback or {})
        if not rec:
            raise ScrapeError(f"{url}: no post JSON found (login wall: {wall})")
        if not rec.get("text"):  # caption can be null in the JSON; og:description carries the text
            rec["text"] = self.page.evaluate(META_DESC_JS) or fallback and fallback.get("text")
        views, rounded = parse_views(self.page.evaluate(PAGE_TOP_JS))
        rec.update(views=views, views_rounded=rounded, page_ok=True, login_wall=wall)
        return rec
