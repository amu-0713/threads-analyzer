"""T1c: can we get >=30 posts by opening single post pages without logging in?

Usage:
    python scripts/post_page_test.py [username] [--headless] [--max-posts 40] [--max-pages 70]

1. Seeds = post URLs found by the T1 profile-page test (data/feasibility/<user>_raw.json).
2. Opens each post page (no login, 2-3 s between pages), extracts fields from the embedded
   SSR JSON and from the DOM, and records whether the login wall appeared.
3. Chain discovery: every post by <username> that shows up on a page (JSON or links) is queued.
   Posts by other accounts are ignored.
Stops at --max-posts, when the queue is empty, or at --max-pages. Test only; unknown fields stay null.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import Error as PWError
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from feasibility_test import (DOM_JS, FIELDS, OUT_DIR, coverage, default_executable, detect_login_wall,  # noqa: E402
                              dom_post_to_record, json_post_to_record, looks_like_post, now_iso, parse_count,
                              try_parse_json_blobs, walk)

VIEWS_RE = re.compile(r"([\d][\d.,]*\s*[KkMm萬万]?)\s*(?:次瀏覽|次觀看|views)", re.I)


def post_url(user: str, code: str) -> str:
    return f"https://www.threads.com/@{user}/post/{code}"


def load_seeds(user: str) -> list[str]:
    p = OUT_DIR / f"{user}_raw.json"
    if not p.exists():
        return []
    d = json.loads(p.read_text(encoding="utf-8"))
    return [m["code"] for m in d.get("merged_posts", []) if m.get("code")]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("username", nargs="?", default="7eleventw")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--max-posts", type=int, default=40)
    ap.add_argument("--max-pages", type=int, default=70)
    ap.add_argument("--executable-path", default=default_executable())
    args = ap.parse_args()
    user = args.username.lstrip("@")

    seeds = load_seeds(user)
    if not seeds:
        print("no seeds: run scripts/feasibility_test.py first", file=sys.stderr)
        return 2

    queue = deque(seeds)
    queued = set(seeds)
    discovered_via: dict[str, str] = {c: "seed:profile_page" for c in seeds}
    results: list[dict] = []
    errors: list[str] = []
    stop_reason = None
    started = now_iso()

    with sync_playwright() as p:
        kw = {"headless": args.headless}
        if args.executable_path:
            kw["executable_path"] = args.executable_path
        browser = p.chromium.launch(**kw)
        ctx = browser.new_context(locale="zh-TW", viewport={"width": 1280, "height": 900})
        page = ctx.new_page()

        while queue:
            if len(results) >= args.max_posts:
                stop_reason = "reached_max_posts"
                break
            if len(results) >= args.max_pages:
                stop_reason = "max_pages_cap"
                break
            code = queue.popleft()
            url = post_url(user, code)
            row = {"code": code, "url": url, "discovered_via": discovered_via.get(code), "http_status": None,
                   "login_wall": None, "error": None}
            json_posts: dict[str, dict] = {}
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
                row["http_status"] = resp.status if resp else None
                try:
                    page.wait_for_selector("time", timeout=15000)
                except PWTimeout:
                    row["error"] = "no <time> within 15s"
                time.sleep(1)
                row["login_wall"] = detect_login_wall(page)

                # SSR JSON
                scripts = page.locator('script[type="application/json"]')
                for i in range(scripts.count()):
                    txt = scripts.nth(i).text_content() or ""
                    if '"like_count"' not in txt:
                        continue
                    for blob in try_parse_json_blobs(txt):
                        for d in walk(blob):
                            if looks_like_post(d):
                                rec = json_post_to_record(d, user)
                                json_posts.setdefault(rec["code"], rec)
                own_json = {c: r for c, r in json_posts.items() if (r["owner"] or "").lower() == user.lower()}

                # DOM
                dom_all = [dom_post_to_record(r) for r in page.evaluate(DOM_JS, user)
                           if r["owner"].lower() == user.lower()]
                dom_main = next((r for r in dom_all if r["code"] == code), {})
                views_dom = None
                m = VIEWS_RE.search(page.inner_text("body")[:1500])
                if m:
                    views_dom = parse_count(re.sub(r"\s", "", m.group(1)))  # '1.0\xa0萬' -> '1.0萬' (rounded by Threads)

                j, d = own_json.get(code, {}), dom_main
                for f in FIELDS:
                    jv, dv = j.get(f), d.get(f)
                    if f == "views":
                        jv, dv = j.get("views"), views_dom
                    row[f] = jv if jv not in (None, "") else dv
                    row[f + "_source"] = "json" if jv not in (None, "") else ("dom" if dv not in (None, "") else None)
                row["views_note"] = "DOM header text near the top of the post page" if row["views_source"] == "dom" else None
                row["has_json"], row["has_dom"] = bool(j), bool(d)

                # chain discovery: only this account's posts
                found = set(own_json) | {r["code"] for r in dom_all}
                new = [c for c in found if c not in queued]
                for c in new:
                    queued.add(c)
                    queue.append(c)
                    discovered_via[c] = f"chain:{code}"
                row["new_own_posts_found"] = len(new)
            except PWError as e:
                row["error"] = f"{type(e).__name__}: {e}"[:300]
                errors.append(f"{code}: {row['error']}")
            results.append(row)
            print(f"[{len(results):02d}] {code} wall={bool(row['login_wall'])} likes={row.get('likes')} views={row.get('views')} "
                  f"new={row.get('new_own_posts_found')} queue={len(queue)}", flush=True)
            time.sleep(random.uniform(2.0, 3.0))
        else:
            stop_reason = "queue_empty"
        browser.close()

    ok = [r for r in results if r.get("has_json") or r.get("has_dom")]
    ok.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    out = {
        "meta": {"username": user, "started_at": started, "finished_at": now_iso(), "headless": args.headless,
                 "logged_in": False, "pages_opened": len(results), "posts_with_data": len(ok),
                 "unique_urls_discovered": len(queued), "stop_reason": stop_reason,
                 "login_wall_pages": sum(1 for r in results if r["login_wall"]),
                 "seeds": len(seeds), "discovered_by_chain": len(queued) - len(seeds),
                 "search_engine": "not used by this script (see docs)"},
        "coverage": coverage(ok),
        "errors": errors,
        "posts": results,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{user}_postpages.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out["meta"], ensure_ascii=False, indent=2))
    for f in FIELDS:
        print(f"  {f:<10}{out['coverage'][f]['pct']:>6}%")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
