"""Threads scraper (Playwright), two modes.

Anonymous mode (default; docs/feasibility.md):
  1. Open the profile page once, no scrolling. Logged out, only the first screen (~7-9 posts) is
     served and the first scroll triggers a login wall, so we never scroll. Read post codes from
     the embedded SSR JSON.
  2. Open each post page and read its SSR JSON (likes/replies/reposts/quotes/text/time) plus the
     view count shown in the page header (DOM only; >= 10,000 is shown rounded, e.g. "1.5 萬").

Login mode (--login): the same, but the browser context loads the user's OWN saved session
(`storage_state`, written by src.pipeline.login) and the profile page is scrolled until
LOGIN_POST_LIMIT posts or the end of the feed. This code never sees a username or password.
If the session is invalid or Threads shows a verification / action-block screen, it STOPS with
LoginInvalid and tells the user; it never tries to get past it.

Rules (both modes): never dismiss/remove/bypass a login wall or verification screen, 2-3 s between
page loads and between scrolls, 30 s timeout, exponential back-off (3 retries) on 429 / timeouts.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from urllib.parse import urlparse
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
# Login mode only: signs that the session is dead or Threads wants a human (we stop, never work around it)
SESSION_PATHS = ("/login", "/accounts/login", "/challenge", "/checkpoint", "/consent", "/suspended", "/accounts/suspended")
CHALLENGE_TEXT_RE = re.compile(
    r"確認這是你本人|偵測到.{0,12}(不尋常|可疑)|驗證你的身分|輸入驗證碼|安全碼|請稍後再試|暫時.{0,6}(限制|封鎖)|帳號已被(停用|暫停)"
    r"|confirm (it'?s|that it'?s) you|suspicious (login|activity)|unusual activity|security code|verify your identity"
    r"|try again later|temporarily (blocked|restricted)|account (has been )?(disabled|suspended)",
    re.I,
)
DOM_CODES_JS = """(u) => [...new Set([...document.querySelectorAll('a[href*="/post/"]')]
    .map(a => (a.getAttribute('href') || '').match(/^\/@([^/]+)\/post\/([^/?#]+)/))
    .filter(m => m && m[1].toLowerCase() === u.toLowerCase()).map(m => m[2]))]"""
MULTIPLIER = {"": 1, "K": 1e3, "k": 1e3, "M": 1e6, "m": 1e6, "萬": 1e4, "万": 1e4}


class RateLimited(Exception):
    pass


class ScrapeError(Exception):
    pass


class LoginInvalid(ScrapeError):
    """Login mode: the session expired, or Threads shows a verification / action-block screen. Never retried."""


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


def json_to_record(d: dict, username: str, base: str | None = None) -> dict:
    tpai = d.get("text_post_app_info") or {}
    caption = d.get("caption") if isinstance(d.get("caption"), dict) else {}
    code = d["code"]
    return {
        "code": code,
        "owner": ((d.get("user") or {}).get("username") or "").lower(),
        "post_url": f"{base or config.THREADS_BASE}/@{username}/post/{code}",
        "taken_at": d.get("taken_at"),
        "text": caption.get("text"),
        "likes": _int(d.get("like_count")),
        "replies": _int(tpai.get("direct_reply_count")),
        "reposts": _int(tpai.get("repost_count")),
        "quotes": _int(tpai.get("quote_count")),
    }


def extract_posts(script_texts: list[str], username: str, base: str | None = None) -> dict[str, dict]:
    """All posts by `username` found in the embedded JSON, keyed by code."""
    found: dict[str, dict] = {}
    for txt in script_texts:
        for blob in _parse_json_blobs(txt):
            for d in _walk(blob):
                if _is_post(d):
                    rec = json_to_record(d, username, base)
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
    def __init__(self, headless: bool = True, executable_path: str | None = None, storage_state: str | Path | None = None,
                 base_url: str | None = None):
        self.headless = headless
        self.executable_path = executable_path or default_executable()
        self.storage_state = str(storage_state) if storage_state else None
        self.login_mode = self.storage_state is not None
        self.base = (base_url or config.THREADS_BASE).rstrip("/")
        self._last_load = 0.0
        self._net_posts: dict[str, dict] = {}
        self.stats = {"pages": 0, "retries": 0, "login_wall_pages": 0, "scrolls": 0}

    def __enter__(self):
        if self.login_mode and not Path(self.storage_state).is_file():
            raise ScrapeError(f"找不到登入狀態檔 {self.storage_state}。請先在這台電腦執行：python -m src.pipeline.login")
        self._pw = sync_playwright().start()
        kw: dict = {"headless": self.headless}
        if self.executable_path:
            kw["executable_path"] = self.executable_path
        self._browser = self._pw.chromium.launch(**kw)
        ctx_kw: dict = {"locale": "zh-TW", "viewport": {"width": 1280, "height": 900}}
        if self.login_mode:
            ctx_kw["storage_state"] = self.storage_state
        ctx = self._browser.new_context(**ctx_kw)
        self.page = ctx.new_page()
        return self

    def __exit__(self, *exc):
        self._browser.close()
        self._pw.stop()

    # -- navigation ---------------------------------------------------------
    def _polite_wait(self) -> None:
        """2-3 s between page loads (and between scrolls)."""
        gap = random.uniform(config.MIN_DELAY_S, config.MAX_DELAY_S)
        remaining = self._last_load + gap - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)

    def _session_problem(self) -> str | None:
        """Login mode: why the session can't be used right now (None = fine). Detection only."""
        path = urlparse(self.page.url).path
        for pat in SESSION_PATHS:
            if path.startswith(pat):
                return f"被導向 {path}（登入已失效，或需要重新登入）"
        if self._login_wall():
            return "出現登入牆（登入狀態已失效）"
        try:
            if not self.page.locator("time").count():  # a real profile / post page always has a <time>
                body = self.page.inner_text("body")[:2000]
                if CHALLENGE_TEXT_RE.search(body):
                    return "出現驗證或頻率限制畫面"
        except PWError:
            pass
        return None

    def _stop_for_session(self, problem: str) -> LoginInvalid:
        return LoginInvalid(
            f"登入模式停止：{problem}。請在瀏覽器裡手動處理（登入／驗證／稍等一段時間），再重新執行 "
            "python -m src.pipeline.login 與本指令。本程式不會嘗試繞過驗證。"
        )

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
                if self.login_mode:
                    deadline = time.monotonic() + config.PAGE_TIMEOUT_MS / 1000
                    while True:  # wait for content, but notice a dead session / verification screen right away
                        problem = self._session_problem()
                        if problem:
                            raise self._stop_for_session(problem)
                        try:
                            self.page.wait_for_selector("time", timeout=1500)
                            break
                        except PWTimeout:
                            if time.monotonic() > deadline:
                                raise
                else:
                    self.page.wait_for_selector("time", timeout=config.PAGE_TIMEOUT_MS)
                time.sleep(config.SETTLE_S)  # let the SSR JSON / header settle
                if self.login_mode:
                    problem = self._session_problem()
                    if problem:
                        raise self._stop_for_session(problem)
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
        """Anonymous mode: posts visible on the logged-out profile first screen, keyed by code."""
        url = f"{self.base}/@{username}"
        self._open(url)
        wall = self._login_wall()
        posts = extract_posts(self.page.evaluate(JSON_SCRIPTS_JS), username, self.base)
        log.info("profile @%s: %d posts in first screen (login wall on load: %s)", username, len(posts), wall)
        return posts

    def _on_response(self, username: str):
        def handler(resp):
            try:
                if "json" not in (resp.headers.get("content-type") or "") and "graphql" not in resp.url:
                    return
                body = resp.text()
                if '"like_count"' not in body:
                    return
                for code, rec in extract_posts([body], username, self.base).items():
                    self._net_posts.setdefault(code, rec)
            except Exception:  # noqa: BLE001 - a response we can't read is just ignored
                pass
        return handler

    def profile_posts_login(self, username: str, limit: int | None = None) -> dict[str, dict]:
        """Login mode: scroll the profile until `limit` posts or the end of the feed.

        Post codes come from the DOM (links) and from the JSON that the page loads while scrolling; entries
        seen only in the DOM have no data yet ({}), the single-post page fills them in. Keyed by code, in the
        order they appear on the profile.
        """
        limit = limit or config.LOGIN_POST_LIMIT
        self._net_posts.clear()
        handler = self._on_response(username)
        self.page.on("response", handler)
        try:
            self._open(f"{self.base}/@{username}")
            found: dict[str, dict] = {}

            def collect() -> None:
                for code, rec in extract_posts(self.page.evaluate(JSON_SCRIPTS_JS), username, self.base).items():
                    found[code] = rec or found.get(code, {})
                for code in self.page.evaluate(DOM_CODES_JS, username):
                    found.setdefault(code, {})
                for code, rec in list(self._net_posts.items()):
                    if rec or code not in found:
                        found[code] = rec

            collect()
            idle = 0
            while len(found) < limit and idle < 3 and self.stats["scrolls"] < config.MAX_SCROLLS:
                problem = self._session_problem()
                if problem:
                    raise self._stop_for_session(problem)
                before = len(found)
                self.page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
                self.page.mouse.wheel(0, 1200)
                self.stats["scrolls"] += 1
                self._last_load = time.monotonic()
                self._polite_wait()  # 2-3 s per scroll step
                collect()
                idle = idle + 1 if len(found) == before else 0
                log.info("scroll %d: %d posts found", self.stats["scrolls"], len(found))
            reason = "limit reached" if len(found) >= limit else "end of feed" if idle >= 3 else "scroll cap"
            log.info("profile @%s (login): %d posts collected (%s), keeping %d", username, len(found), reason, min(len(found), limit))
            return dict(list(found.items())[:limit])
        finally:
            self.page.remove_listener("response", handler)

    def post_page(self, username: str, code: str, fallback: dict | None = None) -> dict:
        """Full record for one post. `fallback` = the profile-page record, used if the page fails."""
        url = f"{self.base}/@{username}/post/{code}"
        try:
            self._open(url)
        except LoginInvalid:
            raise
        except ScrapeError as e:
            if fallback:
                log.warning("post page failed, using profile-page data without views: %s", e)
                return {**fallback, "views": None, "views_rounded": False, "page_ok": False}
            raise
        wall = self._login_wall()
        rec = extract_posts(self.page.evaluate(JSON_SCRIPTS_JS), username, self.base).get(code) or dict(fallback or {})
        if not rec:
            raise ScrapeError(f"{url}: no post JSON found (login wall: {wall})")
        if not rec.get("text"):  # caption can be null in the JSON; og:description carries the text
            rec["text"] = self.page.evaluate(META_DESC_JS) or fallback and fallback.get("text")
        views, rounded = parse_views(self.page.evaluate(PAGE_TOP_JS))
        rec.update(views=views, views_rounded=rounded, page_ok=True, login_wall=wall)
        return rec
