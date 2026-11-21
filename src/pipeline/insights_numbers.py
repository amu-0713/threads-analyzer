"""Recompute every number cited in reports/insights.md from the database.

    python -m src.pipeline.insights_numbers

Uses ONLY source='real' posts of the four brand accounts (the real-only job of each; mock rows are never read).
Prints the figures; reports/insights.md was written against this output.
"""

from __future__ import annotations

import re
import statistics as st
from datetime import datetime
from zoneinfo import ZoneInfo

from .db import Db

ACCOUNTS = ["7eleventw", "starbuckstw", "dcard.tw", "pchome24h"]
TZ = ZoneInfo("Asia/Taipei")
URL = re.compile(r"https?://\S+")


def load() -> list[dict]:
    db, rows = Db(), []
    for u in ACCOUNTS:
        jobs = db.select("jobs", {"username": f"eq.{u}", "status": "eq.done", "select": "id,created_at", "order": "created_at"})
        for j in jobs:  # the real-only job = the one without mock rows
            ps = db.select("posts", {"job_id": f"eq.{j['id']}", "select": "*"})
            if any(p["source"] == "mock" for p in ps):
                continue
            for p in ps:
                assert p["source"] == "real" and p["views"]
                p["u"] = u
                p["t"] = datetime.fromisoformat(p["posted_at"].replace("Z", "+00:00")).astimezone(TZ)
                p["lr"], p["rr"] = p["likes"] / p["views"], p["replies"] / p["views"]
                p["ir"] = (p["likes"] + p["replies"] + p["reposts"] + p["quotes"]) / p["views"]
                rows.append(p)
            break
    return rows


def med(xs):  # percent, 2 decimals
    return round(100 * st.median(xs), 2)


def main() -> None:
    rows = load()
    print(f"posts: {len(rows)}  per account: { {u: sum(r['u'] == u for r in rows) for u in ACCOUNTS} }")

    print("\n== per account (median views / likes / like rate, newest post, top-view post age in days)")
    for u in ACCOUNTS:
        ps = [r for r in rows if r["u"] == u]
        top, newest = max(ps, key=lambda r: r["views"]), max(r["t"] for r in ps)
        print(f"{u:12} n={len(ps)} views={st.median(r['views'] for r in ps):.0f} likes={st.median(r['likes'] for r in ps):.0f} "
              f"lr={med([r['lr'] for r in ps])}% | top views {top['views']} on {top['t']:%m-%d} ({(newest - top['t']).days} d before newest)")

    print("\n== F1 prize posts")
    for key in ["抽 LNGSHOT", "限時抽", "分享你的透卡自拍", "在本篇貼文下方留言上傳韓國商品"]:
        r = next(r for r in rows if key in (r["text"] or ""))
        print(f"{r['u']:10} {r['t']:%m-%d %H:%M} len={r['char_count']:>3} views={r['views']:>6} reply_rate={r['rr']*100:.2f}% interaction={r['ir']*100:.2f}% url={r['url_count']}")

    print("\n== F2 threads: same account, <=5 min apart; follow-up vs opener")
    by: dict[str, list] = {}
    for r in sorted(rows, key=lambda r: (r["u"], r["t"])):
        by.setdefault(r["u"], []).append(r)
    pairs = []
    for u, ps in by.items():
        cur = [ps[0]]
        for p in ps[1:] + [None]:
            if p is not None and (p["t"] - cur[-1]["t"]).total_seconds() <= 300:
                cur.append(p)
                continue
            pairs += [(cur[0], f) for f in cur[1:]]
            cur = [p] if p else []
    n_thread = len({id(o) for o, _ in pairs})
    ratios = [f["views"] / o["views"] for o, f in pairs]
    lower = [x < 1 for x in ratios]
    print(f"multi-post threads: {n_thread}, follow-up posts: {len(pairs)}, with fewer views than opener: {sum(lower)}")
    print("view ratios (follow-up / opener) of the ones below 1:", sorted(round(x, 2) for x in ratios if x < 1), "median", round(st.median([x for x in ratios if x < 1]), 2))
    print("exception:", [(o["u"], f"{o['t']:%m-%d %H:%M:%S}", f["views"] / o["views"]) for (o, f) in pairs if f["views"] >= o["views"]])
    lr_lower = sum(f["lr"] < o["lr"] for o, f in pairs)
    print(f"follow-ups with lower like rate than opener: {lr_lower}/{len(pairs)}")

    print("\n== F3 short text (<=30 chars) vs longer, like rate (median)")
    short = [r for r in rows if r["char_count"] <= 30]
    longer = [r for r in rows if r["char_count"] > 30]
    print(f"short n={len(short)} median={med([r['lr'] for r in short])}% min/max={min(r['lr'] for r in short)*100:.2f}/{max(r['lr'] for r in short)*100:.2f}% | longer n={len(longer)} median={med([r['lr'] for r in longer])}%")
    nd_s = [r for r in short if r["u"] != "dcard.tw"]
    nd_l = [r for r in longer if r["u"] != "dcard.tw"]
    print(f"excluding dcard.tw: short n={len(nd_s)} {med([r['lr'] for r in nd_s])}% | longer n={len(nd_l)} {med([r['lr'] for r in nd_l])}%")
    print("short posts:", sorted((round(r['lr'] * 100, 2), r['u'], r['char_count']) for r in short))

    print("\n== F4 questions / evening")
    q = lambda r: bool(re.search(r"[？?]", URL.sub(" ", r["text"] or "")))
    qa, qb = [r for r in rows if q(r)], [r for r in rows if not q(r)]
    print(f"question n={len(qa)} reply-rate median {med([r['rr'] for r in qa])}% | other n={len(qb)} {med([r['rr'] for r in qb])}% | question posts by account {{{', '.join(f'{u}: {sum(q(r) for r in rows if r[chr(117)] == u)}' for u in ACCOUNTS)}}}")
    ev = [r for r in rows if 18 <= r["t"].hour <= 23]
    ot = [r for r in rows if r not in ev]
    print(f"evening n={len(ev)} like-rate median {med([r['lr'] for r in ev])}% | other n={len(ot)} {med([r['lr'] for r in ot])}% | evening by account { {u: sum(1 for r in ev if r['u'] == u) for u in ACCOUNTS} }")
    ev2, ot2 = [r for r in ev if r["u"] != "dcard.tw"], [r for r in ot if r["u"] != "dcard.tw"]
    print(f"excluding dcard.tw: evening n={len(ev2)} {med([r['lr'] for r in ev2])}% | other n={len(ot2)} {med([r['lr'] for r in ot2])}%")


if __name__ == "__main__":
    main()
