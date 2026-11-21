"""Pre-generate the AI advice for jobs and store it in job_summaries.llm_advice (server-side, no browser).

    python -m src.pipeline.advice --job <job-id> [--job <job-id> ...]
    python -m src.pipeline.advice --all            # every finished job that has a summary
    python -m src.pipeline.advice --all --dry-run  # print the advice, store nothing

Needs LLM_API_KEY in .env (Gemini API key; LLM_MODEL optionally overrides the model) plus the usual
SUPABASE_* values. The prompt mirrors buildPrompt() in src/lib/llm.ts (the dashboard's "regenerate" button):
real-only statistics, aggregates only, no raw post text. Nothing is stored unless the answer ends normally.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time

import httpx

from . import config
from .db import Db

log = logging.getLogger("pipeline.advice")

# Fastest lightweight text model measured through the API's own model list (2026-11-21); override with LLM_MODEL.
DEFAULT_MODEL = "gemini-3.1-flash-lite"
API = "https://generativelanguage.googleapis.com/v1beta/models"
MIN_CHARS = 150  # a real answer to this prompt is ~400+ characters; anything far shorter is treated as broken


class AdviceError(RuntimeError):
    pass


def build_prompt(username: str, summary: dict) -> str:
    m = (summary.get("metrics") or {}).get("real") or {}
    g = (summary.get("group_analysis") or {}).get("real") or {}
    data = {
        "account": f"@{username}",
        "real_posts": m.get("n_real"),
        "averages": m.get("avg"),
        "avg_interaction_rate": m.get("avg_interaction_rate"),
        "avg_like_rate": m.get("avg_like_rate"),
        "avg_reply_rate": m.get("avg_reply_rate"),
        "post_types": m.get("post_types"),
        "length_vs_interaction": m.get("length_vs_interaction"),
        "top_keywords": (m.get("keywords") or [])[:8],
        "group_counts": g.get("counts"),
        "group_profiles": {k: {"n_members": v.get("n_members"), "profile": v.get("profile_of_representatives")}
                           for k, v in (g.get("groups") or {}).items()},
        "hypothesis_checks": [i.get("text") for i in ((summary.get("insights") or {}).get("real") or [])],
    }
    return "\n".join([
        "你是社群媒體數據分析顧問。以下是某個 Threads 帳號「僅真實貼文」的統計摘要（JSON）。",
        "請用繁體中文，依據資料給 3–5 點具體、可執行的內容策略建議。",
        "規則：只能引用資料中有的數字與現象；樣本很少（真實貼文只有個位數）時，必須明講結論僅供參考、不可過度推論；",
        "不要編造資料中沒有的事實；不要提到你看不到的貼文內容；每點建議一句話說明依據。",
        "直接列出建議，不要自我介紹或寒暄。",
        "樣本只有個位數，不可使用「顯著」「明顯優於」等統計推論用語；平均值可能被單一貼文的極端值拉高時要提醒。",
        "",
        json.dumps(data, ensure_ascii=False),
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
    text = generate(build_prompt(job["username"], rows[0]), key, model)
    if not dry_run:
        db.update("job_summaries", {"job_id": f"eq.{job['id']}"}, {"llm_advice": text})
    return text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.pipeline.advice", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--job", action="append", metavar="ID", help="job id (repeatable)")
    g.add_argument("--all", action="store_true", help="every finished job with a summary")
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
    jobs = db.select("jobs", {"status": "eq.done", "select": "id,username", "order": "created_at"}) if args.all else \
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
