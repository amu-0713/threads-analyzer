"""T1 feasibility test: what can we get from a public Threads profile without logging in?

Usage:
    python scripts/feasibility_test.py <username> [--headless] [--max-posts 40]

What it does (test only, not a production scraper):
  * opens https://www.threads.com/@<username> without logging in
  * scrolls (1-2 s apart) until --max-posts posts, 3 scrolls with no new posts, or a login wall
  * parses posts two ways and compares them:
      - DOM: what is rendered on the page
      - JSON: embedded SSR JSON (<script type="application/json">) + network JSON/GraphQL responses
  * writes data/feasibility/<username>_raw.json

Fields we never find are kept as null — nothing is guessed.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import Error as PWError
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "feasibility"

FIELDS = ["created_at", "text", "views", "likes", "replies", "reposts", "quotes", "url"]
MAX_NO_NEW_SCROLLS = 3
LOGIN_WALL_PATTERNS = [
    r"log in or sign up",
    r"log in to see more",
    r"sign up to see more",
    r"登入或註冊",
    r"登入以查看",
    r"登入.*查看更多",
]


# ----------------------------------------------------------------------------- helpers
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_count(s: str | None) -> int | None:
    """'1,234' / '1.2K' / '3.4M' / '1.2萬' -> int. Anything else -> None."""
    if not s:
        return None
    s = s.strip().replace(",", "").replace(" ", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([KkMm萬万億亿]?)", s)
    if not m:
        return None
    num = float(m.group(1))
    mult = {"": 1, "K": 1e3, "k": 1e3, "M": 1e6, "m": 1e6, "萬": 1e4, "万": 1e4, "億": 1e8, "亿": 1e8}[m.group(2)]
    return int(round(num * mult))


def strip_json_prefix(text: str) -> str:
    text = text.lstrip()
    for p in ("for (;;);", "for(;;);", ")]}'"):
        if text.startswith(p):
            text = text[len(p):]
    return text


def try_parse_json_blobs(text: str) -> list:
    """Responses can be one JSON doc or several newline-delimited ones."""
    text = strip_json_prefix(text)
    try:
        return [json.loads(text)]
    except Exception:
        pass
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{") or line.startswith("["):
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def find_keys(obj, pattern: re.Pattern, prefix: str = "", depth: int = 0, acc: set | None = None) -> set:
    """Collect key paths whose name matches pattern (used to discover view/impression fields)."""
    acc = set() if acc is None else acc
    if depth > 6:
        return acc
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            if pattern.search(k):
                acc.add(path)
            find_keys(v, pattern, path, depth + 1, acc)
    elif isinstance(obj, list) and obj:
        find_keys(obj[0], pattern, prefix + "[]", depth + 1, acc)
    return acc


VIEW_KEY_RE = re.compile(r"view|impression|play_count|reach", re.I)


def looks_like_post(d: dict) -> bool:
    return isinstance(d.get("code"), str) and ("taken_at" in d or "caption" in d) and (
        "like_count" in d or "text_post_app_info" in d
    )


def json_post_to_record(d: dict, username: str) -> dict:
    tpai = d.get("text_post_app_info") or {}
    caption = d.get("caption") or {}
    user = d.get("user") or {}
    owner = user.get("username")
    taken_at = d.get("taken_at")
    created = datetime.fromtimestamp(taken_at, tz=timezone.utc).isoformat() if isinstance(taken_at, (int, float)) else None

    # views: only take an explicit numeric field, never derive it.
    views = None
    views_key = None
    for k in ("view_count", "views", "impression_count", "play_count", "ig_play_count"):
        if isinstance(d.get(k), (int, float)):
            views, views_key = int(d[k]), k
            break

    code = d.get("code")
    return {
        "code": code,
        "owner": owner,
        "created_at": created,
        "text": caption.get("text") if isinstance(caption, dict) else None,
        "views": views,
        "views_key": views_key,
        "likes": d.get("like_count") if isinstance(d.get("like_count"), int) else None,
        "replies": tpai.get("direct_reply_count") if isinstance(tpai.get("direct_reply_count"), int) else None,
        "reposts": tpai.get("repost_count") if isinstance(tpai.get("repost_count"), int) else None,
        "quotes": tpai.get("quote_count") if isinstance(tpai.get("quote_count"), int) else None,
        "reshares": tpai.get("reshare_count") if isinstance(tpai.get("reshare_count"), int) else None,
        "url": f"https://www.threads.com/@{owner or username}/post/{code}" if code else None,
        "view_like_keys": sorted(find_keys(d, VIEW_KEY_RE)),
    }


# ----------------------------------------------------------------------------- DOM extraction
DOM_JS = r"""
(username) => {
  const out = [];
  const seen = new Set();
  const links = Array.from(document.querySelectorAll('a[href*="/post/"]'));
  for (const a of links) {
    const href = a.getAttribute('href') || '';
    const m = href.match(/\/@([^/]+)\/post\/([^/?#]+)/);
    if (!m) continue;
    const code = m[2];
    if (seen.has(code)) continue;
    // Climb to the post container: nearest ancestor that also contains action buttons.
    let el = a, container = null;
    for (let i = 0; i < 15 && el; i++, el = el.parentElement) {
      if (el.matches && el.matches('[data-pressable-container]')) { container = el; break; }
      if (el.querySelectorAll && el.querySelectorAll('svg[aria-label]').length >= 3 && el.querySelector('time')) { container = el; break; }
    }
    if (!container) continue;
    seen.add(code);
    const t = container.querySelector('time');
    // action buttons: svg aria-label (Like/Reply/Repost/Share or localized) + sibling number text
    const actions = {};
    for (const svg of container.querySelectorAll('svg[aria-label]')) {
      const label = svg.getAttribute('aria-label');
      const btn = svg.closest('[role="button"]') || svg.parentElement;
      const txt = btn ? (btn.innerText || '').trim() : '';
      if (!(label in actions)) actions[label] = txt;
    }
    // text: spans with dir="auto" that are not the username/time
    const textParts = [];
    for (const s of container.querySelectorAll('span[dir="auto"]')) {
      const tx = (s.innerText || '').trim();
      if (!tx) continue;
      if (s.closest('a[href^="/@"]') && !s.closest('a[href*="/post/"]')) continue;
      if (s.closest('time')) continue;
      textParts.push(tx);
    }
    out.push({
      code,
      owner: m[1],
      href: new URL(href, location.origin).href,
      datetime: t ? t.getAttribute('datetime') : null,
      actions,
      text_parts: textParts,
      container_text: (container.innerText || '').slice(0, 2000),
    });
  }
  return out;
}
"""

ACTION_MAP = {
    "likes": [r"^like$", r"^unlike$", r"讚", r"喜歡"],
    "replies": [r"^reply$", r"^comment$", r"回覆", r"留言"],
    "reposts": [r"^repost$", r"轉發", r"轉貼"],
    "shares": [r"^share$", r"分享"],
    "views": [r"view", r"觀看", r"瀏覽"],
}


def dom_post_to_record(p: dict) -> dict:
    rec = {
        "code": p["code"],
        "owner": p["owner"],
        "created_at": p.get("datetime"),
        "text": None,
        "views": None,
        "likes": None,
        "replies": None,
        "reposts": None,
        "quotes": None,  # DOM merges quotes into the repost button; not separable
        "url": p.get("href"),
        "raw_actions": p.get("actions"),
    }
    # first text part is usually the author handle; keep the longest non-handle chunk set
    parts = [t for t in p.get("text_parts", []) if t != p["owner"]]
    rec["text"] = "\n".join(parts) if parts else None
    for label, txt in (p.get("actions") or {}).items():
        for field, pats in ACTION_MAP.items():
            if any(re.search(pt, label, re.I) for pt in pats):
                if field in rec and rec[field] is None:
                    rec[field] = parse_count(txt)
    return rec


# ----------------------------------------------------------------------------- main
def detect_login_wall(page) -> str | None:
    try:
        if "/login" in page.url:
            return f"redirected to {page.url}"
        dialogs = page.locator('[role="dialog"]')
        texts = []
        for i in range(min(dialogs.count(), 3)):
            texts.append(dialogs.nth(i).inner_text(timeout=1000))
        body = " ".join(texts)
        for pat in LOGIN_WALL_PATTERNS:
            if re.search(pat, body, re.I):
                return f"dialog matched /{pat}/"
    except PWError:
        pass
    return None


def default_executable() -> str | None:
    env = os.environ.get("PW_CHROMIUM_PATH")
    if env:
        return env
    pre = Path("/opt/pw-browsers/chromium")  # pre-installed browser in some cloud sandboxes
    return str(pre) if pre.exists() else None


def coverage(records: list[dict]) -> dict:
    n = len(records)
    res = {}
    for f in FIELDS:
        got = sum(1 for r in records if r.get(f) not in (None, ""))
        res[f] = {"count": got, "total": n, "pct": round(100 * got / n, 1) if n else 0.0}
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("username")
    ap.add_argument("--headless", action="store_true", help="run without a visible browser window")
    ap.add_argument("--max-posts", type=int, default=40)
    ap.add_argument("--max-scrolls", type=int, default=40, help="hard cap on scrolls")
    ap.add_argument("--executable-path", default=default_executable(), help="custom Chromium binary (optional)")
    args = ap.parse_args()

    username = args.username.lstrip("@")
    url = f"https://www.threads.com/@{username}"
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    json_posts: dict[str, dict] = {}
    dom_posts: dict[str, dict] = {}
    network_log: list[dict] = []
    errors: list[str] = []
    scroll_log: list[dict] = []
    view_keys_seen: set[str] = set()
    sample_json_post = None
    stop_reason = None
    login_wall = None

    def ingest_json(obj, source: str) -> int:
        nonlocal sample_json_post
        added = 0
        for d in walk(obj):
            if looks_like_post(d):
                rec = json_post_to_record(d, username)
                view_keys_seen.update(rec["view_like_keys"])
                if rec["owner"] and rec["owner"].lower() != username.lower():
                    continue  # quoted / reposted posts from other users
                if rec["code"] not in json_posts:
                    rec["json_source"] = source
                    json_posts[rec["code"]] = rec
                    added += 1
                    if sample_json_post is None:
                        sample_json_post = d
        return added

    def on_response(resp):
        try:
            ct = (resp.headers.get("content-type") or "").lower()
            u = resp.url
            if not ("json" in ct or "/graphql" in u or "/api/" in u):
                return
            body = resp.text()
            entry = {"url": u.split("?")[0], "status": resp.status, "content_type": ct, "bytes": len(body),
                     "friendly_name": resp.request.headers.get("x-fb-friendly-name"), "posts_added": 0}
            for blob in try_parse_json_blobs(body):
                entry["posts_added"] += ingest_json(blob, f"network:{entry['friendly_name'] or entry['url']}")
            network_log.append(entry)
        except Exception as e:  # body may be unavailable for redirects etc.
            errors.append(f"response parse error {resp.url[:120]}: {type(e).__name__}: {e}"[:300])

    started = now_iso()
    with sync_playwright() as p:
        launch_kwargs = {"headless": args.headless}
        if args.executable_path:
            launch_kwargs["executable_path"] = args.executable_path
        browser = p.chromium.launch(**launch_kwargs)
        ctx = browser.new_context(locale="zh-TW", viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.on("response", on_response)

        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
            http_status = resp.status if resp else None
            try:
                page.wait_for_selector('a[href*="/post/"]', timeout=20000)
            except PWTimeout:
                errors.append("no post links appeared within 20s after load")
        except PWError as e:
            errors.append(f"navigation failed: {e}"[:500])
            http_status = None
            stop_reason = "navigation_failed"

        if stop_reason is None:
            # SSR JSON embedded in the initial HTML
            try:
                scripts = page.locator('script[type="application/json"]')
                for i in range(scripts.count()):
                    txt = scripts.nth(i).text_content() or ""
                    if '"taken_at"' in txt or '"like_count"' in txt:
                        for blob in try_parse_json_blobs(txt):
                            ingest_json(blob, "ssr:script[type=application/json]")
            except PWError as e:
                errors.append(f"ssr parse error: {e}"[:300])

            no_new = 0
            for i in range(args.max_scrolls):
                for raw in page.evaluate(DOM_JS, username):
                    if raw["owner"].lower() != username.lower():
                        continue
                    if raw["code"] not in dom_posts:
                        dom_posts[raw["code"]] = dom_post_to_record(raw)
                total = len(set(dom_posts) | set(json_posts))
                scroll_log.append({"scroll": i, "dom": len(dom_posts), "json": len(json_posts), "union": total})
                print(f"[scroll {i:02d}] dom={len(dom_posts)} json={len(json_posts)} union={total}", flush=True)

                login_wall = detect_login_wall(page)
                if login_wall:
                    stop_reason = "login_wall"
                    break
                if total >= args.max_posts:
                    stop_reason = "reached_max_posts"
                    break
                if i > 0 and total <= scroll_log[-2]["union"]:
                    no_new += 1
                    if no_new >= MAX_NO_NEW_SCROLLS:
                        stop_reason = "no_new_posts_3_scrolls"
                        break
                else:
                    no_new = 0
                page.mouse.wheel(0, 2500)
                time.sleep(random.uniform(1.0, 2.0))
            else:
                stop_reason = "max_scrolls_cap"

            try:
                page.screenshot(path=str(OUT_DIR / f"{username}_final.png"))
            except PWError:
                pass
        browser.close()

    # ---- compare & merge
    dom_list = list(dom_posts.values())
    json_list = list(json_posts.values())
    merged = []
    for code in list(dict.fromkeys(list(json_posts) + list(dom_posts))):
        j, d = json_posts.get(code, {}), dom_posts.get(code, {})
        row = {"code": code}
        for f in FIELDS:
            jv, dv = j.get(f), d.get(f)
            row[f] = jv if jv not in (None, "") else dv
            row[f + "_source"] = "json" if jv not in (None, "") else ("dom" if dv not in (None, "") else None)
        merged.append(row)
    merged.sort(key=lambda r: r.get("created_at") or "", reverse=True)

    login_wall_at = len(set(dom_posts) | set(json_posts)) if stop_reason == "login_wall" else None
    result = {
        "meta": {
            "username": username,
            "url": url,
            "started_at": started,
            "finished_at": now_iso(),
            "headless": args.headless,
            "logged_in": False,
            "http_status": http_status,
            "stop_reason": stop_reason,
            "login_wall": login_wall,
            "posts_loaded_before_login_wall": login_wall_at,
            "scrolls": len(scroll_log),
            "counts": {"dom": len(dom_list), "json": len(json_list), "merged": len(merged)},
            "view_like_json_keys_seen": sorted(view_keys_seen),
        },
        "coverage": {"dom": coverage(dom_list), "json": coverage(json_list), "merged": coverage(merged)},
        "scroll_log": scroll_log,
        "network_log": network_log,
        "errors": errors,
        "merged_posts": merged,
        "dom_posts": dom_list,
        "json_posts": json_list,
        "sample_json_post_raw": sample_json_post,
    }
    out = OUT_DIR / f"{username}_raw.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== summary ===")
    print(json.dumps(result["meta"], ensure_ascii=False, indent=2))
    print("coverage (pct)  field      dom    json   merged")
    for f in FIELDS:
        print(f"                {f:<10} {result['coverage']['dom'][f]['pct']:>5}  {result['coverage']['json'][f]['pct']:>5}  {result['coverage']['merged'][f]['pct']:>5}")
    if errors:
        print(f"errors: {len(errors)} (see raw json)")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
