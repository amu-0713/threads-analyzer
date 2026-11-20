"""T1b: test the official Threads API (Profile Discovery) for a public account.

Usage:
    export THREADS_ACCESS_TOKEN=...      # or put it in .env (git-ignored)
    python scripts/api_test.py [username] [--max-posts 40]

Calls GET https://graph.threads.net/v1.0/profile_posts?username=<username>
with cursor pagination until --max-posts posts are collected or there are no more pages.
Test only. The token is read from the environment, sent in an Authorization header
and never printed or written to the output file.

Field availability is NOT assumed: the script asks for a wide field list; if the API
rejects the request because of a field, it drops fields one at a time and records which
ones were rejected. Fields never returned stay null.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "feasibility"
BASE = "https://graph.threads.net/v1.0"

# id/text/timestamp/permalink are documented for user posts; the count fields are what we are testing.
CANDIDATE_FIELDS = [
    "id", "media_product_type", "media_type", "text", "timestamp", "permalink", "username",
    "shortcode", "is_quote_post",
    "like_count", "likes", "replies_count", "reply_count", "reposts_count", "repost_count",
    "quotes_count", "quote_count", "views", "view_count",
]
COVERAGE_GROUPS = {
    "created_at": ["timestamp"],
    "text": ["text"],
    "views": ["views", "view_count"],
    "likes": ["like_count", "likes"],
    "replies": ["replies_count", "reply_count"],
    "reposts": ["reposts_count", "repost_count"],
    "quotes": ["quotes_count", "quote_count"],
    "url": ["permalink"],
}


def load_dotenv() -> None:
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def api_get(path: str, params: dict, token: str) -> tuple[int, dict, dict]:
    url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode()), dict(r.headers)
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = {"error": {"message": "non-JSON error body"}}
        return e.code, body, dict(e.headers)


def scrub(s: str, token: str) -> str:
    return s.replace(token, "***") if token else s


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("username", nargs="?", default="7eleventw")
    ap.add_argument("--max-posts", type=int, default=40)
    ap.add_argument("--page-size", type=int, default=25)
    args = ap.parse_args()

    load_dotenv()
    token = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    if not token:
        print("THREADS_ACCESS_TOKEN is not set (env var or .env).", file=sys.stderr)
        return 2

    username = args.username.lstrip("@")
    fields = list(CANDIDATE_FIELDS)
    rejected: list[dict] = []
    pages: list[dict] = []
    posts: list[dict] = []
    errors: list[dict] = []
    rate_headers: dict = {}
    after = None
    stop_reason = None

    while len(posts) < args.max_posts:
        params = {"username": username, "fields": ",".join(fields), "limit": args.page_size}
        if after:
            params["after"] = after
        status, body, headers = api_get("profile_posts", params, token)
        for h in headers:
            if h.lower() in ("x-app-usage", "x-business-use-case-usage", "x-ad-account-usage", "retry-after"):
                rate_headers[h] = headers[h]

        if status != 200:
            err = body.get("error", {})
            msg = scrub(str(err.get("message", "")), token)
            errors.append({"http_status": status, "code": err.get("code"), "subcode": err.get("error_subcode"),
                           "type": err.get("type"), "message": msg})
            print(f"HTTP {status}: code={err.get('code')} {msg[:200]}")
            # Field rejected? Drop the field named in the message and retry (never drop id/timestamp/text).
            m = re.search(r"(?:nonexisting field|Tried accessing nonexisting field|field)\s*[\(\"']?(\w+)", msg)
            cand = m.group(1) if m else None
            if status == 400 and cand in fields and cand not in ("id", "timestamp", "text"):
                fields.remove(cand)
                rejected.append({"field": cand, "message": msg})
                continue
            stop_reason = f"http_{status}"
            break

        data = body.get("data", [])
        posts.extend(data)
        paging = body.get("paging", {})
        pages.append({"n_posts": len(data), "has_next": bool(paging.get("next"))})
        print(f"page {len(pages)}: +{len(data)} (total {len(posts)})")
        after = (paging.get("cursors") or {}).get("after")
        if not data or not paging.get("next") or not after:
            stop_reason = "no_more_pages"
            break
        time.sleep(1)
    else:
        stop_reason = "reached_max_posts"

    posts = posts[: args.max_posts]
    cov = {}
    for name, keys in COVERAGE_GROUPS.items():
        got = sum(1 for p in posts if any(p.get(k) not in (None, "") for k in keys))
        cov[name] = {"count": got, "total": len(posts), "pct": round(100 * got / len(posts), 1) if posts else 0.0,
                     "keys_tried": keys, "keys_present": sorted({k for p in posts for k in keys if k in p})}

    result = {
        "meta": {"username": username, "endpoint": f"{BASE}/profile_posts", "fetched_at": datetime.now(timezone.utc).isoformat(),
                 "posts": len(posts), "pages": len(pages), "stop_reason": stop_reason,
                 "fields_used": fields, "fields_rejected": rejected, "rate_limit_headers": rate_headers},
        "coverage": cov,
        "errors": errors,
        "posts": posts,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{username}_api.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["meta"], ensure_ascii=False, indent=2))
    for k, v in cov.items():
        print(f"  {k:<11}{v['pct']:>6}%  keys={v['keys_present']}")
    print(f"wrote {out}")
    return 0 if posts else 1


if __name__ == "__main__":
    sys.exit(main())
