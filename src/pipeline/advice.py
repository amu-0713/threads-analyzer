"""Pre-generate the AI advice for jobs and store it in job_summaries.llm_advice (server-side, no browser).

    python -m src.pipeline.advice --job <job-id> [--job <job-id> ...]
    python -m src.pipeline.advice --all            # every finished job that has a summary
    python -m src.pipeline.advice --all --dry-run  # print the advice, store nothing

Needs LLM_API_KEY in .env (Gemini API key; LLM_MODEL optionally overrides the model) plus the usual
SUPABASE_* values. The prompt mirrors buildPrompt() in src/lib/llm.ts (the dashboard's "regenerate" button):
real-only statistics (medians first, rates as percentages), aggregates only, no raw post text. Nothing is stored unless the answer ends normally.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import statistics
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from . import config
from .db import Db

log = logging.getLogger("pipeline.advice")
TAIPEI = ZoneInfo("Asia/Taipei")

# Fastest lightweight text model measured through the API's own model list (2026-11-21); override with LLM_MODEL.
DEFAULT_MODEL = "gemini-3.1-flash-lite"
API = "https://generativelanguage.googleapis.com/v1beta/models"
MIN_CHARS = 150  # a real answer to this prompt is ~400+ characters; anything far shorter is treated as broken


class AdviceError(RuntimeError):
    pass


def _median(xs: list[float]) -> float | None:
    return statistics.median(xs) if xs else None


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _pct(x: float | None) -> str | None:  # rates as percentages with 2 decimals ("3.59%")
    return None if x is None else f"{x * 100:.2f}%"


def _num(x: float | None, d: int = 0) -> float | int | None:
    if x is None:
        return None
    v = float(f"{x:.{d}f}")
    return int(v) if v == int(v) else v  # same as JS: 32.0 -> 32


SLOTS = [("凌晨 00–05", 0, 5), ("上午 06–11", 6, 11), ("下午 12–17", 12, 17), ("晚間 18–23", 18, 23)]
BINS = [("50 字以內", 0, 50), ("51–150 字", 51, 150), ("151–300 字", 151, 300), ("300 字以上", 301, 10**9)]


def advice_data(username: str, summary: dict, posts: list[dict]) -> dict:
    """Everything the model sees, from the account's REAL posts; medians first, every rate a percentage.
    Mirrors adviceData() in src/lib/llm.ts (the dashboard's regenerate button) — keep the two in sync."""
    real = [p for p in posts if p.get("source") == "real" and p.get("views")]
    ir = lambda p: (p["likes"] + p["replies"] + p["reposts"] + p["quotes"]) / p["views"]  # noqa: E731
    lr = lambda p: p["likes"] / p["views"]  # noqa: E731
    rr = lambda p: p["replies"] / p["views"]  # noqa: E731
    col = lambda f, agg: agg([f(p) for p in real])  # noqa: E731
    hour = lambda p: datetime.fromisoformat(p["posted_at"].replace("Z", "+00:00")).astimezone(TAIPEI).hour  # noqa: E731
    g = (summary.get("group_analysis") or {}).get("real")
    share = lambda x: None if x is None else f"{round(x * 100)}%"  # noqa: E731
    out: dict = {
        "帳號": f"@{username}",
        "真實貼文數": len(real),
        "說明": "中位數是主要參考；平均數容易被單一爆文拉高。所有比率皆為百分比。",
        "中位數": {
            "觀看": _num(col(lambda p: p["views"], _median)), "讚": _num(col(lambda p: p["likes"], _median), 1),
            "回覆": _num(col(lambda p: p["replies"], _median), 1), "轉發": _num(col(lambda p: p["reposts"], _median), 1),
            "字數": _num(col(lambda p: p["char_count"], _median)),
            "互動率": _pct(col(ir, _median)), "按讚率": _pct(col(lr, _median)), "回覆率": _pct(col(rr, _median)),
        },
        "平均數": {
            "觀看": _num(col(lambda p: p["views"], _mean)), "讚": _num(col(lambda p: p["likes"], _mean), 1),
            "回覆": _num(col(lambda p: p["replies"], _mean), 1), "轉發": _num(col(lambda p: p["reposts"], _mean), 1),
            "互動率": _pct(col(ir, _mean)), "按讚率": _pct(col(lr, _mean)), "回覆率": _pct(col(rr, _mean)),
        },
    }
    types = list(dict.fromkeys(p.get("post_type") or "未分類" for p in real))
    out["貼文類型"] = [{"類型": t, "篇數": len(ps), "互動率中位數": _pct(_median([ir(p) for p in ps]))}
                       for t in types for ps in [[p for p in real if (p.get("post_type") or "未分類") == t]]]
    out["字數區間"] = [{"區間": label, "篇數": len(ps), "互動率中位數": _pct(_median([ir(p) for p in ps]))}
                       for label, lo, hi in BINS for ps in [[p for p in real if lo <= p["char_count"] <= hi]] if ps]
    out["發文時段"] = [{"時段": label, "篇數": len(ps), "互動率中位數": _pct(_median([ir(p) for p in ps]))}
                       for label, lo, hi in SLOTS for ps in [[p for p in real if p.get("posted_at") and lo <= hour(p) <= hi]] if ps]
    kw = ((summary.get("metrics") or {}).get("real") or {}).get("keywords")
    if kw is not None:
        out["常見關鍵字"] = [k["word"] for k in kw[:8]]
    if g:
        out["分組篇數"] = g.get("counts")
        groups = {}
        for k, v in (g.get("groups") or {}).items():
            pr = v.get("profile_of_representatives")
            groups[k] = pr and {
                "代表貼文數": pr.get("n"), "平均字數": _num(pr.get("avg_char_count")), "平均按讚率": _pct(pr.get("avg_like_rate")),
                "平均回覆率": _pct(pr.get("avg_reply_rate")), "常見關鍵字": [w["word"] for w in (pr.get("keywords") or [])[:5]],
                "提問句占比": share(pr.get("question_share")), "晚間占比": share(pr.get("evening_share")), "含連結占比": share(pr.get("link_share")),
            }
        out["各組代表貼文特徵"] = groups
    return out


def build_prompt(username: str, summary: dict, posts: list[dict]) -> str:
    return "\n".join([
        "你是社群媒體數據分析顧問。以下是某個 Threads 帳號「僅真實貼文」的統計摘要（JSON）。",
        "請用繁體中文，依據資料給 3–5 點具體、可執行的內容策略建議。",
        "規則：只能引用資料中有的數字與現象；樣本很少（真實貼文只有個位數）時，必須明講結論僅供參考、不可過度推論；",
        "不要編造資料中沒有的事實；不要提到你看不到的貼文內容；每點建議一句話說明依據。",
        "直接列出建議，不要自我介紹或寒暄。",
        "樣本只有個位數，不可使用「顯著」「明顯優於」等統計推論用語。",
        "引用數字時優先使用中位數；平均數容易被單一爆文拉高，若引用平均數要註明。",
        "所有比率一律用百分比表示（例如 3.59%），不要輸出 0.0359 這樣的小數。",
        "篇數少於 3 篇的字數區間、發文時段、貼文類型或分組，不可作為建議的依據；若要提到，必須註明只有幾篇。",
        "輸出純文字，不要使用任何 Markdown 符號（不要用 **、#、*、`）；每點以「1.」「2.」編號開頭，各佔一段。",
        "",
        json.dumps(advice_data(username, summary, posts), ensure_ascii=False),
    ])


def _request(client: httpx.Client, model: str, key: str, prompt: str, minimal_thinking: bool) -> httpx.Response:
    cfg: dict = {"temperature": 0.4, "maxOutputTokens": 4096}
    if minimal_thinking:  # measured: thinkingLevel "minimal" -> 0 thought tokens, ~2 s (thinkingBudget: 0 is rejected)
        cfg["thinkingConfig"] = {"thinkingLevel": "minimal"}
    return client.post(f"{API}/{model}:generateContent", headers={"x-goog-api-key": key},
                       json={"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": cfg})


def generate(prompt: str, key: str, model: str, client: httpx.Client | None = None, retries: int = 2) -> str:
    """One complete answer or an AdviceError. Retries 429/5xx (e.g. 503 'high demand') with back-off."""
    own = client is None
    client = client or httpx.Client(timeout=60)
    try:
        for attempt in range(retries + 1):
            res = _request(client, model, key, prompt, True)
            if res.status_code == 400:  # parameter not accepted by this model -> default request
                res = _request(client, model, key, prompt, False)
            if res.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                wait = 5 * 2**attempt
                log.warning("Gemini %s, retrying in %ss", res.status_code, wait)
                time.sleep(wait)
                continue
            break
        if res.status_code != 200:
            try:
                msg = res.json()["error"]["message"]
            except Exception:  # noqa: BLE001
                msg = res.text[:200]
            raise AdviceError(f"Gemini API {res.status_code}: {msg}")
        body = res.json()
        cand = (body.get("candidates") or [{}])[0]
        finish = cand.get("finishReason")
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
        usage = body.get("usageMetadata") or {}
        log.info("%s: finishReason=%s chars=%d output_tokens=%s thought_tokens=%s", model, finish, len(text),
                 usage.get("candidatesTokenCount"), usage.get("thoughtsTokenCount", 0))
        if finish != "STOP":
            raise AdviceError(f"answer did not end normally (finishReason={finish}); not stored")
        if len(text) < MIN_CHARS:
            raise AdviceError(f"answer too short ({len(text)} chars); not stored")
        return text
    finally:
        if own:
            client.close()


def advise_job(db: Db, job: dict, key: str, model: str, dry_run: bool = False) -> str:
    rows = db.select("job_summaries", {"job_id": f"eq.{job['id']}", "select": "metrics,group_analysis,insights"})
    if not rows:
        raise AdviceError("job has no summary yet (run the pipeline first)")
    posts = db.select("posts", {"job_id": f"eq.{job['id']}", "source": "eq.real",
                                "select": "source,views,likes,replies,reposts,quotes,char_count,post_type,posted_at"})
    text = generate(build_prompt(job["username"], rows[0], posts), key, model)
    if not dry_run:
        db.update("job_summaries", {"job_id": f"eq.{job['id']}"}, {"llm_advice": text})
    return text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.pipeline.advice", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--job", action="append", metavar="ID", help="job id (repeatable)")
    g.add_argument("--all", action="store_true", help="every finished job with a summary")
    ap.add_argument("--mode", choices=["anonymous", "login"], help="with --all: only jobs of this scraping mode")
    ap.add_argument("--model", help=f"default: $LLM_MODEL or {DEFAULT_MODEL}")
    ap.add_argument("--dry-run", action="store_true", help="print the advice, do not store it")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    config.load_env()
    key = os.environ.get("LLM_API_KEY")
    if not key:
        raise SystemExit("LLM_API_KEY is not set (put it in .env).")
    model = args.model or os.environ.get("LLM_MODEL") or DEFAULT_MODEL

    db = Db()
    flt = {"status": "eq.done", "select": "id,username,mode", "order": "created_at", **({"mode": f"eq.{args.mode}"} if args.mode else {})}
    jobs = db.select("jobs", flt) if args.all else \
        [j for i in args.job if (j := db.get_job(i))]
    if not jobs:
        log.error("no jobs to process")
        return 2
    failed = 0
    for job in jobs:
        try:
            text = advise_job(db, job, key, model, args.dry_run)
            log.info("@%s (%s): %d chars %s", job["username"], job["id"][:8], len(text), "(dry run)" if args.dry_run else "stored")
            if args.dry_run:
                print(text, "\n")
        except AdviceError as e:
            failed += 1
            log.error("@%s (%s): %s", job["username"], job["id"][:8], e)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
