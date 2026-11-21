"""Analysis (T6 + T8): turns a job's posts into the JSON stored in job_summaries.

Every result exists in two versions, as {"all": ..., "real": ...}:
  all  = real + mock posts      real = only source='real'
(for a job without mock posts the two are identical).

Definitions
  interaction rate = (likes + replies + reposts + quotes) / views          (posts with views only)
  like rate / reply rate = likes / views, replies / views
  percentile       = (# posts with a smaller value + 0.5 * # equal) / n    (within the account)
  evening          = posted 18:00-23:59 Taipei time
  question         = text contains ？ or ? (outside URLs)

Grouping (PRD): posts with views < 20% of the account's median views are NOT grouped (their rates are
unreliable) and are left out of the percentile ranking too. For the rest:
  低迷型 = like pct < 0.5 and reply pct < 0.5
  討論型 = reply pct >= 0.5 and reply pct >= like pct
  共鳴型 = like pct >= 0.5 and like pct > reply pct
"""

from __future__ import annotations

import math
import random
import re
import statistics as st
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

import jieba

from .features import URL_RE

jieba.setLogLevel(60)  # silence "Building prefix dict" noise
TAIPEI = ZoneInfo("Asia/Taipei")

WEEKDAYS = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
SLOTS = [("凌晨 00–05", 0, 5), ("上午 06–11", 6, 11), ("下午 12–17", 12, 17), ("晚間 18–23", 18, 23)]
LENGTH_BINS = [("≤50 字", 0, 50), ("51–150 字", 51, 150), ("151–300 字", 151, 300), (">300 字", 301, 10**9)]
GROUPS = ("低迷型", "討論型", "共鳴型")
UNGROUPED = "未分組"
MIN_VIEWS_RATIO = 0.2
MIN_SIDE_N = 3  # minimum posts per side for a comparison
PERMUTATIONS = 5000

STOPWORDS = set("的 了 是 在 和 與 及 也 都 就 你 我 他 她 它 們 這 那 有 為 個 一 不 要 會 可 以 對 之 如 或 但 而 並 很 更 讓 來 去 到 說 看 啊 吧 呢 喔 哦 嗎 吧 一起 我們 你們 大家 可以 我們的 自己 今天 什麼 還是 因為 所以 如果 就是 還有 已經 一個 沒有 這個 那個".split())


# ----------------------------------------------------------------------------- helpers
def _dt(p: dict) -> datetime:
    return datetime.fromisoformat(p["posted_at"].replace("Z", "+00:00")).astimezone(TAIPEI)


def _has_views(p: dict) -> bool:
    return bool(p.get("views"))


def rate(p: dict, *fields: str) -> float | None:
    return sum(p[f] for f in fields) / p["views"] if _has_views(p) else None


def inter_rate(p: dict) -> float | None:
    return rate(p, "likes", "replies", "reposts", "quotes")


def is_question(p: dict) -> bool:
    return bool(re.search(r"[？?]", URL_RE.sub(" ", p.get("text") or "")))


def is_evening(p: dict) -> bool:
    return 18 <= _dt(p).hour <= 23


def has_link(p: dict) -> bool:
    return (p.get("url_count") or 0) > 0


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _round(x: float | None, nd: int = 5) -> float | None:
    return None if x is None else round(x, nd)


def percentiles(values: list[float]) -> list[float]:
    n = len(values)
    return [(sum(v < x for v in values) + 0.5 * sum(v == x for v in values)) / n for x in values]


def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 4:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = _mean(rx), _mean(ry)
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if sx == 0 or sy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / (sx * sy)


def _logr(x: float) -> float:
    return math.log(x + 1e-4)  # rates can be exactly 0


def compare(a: list[float], b: list[float], seed: int = 7) -> dict:
    """Is group a's rate different from group b's? Geometric-mean ratio + permutation test on mean(log rate)."""
    if len(a) < MIN_SIDE_N or len(b) < MIN_SIDE_N:
        return {"n_a": len(a), "n_b": len(b), "enough_data": False}
    la, lb = sorted(_logr(x) for x in a), sorted(_logr(x) for x in b)  # sorted: result independent of input order
    obs = _mean(la) - _mean(lb)
    pool, na = la + lb, len(la)
    rng = random.Random(seed)
    hits = 0
    for _ in range(PERMUTATIONS):
        rng.shuffle(pool)
        if abs(_mean(pool[:na]) - _mean(pool[na:])) >= abs(obs) - 1e-12:
            hits += 1
    return {
        "n_a": len(a), "n_b": len(b), "enough_data": True,
        "mean_a": _round(_mean(a)), "mean_b": _round(_mean(b)),
        "ratio": _round(math.exp(obs), 3),  # geometric-mean ratio a/b
        "p_value": round((hits + 1) / (PERMUTATIONS + 1), 4),
    }


# ----------------------------------------------------------------------------- text
def keywords(posts: list[dict], top: int = 10) -> list[dict]:
    """Top words by number of posts containing them (jieba, 2+ chars, no stopwords/numbers)."""
    df: Counter = Counter()
    for p in posts:
        text = URL_RE.sub(" ", p.get("text") or "")
        text = re.sub(r"[#@]\S+", " ", text)
        words = {w.strip() for w in jieba.lcut(text)}
        df.update(w for w in words if len(w) >= 2 and w not in STOPWORDS and re.search(r"[\w]", w) and not w.isdigit())
    return [{"word": w, "posts": c} for w, c in df.most_common(top)]


def hashtags(posts: list[dict], top: int = 10) -> list[dict]:
    c: Counter = Counter()
    for p in posts:
        c.update(re.findall(r"(?<![\w&#])#\w+", URL_RE.sub(" ", p.get("text") or "")))
    return [{"tag": t, "count": n} for t, n in c.most_common(top)]


# ----------------------------------------------------------------------------- metrics
def metrics(posts: list[dict]) -> dict:
    n = len(posts)
    rated = [p for p in posts if _has_views(p)]
    out = {
        "n_posts": n,
        "n_real": sum(p["source"] == "real" for p in posts),
        "n_mock": sum(p["source"] == "mock" for p in posts),
        "avg": {k: _round(_mean([p[k] for p in posts]), 2) for k in ("likes", "replies", "reposts", "quotes", "views", "char_count")},
        "median": {k: st.median([p[k] for p in posts]) if posts else None for k in ("likes", "replies", "reposts", "quotes")},
        "avg_interaction_rate": _round(_mean([inter_rate(p) for p in rated])),
        "avg_like_rate": _round(_mean([rate(p, "likes") for p in rated])),
        "avg_reply_rate": _round(_mean([rate(p, "replies") for p in rated])),
    }
    # weekday x time-slot
    cells = {(d, s): [] for d in range(7) for s in range(len(SLOTS))}
    for p in posts:
        t = _dt(p)
        s = next(i for i, (_, lo, hi) in enumerate(SLOTS) if lo <= t.hour <= hi)
        cells[(t.weekday(), s)].append(p)
    out["time_distribution"] = {
        "weekdays": WEEKDAYS, "slots": [s[0] for s in SLOTS],
        "counts": [[len(cells[(d, s)]) for s in range(len(SLOTS))] for d in range(7)],
        "avg_interaction_rate": [[_round(_mean([inter_rate(p) for p in cells[(d, s)] if _has_views(p)])) for s in range(len(SLOTS))] for d in range(7)],
    }
    # text length vs interaction
    bins = []
    for label, lo, hi in LENGTH_BINS:
        ps = [p for p in rated if lo <= p["char_count"] <= hi]
        bins.append({"label": label, "n": len(ps), "avg_interaction_rate": _round(_mean([inter_rate(p) for p in ps]))})
    out["length_vs_interaction"] = {
        "bins": bins,
        "spearman": _round(spearman([p["char_count"] for p in rated], [inter_rate(p) for p in rated]), 3),
    }
    out["keywords"] = keywords(posts)
    out["hashtags"] = hashtags(posts)
    types = Counter(p["post_type"] for p in posts)
    out["post_types"] = [
        {"type": t, "n": c, "share": round(c / n, 3) if n else 0,
         "avg_interaction_rate": _round(_mean([inter_rate(p) for p in rated if p["post_type"] == t]))}
        for t, c in types.most_common()
    ]
    return out


def _brief(p: dict) -> dict:
    return {
        "post_url": p["post_url"], "source": p["source"], "posted_at": _dt(p).isoformat(),
        "text": (p.get("text") or "")[:100], "views": p.get("views"), "likes": p["likes"], "replies": p["replies"],
        "reposts": p["reposts"], "quotes": p["quotes"], "interaction_rate": _round(inter_rate(p)),
    }


def top_posts(posts: list[dict], k: int = 5) -> list[dict]:
    rated = [p for p in posts if _has_views(p)]
    return [_brief(p) for p in sorted(rated, key=inter_rate, reverse=True)[:k]]


# ----------------------------------------------------------------------------- grouping
def assign_groups(posts: list[dict]) -> dict[str, str]:
    """post_url -> group label (低迷型 / 討論型 / 共鳴型 / 未分組)."""
    rated = [p for p in posts if _has_views(p)]
    labels = {p["post_url"]: UNGROUPED for p in posts}
    if not rated:
        return labels
    med = st.median(p["views"] for p in rated)
    eligible = [p for p in rated if p["views"] >= MIN_VIEWS_RATIO * med]
    if len(eligible) < MIN_SIDE_N:
        return labels
    lp = percentiles([rate(p, "likes") for p in eligible])
    rp = percentiles([rate(p, "replies") for p in eligible])
    for p, l, r in zip(eligible, lp, rp):
        if l < 0.5 and r < 0.5:
            g = "低迷型"
        elif r >= 0.5 and r >= l:
            g = "討論型"
        else:
            g = "共鳴型"
        labels[p["post_url"]] = g
        p["_like_pct"], p["_reply_pct"] = l, r
    return labels


def _profile(ps: list[dict]) -> dict:
    """Same toolkit for every group: keywords, post types, length."""
    rated = [p for p in ps if _has_views(p)]
    return {
        "n": len(ps),
        "avg_views": _round(_mean([p["views"] for p in rated]), 0),
        "avg_like_rate": _round(_mean([rate(p, "likes") for p in rated])),
        "avg_reply_rate": _round(_mean([rate(p, "replies") for p in rated])),
        "avg_char_count": _round(_mean([p["char_count"] for p in ps]), 1),
        "keywords": keywords(ps, 6),
        "post_types": [{"type": t, "n": c} for t, c in Counter(p["post_type"] for p in ps).most_common()],
        "question_share": _round(_mean([float(is_question(p)) for p in ps]), 2),
        "evening_share": _round(_mean([float(is_evening(p)) for p in ps]), 2),
        "link_share": _round(_mean([float(has_link(p)) for p in ps]), 2),
    }


REP_KEY = {  # how a group's representative posts are picked: the most typical = most extreme on its defining trait
    "討論型": lambda p: -p["_reply_pct"],
    "共鳴型": lambda p: -p["_like_pct"],
    "低迷型": lambda p: p["_like_pct"] + p["_reply_pct"],
}


def group_analysis(posts: list[dict]) -> dict:
    labels = assign_groups(posts)
    by_group = {g: [p for p in posts if labels[p["post_url"]] == g] for g in (*GROUPS, UNGROUPED)}
    rated = [p for p in posts if _has_views(p)]
    out = {
        "rules": "views < 20% of median -> 未分組; 低迷型 like&reply pct < 0.5; 討論型 reply pct >= 0.5 and >= like pct; 共鳴型 like pct >= 0.5 and > reply pct",
        "median_views": st.median(p["views"] for p in rated) if rated else None,
        "counts": {g: len(ps) for g, ps in by_group.items()},
        "assignments": labels,
        "groups": {},
    }
    for g in GROUPS:
        members = by_group[g]
        reps = sorted(members, key=REP_KEY[g])[:5]  # 3-5 representatives (fewer only if the group is smaller)
        out["groups"][g] = {
            "n_members": len(members),
            "representatives": [{**_brief(p), "like_pct": _round(p["_like_pct"], 2), "reply_pct": _round(p["_reply_pct"], 2)} for p in reps],
            "profile_of_representatives": _profile(reps) if reps else None,
        }
    return out


# ----------------------------------------------------------------------------- insights
def pattern_checks(posts: list[dict]) -> list[dict]:
    """Generic hypothesis checks. These are what must rediscover the patterns planted in mock data."""
    rated = [p for p in posts if _has_views(p)]
    specs = [
        ("question_reply", "提問句 vs 非提問句：回覆率", is_question, lambda p: rate(p, "replies"), "提問句貼文", "其他貼文"),
        ("evening_like", "晚間（18–23 點）vs 其他時段：按讚率", is_evening, lambda p: rate(p, "likes"), "晚間發文", "其他時段發文"),
        ("link_interaction", "含連結 vs 無連結：互動率", has_link, inter_rate, "含連結貼文", "無連結貼文"),
    ]
    out = []
    for key, title, pred, metric, name_a, name_b in specs:
        a = [metric(p) for p in rated if pred(p)]
        b = [metric(p) for p in rated if not pred(p)]
        c = compare(a, b)
        if not c["enough_data"]:
            text = f"{title}：樣本不足（{name_a} {c['n_a']} 篇、{name_b} {c['n_b']} 篇，每組至少需要 {MIN_SIDE_N} 篇）。"
            verdict = "insufficient"
        else:
            r, p_val = c["ratio"], c["p_value"]
            verdict = ("higher" if r > 1 else "lower") if p_val < 0.05 else "no_clear_difference"
            direction = "高於" if r > 1 else "低於"
            sig = "差異達統計顯著" if p_val < 0.05 else "差異不顯著，不能下結論"
            text = f"{title}：{name_a}（{c['n_a']} 篇）{direction}{name_b}（{c['n_b']} 篇），約 {r:.2f} 倍（幾何平均比），{sig}（p={p_val}）。"
        out.append({"key": key, "title": title, "verdict": verdict, "text": text, "evidence": c})
    return out


def insights(posts: list[dict]) -> list[dict]:
    items = pattern_checks(posts)
    n = len(posts)
    if n < 10:
        items.insert(0, {"key": "small_sample", "title": "樣本數少", "verdict": "info", "evidence": {"n": n},
                         "text": f"只有 {n} 篇貼文，以下比較的統計力很低，僅供參考。"})
    rated = [p for p in posts if _has_views(p)]
    best = max(SLOTS, key=lambda s: _mean([inter_rate(p) for p in rated if s[1] <= _dt(p).hour <= s[2]] or [-1]), default=None)
    if rated and best:
        slot_posts = [p for p in rated if best[1] <= _dt(p).hour <= best[2]]
        if slot_posts:
            items.append({"key": "best_slot", "title": "互動率最高的時段", "verdict": "info",
                          "evidence": {"slot": best[0], "n": len(slot_posts)},
                          "text": f"{best[0]} 的平均互動率最高（{len(slot_posts)} 篇）。"})
    return items


# ----------------------------------------------------------------------------- entry point
def analyze(posts: list[dict]) -> dict:
    """posts = rows of the `posts` table for one job -> payloads for job_summaries (+ per-post group labels)."""
    scopes = {"all": posts, "real": [p for p in posts if p["source"] == "real"]}
    result = {"metrics": {}, "top_posts": {}, "group_analysis": {}, "insights": {}}
    for name, ps in scopes.items():
        if not ps:
            continue
        ps = [dict(p) for p in ps]  # grouping annotates rows; keep the caller's data untouched
        result["metrics"][name] = metrics(ps)
        result["top_posts"][name] = top_posts(ps)
        result["group_analysis"][name] = group_analysis(ps)
        result["insights"][name] = insights(ps)
    # posts.group follows the "all" scope; the real-only labels stay in group_analysis.real.assignments
    result["post_groups"] = result["group_analysis"]["all"]["assignments"]
    return result
