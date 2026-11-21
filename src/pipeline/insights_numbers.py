"""Recompute every number cited in reports/insights.md from the database (real posts only, never mock).

    python -m src.pipeline.insights_numbers --mode login        # 4 accounts x 40 posts (the main data)
    python -m src.pipeline.insights_numbers --mode anonymous    # the logged-out first-screen data (appendix)

Reads the finished job of each brand account for the chosen scraping mode (anonymous: the real-only job, i.e. the one
without mock rows; login: the latest login job). Prints descriptive figures only: counts, medians, direction.
No significance tests. The outputs are saved in reports/insights_numbers_<mode>.txt so the figures can be checked
without database access.

Two lists below were coded BY HAND after reading the posts (INVITE / HEAVY). That is exploratory coding, done once
the data was in: it is disclosed in the report and must not be read as a pre-registered test.
"""

from __future__ import annotations

import argparse
import re
import statistics as st
from datetime import datetime
from zoneinfo import ZoneInfo

from .db import Db

ACCOUNTS = ["7eleventw", "starbuckstw", "dcard.tw", "pchome24h"]
TZ = ZoneInfo("Asia/Taipei")
URL = re.compile(r"https?://\S+")
QUESTION = re.compile(r"[？?]")
TEASER = re.compile(r"原文來自|搜尋文章標題")  # dcard.tw: a post that points readers to the full article elsewhere

# Hand-coded (account, "MM-DD", unique text fragment).
# INVITE: the post asks readers for ONE easy action (like / comment / guess / post a photo / lottery) in a short opener.
INVITE = [
    ("7eleventw", "11-20", "\\ 抽 LNGSHOT"), ("starbuckstw", "09-04", "許願文"), ("pchome24h", "11-18", "限時抽"),
    ("pchome24h", "11-12", "點愛心"), ("pchome24h", "11-03", "留言猜猜"), ("pchome24h", "10-27", "國際黑貓日"),
    ("pchome24h", "10-24", "重大消息宣布"), ("pchome24h", "09-26", "國際兔子日"), ("pchome24h", "09-18", "一人一讚"),
    ("pchome24h", "11-05", "咖啡PChome請你喝"),
]
# HEAVY: a prize / campaign post whose opener carries the full rules (several steps, purchase, photo, long text).
HEAVY = [
    ("7eleventw", "10-16", "在本篇貼文下方留言上傳"), ("starbuckstw", "10-07", "分享你的透卡自拍"), ("pchome24h", "11-05", "獲得活動辦法"),
]


def load(mode: str, db: Db | None = None) -> list[dict]:
    db = db or Db()
    rows: list[dict] = []
    for u in ACCOUNTS:
        jobs = db.select("jobs", {"username": f"eq.{u}", "status": "eq.done", "mode": f"eq.{mode}", "select": "id,created_at", "order": "created_at"})
        chosen = None
        for j in jobs:
            ps = db.select("posts", {"job_id": f"eq.{j['id']}", "select": "*"})
            if mode == "anonymous" and any(p["source"] == "mock" for p in ps):
                continue  # the 7eleventw main task also holds mock rows: never used here
            chosen = ps  # for login: keep the latest
            if mode == "anonymous":
                break
        if chosen is None:
            raise SystemExit(f"no finished {mode} job for @{u}")
        for p in chosen:
            assert p["source"] == "real" and p["views"], p["post_url"]
            p["u"] = u
            p["t"] = datetime.fromisoformat(p["posted_at"].replace("Z", "+00:00")).astimezone(TZ)
            p["lr"], p["rr"] = p["likes"] / p["views"], p["replies"] / p["views"]
            p["ir"] = (p["likes"] + p["replies"] + p["reposts"] + p["quotes"]) / p["views"]
            rows.append(p)
    return rows


def med(xs):
    return st.median(xs) if xs else float("nan")


def pc(x: float) -> str:
    return "—" if x != x else f"{100 * x:.2f}%"


def find(rows: list[dict], u: str, day: str, frag: str) -> dict | None:
    c = [r for r in rows if r["u"] == u and f"{r['t']:%m-%d}" == day and frag in (r["text"] or "")]
    assert len(c) <= 1, (u, day, frag, len(c))
    return c[0] if c else None


def per_account(rows: list[dict], out) -> None:
    out("== 1. per account")
    for u in ACCOUNTS:
        ps = [r for r in rows if r["u"] == u]
        top = max(ps, key=lambda r: r["views"])
        newest = max(r["t"] for r in ps)
        types = {t: sum(1 for r in ps if r["post_type"] == t) for t in sorted({r["post_type"] for r in ps})}
        out(f"{u:12} n={len(ps)} {min(r['t'] for r in ps):%Y-%m-%d}..{newest:%Y-%m-%d} | median views {med([r['views'] for r in ps]):.0f}, "
            f"likes {med([r['likes'] for r in ps]):.1f}, like rate {pc(med([r['lr'] for r in ps]))}, interaction rate {pc(med([r['ir'] for r in ps]))}, "
            f"reply rate {pc(med([r['rr'] for r in ps]))}, chars {med([r['char_count'] for r in ps]):.0f} | rounded views {sum(1 for r in ps if r['views_rounded'])}"
            f" | top views {top['views']} on {top['t']:%m-%d} ({(newest - top['t']).days} d before newest) | types {types}")


def threads(rows: list[dict], out) -> None:
    out("\n== 2. threads: same account, <=5 min after the previous post = follow-up")
    by: dict[str, list] = {}
    for r in sorted(rows, key=lambda r: (r["u"], r["t"])):
        by.setdefault(r["u"], []).append(r)
    pairs, n_threads = [], 0
    for ps in by.values():
        cur = [ps[0]]
        for p in ps[1:] + [None]:
            if p is not None and (p["t"] - cur[-1]["t"]).total_seconds() <= 300:
                cur.append(p)
                continue
            if len(cur) > 1:
                n_threads += 1
                pairs += [(cur[0], f) for f in cur[1:]]
            cur = [p] if p else []
    ratios = [f["views"] / o["views"] for o, f in pairs]
    below = [x for x in ratios if x < 1]
    out(f"multi-post threads {n_threads}; follow-up posts {len(pairs)}; fewer views than the opener {len(below)}; "
        f"views ratio (follow-up / opener) median all {med(ratios):.2f}, median of those below 1: {med(below):.2f}; like rate lower than opener {sum(f['lr'] < o['lr'] for o, f in pairs)}")
    out("by account (follow-ups, with fewer views): " + str({u: (sum(1 for o, _ in pairs if o["u"] == u), sum(1 for o, f in pairs if o["u"] == u and f["views"] < o["views"])) for u in by}))
    out("exceptions (follow-up >= opener): " + str([(o["u"], f"{o['t']:%m-%d %H:%M}", round(f["views"] / o["views"], 2)) for o, f in pairs if f["views"] >= o["views"]]))


def invite_vs_heavy(rows: list[dict], out) -> None:
    out("\n== 3. hand-coded: short invitation openers vs rule-heavy prize openers (exploratory coding)")
    inv = [r for r in (find(rows, *k) for k in INVITE) if r]
    heavy = [r for r in (find(rows, *k) for k in HEAVY) if r]
    for label, g in (("invite", inv), ("rule-heavy", heavy)):
        out(f"{label}: n={len(g)}" + (f" | median interaction rate {pc(med([r['ir'] for r in g]))}, median reply rate {pc(med([r['rr'] for r in g]))}" if g else ""))
        for r in sorted(g, key=lambda r: (r["u"], r["t"])):
            ps = [x for x in rows if x["u"] == r["u"]]
            out(f"   {r['u']:12} {r['t']:%m-%d} chars {r['char_count']:>3} views {r['views']:>7} interaction {pc(r['ir']):>7} reply {pc(r['rr']):>6} "
                f"= {r['ir'] / med([x['ir'] for x in ps]):.1f}x the account median | {(r['text'] or '').replace(chr(10), ' ')[:34]}")


def features(rows: list[dict], out) -> None:
    out("\n== 4. one feature at a time: pooled median, and direction inside each account (accounts with >=3 posts on both sides)")

    def feat(name, pred, metric, mname):
        a, b = [r for r in rows if pred(r)], [r for r in rows if not pred(r)]
        per, ok = [], 0
        for u in ACCOUNTS:
            ua, ub = [r for r in a if r["u"] == u], [r for r in b if r["u"] == u]
            if ua and ub:
                up = med([metric(r) for r in ua]) > med([metric(r) for r in ub])
                per.append(f"{u[:6]} {len(ua)}/{len(ub)}{'↑' if up else '↓'}")
                if len(ua) >= 3 and len(ub) >= 3:
                    ok += 1 if up else 0
        comp = sum(1 for u in ACCOUNTS if len([r for r in a if r["u"] == u]) >= 3 and len([r for r in b if r["u"] == u]) >= 3)
        out(f"{name:20} {mname:15} yes n={len(a):>3} median {pc(med([metric(r) for r in a])):>6} | no n={len(b):>3} {pc(med([metric(r) for r in b])):>6} "
            f"| higher in {ok}/{comp} comparable accounts [{', '.join(per)}]")

    feat("short (<=30 chars)", lambda r: r["char_count"] <= 30, lambda r: r["lr"], "like rate")
    feat("question (？/?)", lambda r: bool(QUESTION.search(URL.sub(" ", r["text"] or ""))), lambda r: r["rr"], "reply rate")
    feat("evening (18-23h)", lambda r: r["t"].hour >= 18, lambda r: r["lr"], "like rate")
    feat("has a link", lambda r: r["url_count"] > 0, lambda r: r["ir"], "interaction rate")
    feat("has a hashtag", lambda r: r["hashtag_count"] > 0, lambda r: r["ir"], "interaction rate")
    feat("long (>150 chars)", lambda r: r["char_count"] > 150, lambda r: r["ir"], "interaction rate")
    link_by = {u: sum(1 for r in rows if r["u"] == u and r["url_count"] > 0) for u in ACCOUNTS}
    out(f"link posts per account {link_by}; evening posts per account " + str({u: sum(1 for r in rows if r["u"] == u and r["t"].hour >= 18) for u in ACCOUNTS}))
    q_abs = [r["replies"] for r in rows if QUESTION.search(URL.sub(" ", r["text"] or ""))], [r["replies"] for r in rows if not QUESTION.search(URL.sub(" ", r["text"] or ""))]
    out(f"replies per post, median: question {med(q_abs[0]):.1f} vs other {med(q_abs[1]):.1f}")


def teaser(rows: list[dict], out) -> None:
    out("\n== 5. dcard.tw: posts that point readers to the full article elsewhere ('原文來自' / '搜尋文章標題')")
    dc = [r for r in rows if r["u"] == "dcard.tw"]
    a, b = [r for r in dc if TEASER.search(r["text"] or "")], [r for r in dc if not TEASER.search(r["text"] or "")]
    for label, g in (("teaser", a), ("other", b)):
        out(f"{label}: n={len(g)}" + (f" median views {med([r['views'] for r in g]):.0f}, like rate {pc(med([r['lr'] for r in g]))}, interaction rate {pc(med([r['ir'] for r in g]))}" if g else ""))


def age(rows: list[dict], out) -> None:
    out("\n== 6. older vs newer posts (median views / interaction rate by thirds of the time range)")
    for u in ACCOUNTS:
        ps = sorted((r for r in rows if r["u"] == u), key=lambda r: r["t"])
        n = len(ps)
        t = [ps[: n // 3], ps[n // 3: 2 * n // 3], ps[2 * n // 3:]]
        out(f"{u:12} oldest/middle/newest third: views {[round(med([r['views'] for r in x])) for x in t]}, interaction {[pc(med([r['ir'] for r in x])) for x in t]}")


def main(argv: list[str] | None = None, db: Db | None = None) -> str:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["login", "anonymous"], default="login")
    args = ap.parse_args(argv)
    rows = load(args.mode, db)
    lines: list[str] = []
    out = lines.append
    out(f"mode={args.mode}  posts={len(rows)}  per account { {u: sum(r['u'] == u for r in rows) for u in ACCOUNTS} }  (real posts only)\n")
    per_account(rows, out)
    threads(rows, out)
    invite_vs_heavy(rows, out)
    features(rows, out)
    teaser(rows, out)
    age(rows, out)
    text = "\n".join(lines)
    print(text)
    return text


if __name__ == "__main__":
    main()
