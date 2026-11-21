"""Mock post generator (source='mock').

Used only when the logged-out scrape returns fewer than 30 posts (see docs/feasibility.md).
Field structure is identical to real rows; the numeric distributions are taken from the job's
own real posts. Three known patterns are planted on purpose so the analysis can be validated:

    1. question posts ("...？")      -> reply rate  x QUESTION_REPLY_BOOST
    2. evening posts (18:00-23:59)   -> like rate   x EVENING_LIKE_BOOST
    3. posts with a link             -> all interaction rates x LINK_PENALTY

Details and validation results: docs/mock_design.md. Deterministic per job (seeded by job id).
"""

from __future__ import annotations

import math
import random
import statistics as st
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .features import text_features

TAIPEI = ZoneInfo("Asia/Taipei")

# --- planted patterns (keep in sync with docs/mock_design.md) -------------------------------
QUESTION_REPLY_BOOST = 3.0
EVENING_LIKE_BOOST = 2.0
LINK_PENALTY = 0.4
EVENING_HOURS = range(18, 24)

# Share of mock posts having each trait. Assigned as a balanced design (exact counts, shuffled), not
# independent coin flips, so a 22-post sample can't end up with e.g. only 4 evening posts by bad luck.
P_QUESTION, P_EVENING, P_LINK, P_HASHTAG, P_MENTION = 0.45, 0.45, 0.30, 0.20, 0.15
NOISE_SIGMA = 0.40  # log-normal noise on every rate (kept small so planted effects stay detectable)
RATE_FLOORS = {"likes": 0.003, "replies": 0.001, "reposts": 0.0005, "quotes": 0.0001}
WINDOW_DAYS = 60

STATEMENTS = [
    "新品正式上市，快來嚐鮮", "本週限定優惠，把握時間", "今天天氣不錯，出門走走", "感謝大家一直以來的支持",
    "小編精選推薦給你", "同仁用心準備中，敬請期待", "跟我們一起度過愉快的週末", "會員專屬好康提前曝光",
    "集點活動即將開跑，別錯過", "全新座位區開放，歡迎體驗", "季節限定口味回歸", "今天也要好好吃飯",
    "新的一週，一起加油", "限量商品數量有限，售完為止", "謝謝你們的留言與回饋", "門市服務再升級",
]
QUESTIONS = [
    "你今天想吃什麼？", "最近有什麼新品值得推薦？", "你最喜歡哪一種口味？", "週末有什麼計畫嗎？",
    "有人試過這個組合嗎？", "如果只能選一個，你會選哪個？", "你都在哪個時段來光顧？",
]
HASHTAGS = ["#週末好康", "#新品", "#限時優惠", "#日常", "#推薦"]


def _rates(real: list[dict]) -> dict[str, float]:
    """Base interaction rate per metric = median of the real rates, floored (real medians are often ~0)."""
    out = {}
    for k in ("likes", "replies", "reposts", "quotes"):
        rs = [r[k] / r["views"] for r in real if r.get("views")]
        out[k] = max(st.median(rs) if rs else 0.0, RATE_FLOORS[k])
    return out


def _round_views(v: float) -> tuple[int, bool]:
    # Threads shows exact views below 10,000 and "x.x 萬" (nearest 1,000) from 10,000 up; mimic that.
    v = max(int(v), 50)
    return (int(round(v, -3)), True) if v >= 10_000 else (v, False)


def _balanced(rng: random.Random, n: int, p: float) -> list[bool]:
    flags = [True] * round(n * p) + [False] * (n - round(n * p))
    rng.shuffle(flags)
    return flags


def _sample_hour(rng: random.Random, real_hours: list[int], evening: bool) -> int:
    """Hour within the requested class: half from the job's real hours of that class, half uniform."""
    lo, hi = (18, 23) if evening else (8, 17)
    pool = [h for h in real_hours if lo <= h <= hi]
    if pool and rng.random() < 0.5:
        return rng.choice(pool)
    return rng.randint(lo, hi)


def _make_text(rng: random.Random, username: str, target_len: int, question: bool, link: bool,
               hashtag: bool, mention: bool, n: int) -> str:
    parts: list[str] = []
    while sum(len(p) + 1 for p in parts) < target_len * 0.7:
        parts.append(rng.choice(STATEMENTS))
    body = "，".join(dict.fromkeys(parts)) + "。"  # drop duplicate sentences
    if question:
        body += rng.choice(QUESTIONS)
    if hashtag:
        body += " " + rng.choice(HASHTAGS)
    if mention:
        body += f" @{username}"
    if link:
        body += f" https://example.com/promo/{n:03d}"
    return body


def generate_mock(job_id: str, username: str, real_rows: list[dict], target: int = 30) -> list[dict]:
    """Rows to add so that real + mock = target (empty if there are already enough real rows)."""
    need = target - len(real_rows)
    if need <= 0:
        return []
    with_views = [r for r in real_rows if r.get("views")]
    if len(with_views) < 3:
        raise ValueError("need at least 3 real posts with views to derive distributions for mock data")

    rng = random.Random(job_id)
    base = _rates(with_views)

    log_views = [math.log(r["views"]) for r in with_views]
    mu, sd = st.mean(log_views), min(st.pstdev(log_views), 1.0)
    lens = [math.log(max(r["char_count"], 5)) for r in real_rows]
    len_mu, len_sd = st.mean(lens), max(st.pstdev(lens), 0.3)

    real_dt = [datetime.fromisoformat(r["posted_at"].replace("Z", "+00:00")).astimezone(TAIPEI) for r in real_rows]
    real_hours = [d.hour for d in real_dt]
    newest = max(real_dt)

    questions, evenings, links = (_balanced(rng, need, p) for p in (P_QUESTION, P_EVENING, P_LINK))
    hashtags, mentions = (_balanced(rng, need, p) for p in (P_HASHTAG, P_MENTION))

    rows = []
    for i in range(need):
        question, evening, link, hashtag, mention = questions[i], evenings[i], links[i], hashtags[i], mentions[i]

        day = newest - timedelta(days=rng.randint(0, WINDOW_DAYS))
        hour = _sample_hour(rng, real_hours, evening)
        posted = day.replace(hour=hour, minute=rng.randint(0, 59), second=rng.randint(0, 59), microsecond=0)
        if posted > newest:
            posted -= timedelta(days=1)

        views, rounded = _round_views(math.exp(rng.gauss(mu, sd)))
        text = _make_text(rng, username, int(math.exp(rng.gauss(len_mu, len_sd))), question, link, hashtag, mention, i + 1)

        mult = {"likes": 1.0, "replies": 1.0, "reposts": 1.0, "quotes": 1.0}
        if question:
            mult["replies"] *= QUESTION_REPLY_BOOST
        if evening:
            mult["likes"] *= EVENING_LIKE_BOOST
        if link:
            mult = {k: v * LINK_PENALTY for k, v in mult.items()}
        counts = {k: max(0, round(views * base[k] * mult[k] * math.exp(rng.gauss(0, NOISE_SIGMA)))) for k in base}

        rows.append({
            "job_id": job_id,
            "post_url": f"mock://{username}/{i + 1:03d}",
            "posted_at": posted.isoformat(),
            "text": text,
            "views": views,
            "views_rounded": rounded,
            **counts,
            **text_features(text),
            "source": "mock",
        })
    return rows
