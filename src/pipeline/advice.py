"""Pre-generate the AI advice (one per goal) and cache it in job_summaries.llm_advice, server-side, no browser.

    python -m src.pipeline.advice --job <job-id> [--job <job-id> ...]
    python -m src.pipeline.advice --all [--mode login]    # every finished job that has a summary
    python -m src.pipeline.advice --all --dry-run         # print the advice, store nothing

Both goals (擴大觸及 / 帶動討論) are generated for each job. Needs LLM_API_KEY in .env (Gemini API key) plus the usual
SUPABASE_* values, and the job's analysis must already contain the writing guide (re-run `run --analyze-only` once).

This file mirrors src/lib/advice.ts + src/lib/llm.ts (the dashboard's goal / model switch): same whitelist of models,
same prompt input (stable features only, medians/percentages), same JSON schema and validation, same cache format.
Keep the two in sync. Nothing is stored unless the answer is valid JSON with every field.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sys
import time
from datetime import datetime, timezone

import httpx

from . import config
from .db import Db

log = logging.getLogger("pipeline.advice")

GOALS = ["擴大觸及", "帶動討論"]
GOAL_GROUP = {"擴大觸及": "共鳴型", "帶動討論": "討論型"}
GOAL_TEXT = {
    "擴大觸及": "擴大觸及、建立好感（共鳴型：按讚百分位高）",
    "帶動討論": "帶動討論、收集意見（討論型：回覆百分位高）",
}
# Only these can be chosen (UI: dropdown; CLI: --model). Default = first.
MODELS = ["gemini-3.8-flash", "gemini-3.1-flash-lite"]
DEFAULT_MODEL = MODELS[0]
THINKING = {"gemini-3.8-flash": {"thinkingLevel": "low"}, "gemini-3.1-flash-lite": {"thinkingLevel": "minimal"}}  # 3.8-flash rejects "minimal" (HTTP 400)
API = "https://generativelanguage.googleapis.com/v1beta/models"

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "goal": {"type": "STRING", "enum": GOALS},
        "summary": {"type": "STRING"},
        "actions": {
            "type": "ARRAY", "minItems": 2, "maxItems": 4,
            "items": {"type": "OBJECT", "properties": {"do": {"type": "STRING"}, "why": {"type": "STRING"}, "test": {"type": "STRING"}},
                      "required": ["do", "why", "test"]},
        },
        "avoid": {"type": "STRING"},
    },
    "required": ["goal", "summary", "actions", "avoid"],
}
FORBIDDEN = re.compile(r"顯著|明顯優於|統計上|p\s*值|p\s*=|證明")


class AdviceError(RuntimeError):
    pass


# ------------------------------------------------------------------------------------------------ prompt input
def _half_up(x: float) -> int:  # JS Math.round semantics (Python's round() is half-to-even)
    return math.floor(x + 0.5)


def _fmt(f: dict, v: float) -> str:
    return f"{_half_up(v * 100)}%" if f["is_share"] else f"{_half_up(v)} 字"


def _feature(group: str, f: dict) -> dict:
    return {
        "特徵": f["label"],
        "方向": f"{group}較高" if f["direction"] == "higher" else f"{group}較低",
        group: _fmt(f, f["group_value"]),
        "其他貼文": _fmt(f, f["others_value"]),
        "篇數": f"{group} {f['n_group']} 篇、其他 {f['n_others']} 篇",
    }


def stable_counts(summary: dict) -> dict | None:
    wg = ((summary.get("group_analysis") or {}).get("real") or {}).get("writing_guide") or {}
    if not wg.get("available"):
        return None
    return {g: len((wg.get("groups", {}).get(g) or {}).get("stable_features") or []) for g in ("共鳴型", "討論型", "低迷型")}


def advice_input(username: str, goal: str, summary: dict) -> dict:
    ga = (summary.get("group_analysis") or {}).get("real") or {}
    wg = ga.get("writing_guide") or {}
    if not wg.get("available"):
        raise AdviceError("樣本太少，無法列出寫作清單")
    group = GOAL_GROUP[goal]
    feats = (wg.get("groups", {}).get(group) or {}).get("stable_features") or []
    if not feats:
        raise AdviceError(f"{goal}（{group}）目前沒有前後期一致的寫法，暫不產生建議")
    low = (wg.get("groups", {}).get("低迷型") or {}).get("stable_features") or []
    rep = (ga.get("groups", {}).get(group) or {}).get("profile_of_representatives")
    pct = lambda x: None if x is None else f"{x * 100:.2f}%"  # noqa: E731
    share = lambda x: None if x is None else f"{_half_up(x * 100)}%"  # noqa: E731
    counts = ga.get("counts") or {}
    out = {
        "帳號": f"@{username}",
        "目標": goal,
        "目標說明": GOAL_TEXT[goal],
        "真實貼文數": wg["n_posts"],
        "前後兩半各": wg["halves"],
        "分組篇數": {"共鳴型": counts.get("共鳴型"), "討論型": counts.get("討論型"), "低迷型": counts.get("低迷型")},
        "目標組穩定特徵": [_feature(group, f) for f in feats],
        "目標組代表貼文特徵": rep and {
            "代表貼文數": rep.get("n"),
            "平均字數": None if rep.get("avg_char_count") is None else _half_up(rep["avg_char_count"]),
            "平均按讚率": pct(rep.get("avg_like_rate")),
            "平均回覆率": pct(rep.get("avg_reply_rate")),
            "常見關鍵字": [k["word"] for k in (rep.get("keywords") or [])[:5]],
            "提問句占比": share(rep.get("question_share")),
            "含連結占比": share(rep.get("link_share")),
        },
        "低迷型穩定特徵": [_feature("低迷型", f) for f in low],
    }
    return out


def build_prompt(username: str, goal: str, summary: dict) -> str:
    data = advice_input(username, goal, summary)
    return "\n".join([
        "你是社群行銷顧問。以下是某個 Threads 帳號「僅真實貼文」的分析摘要（JSON）。",
        f"任務：針對目標「{goal}」，告訴使用者「下一篇貼文」可以怎麼寫。",
        "規則：",
        "1. 只能使用資料裡列出的穩定特徵。每點 actions 的 why 必須寫出：哪一組、哪個特徵、方向、篇數；特徵必須出現在「目標組穩定特徵」或「低迷型穩定特徵」，數字（百分比、字數、篇數）必須與資料一致。",
        "2. do 是使用者明天就能照著發文的具體寫法（例如：首篇控制在 120 字內，結尾用一個問句邀請回覆），不能只是統計事實；每一點 do 只依據一個特徵。",
        "3. test 說明怎麼驗證（例如：連續 4 篇 A/B 對照，比較回覆率中位數），要寫出比較的指標與篇數。",
        "4. avoid 用一句話說要避開什麼，依據低迷型穩定特徵；若「低迷型穩定特徵」是空的，寫「低迷型目前沒有前後期一致的特徵，沒有足夠依據指出要避開的寫法」。",
        "5. 用中立字詞描述；不可使用「顯著」「明顯優於」「統計上」「p 值」「證明」等推論用語；比率一律用百分比（例如 3.59%）；中位數優先。",
        f"6. 依實際篇數描述樣本：真實貼文 {data['真實貼文數']} 篇（依發文時間分成前後各約 {'、'.join(str(x) for x in data['前後兩半各'])} 篇）。特徵方向只代表該組貼文與其他貼文的差別，不代表因果；summary 或 why 要提醒仍需實際測試。",
        f"7. 輸出 JSON：goal 必須是「{goal}」；summary 一句話（這個帳號要達成這個目標，下一篇該怎麼寫）；actions 2–4 點，每點有 do、why、test；avoid 一句話。",
        "",
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
    ])


# ------------------------------------------------------------------------------------------------ validation + cache
def parse_advice(text: str, goal: str) -> dict:
    try:
        obj = json.loads(text)
    except ValueError:
        raise AdviceError("回應不是合法的 JSON") from None
    s = lambda v: isinstance(v, str) and v.strip() != ""  # noqa: E731
    if not isinstance(obj, dict) or obj.get("goal") != goal:
        raise AdviceError(f"goal 欄位不是「{goal}」")
    if not s(obj.get("summary")):
        raise AdviceError("缺少 summary")
    acts = obj.get("actions")
    if not isinstance(acts, list) or not 2 <= len(acts) <= 4:
        raise AdviceError("actions 必須是 2–4 點")
    for a in acts:
        if not (isinstance(a, dict) and s(a.get("do")) and s(a.get("why")) and s(a.get("test"))):
            raise AdviceError("某一點缺少 do／why／test")
    if not s(obj.get("avoid")):
        raise AdviceError("缺少 avoid")
    blob = " ".join([obj["summary"], obj["avoid"], *[a[k] for a in acts for k in ("do", "why", "test")]])
    if FORBIDDEN.search(blob):
        raise AdviceError("內容含有推論用語")
    return {"goal": goal, "summary": obj["summary"].strip(),
            "actions": [{"do": a["do"].strip(), "why": a["why"].strip(), "test": a["test"].strip()} for a in acts],
            "avoid": obj["avoid"].strip()}


def entry_key(goal: str, model: str) -> str:
    return f"{goal}|{model}"


def parse_store(raw: str | None) -> dict:
    """Old rows hold plain text; new rows hold {"version": 2, ...}. Both must keep working."""
    if not raw:
        return {"version": 2, "legacy_text": None, "entries": {}}
    try:
        o = json.loads(raw)
        if isinstance(o, dict) and o.get("version") == 2 and isinstance(o.get("entries"), dict):
            return {"version": 2, "legacy_text": o.get("legacy_text"), "entries": o["entries"]}
    except ValueError:
        pass
    return {"version": 2, "legacy_text": raw, "entries": {}}


def with_entry(raw: str | None, entry: dict) -> str:
    store = parse_store(raw)
    store["entries"][entry_key(entry["goal"], entry["model"])] = entry
    return json.dumps(store, ensure_ascii=False, separators=(",", ":"))


# ------------------------------------------------------------------------------------------------ Gemini call
VARIANTS = [(True, True), (False, True), (False, False)]  # (thinking, schema): tried in order on HTTP 400


def _request(client: httpx.Client, model: str, key: str, prompt: str, thinking: bool, schema: bool) -> httpx.Response:
    cfg: dict = {"temperature": 0.4, "maxOutputTokens": 4096, "responseMimeType": "application/json"}
    if schema:
        cfg["responseSchema"] = RESPONSE_SCHEMA
    if thinking:
        cfg["thinkingConfig"] = THINKING[model]
    return client.post(f"{API}/{model}:generateContent", headers={"x-goog-api-key": key},
                       json={"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": cfg})


def _request_text(client: httpx.Client, model: str, key: str, prompt: str, retries: int = 2) -> str:
    started = time.monotonic()
    vi = 0
    res = _request(client, model, key, prompt, *VARIANTS[vi])
    while res.status_code == 400 and vi < len(VARIANTS) - 1:
        log.info("%s rejected variant %d (400): %s", model, vi, res.text[:200])
        vi += 1
        res = _request(client, model, key, prompt, *VARIANTS[vi])
    for attempt in range(retries):
        if res.status_code not in (429, 500, 502, 503, 504):
            break
        wait = 3 * 2**attempt
        log.warning("%s HTTP %s, retrying in %ss", model, res.status_code, wait)
        time.sleep(wait)
        res = _request(client, model, key, prompt, *VARIANTS[vi])
    if res.status_code != 200:
        try:
            msg = res.json()["error"]["message"]
        except Exception:  # noqa: BLE001
            msg = res.text[:200]
        raise AdviceError(f"Gemini API {res.status_code}: {str(msg)[:200]}")
    body = res.json()
    cand = (body.get("candidates") or [{}])[0]
    finish = cand.get("finishReason")
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    usage = body.get("usageMetadata") or {}
    log.info("%s variant=%d: %.1fs finishReason=%s chars=%d output_tokens=%s thought_tokens=%s", model, vi, time.monotonic() - started,
             finish, len(text), usage.get("candidatesTokenCount"), usage.get("thoughtsTokenCount", 0))
    if not text.strip():
        raise AdviceError(f"Gemini returned no text (finishReason={finish})")
    if finish and finish != "STOP":
        raise AdviceError(f"answer did not end normally (finishReason={finish}); not stored")
    return text


def generate(prompt: str, key: str, model: str, goal: str, client: httpx.Client | None = None) -> dict:
    """Valid advice or an AdviceError. An invalid reply (bad JSON, missing field, inferential wording) is retried once."""
    if model not in MODELS:
        raise AdviceError(f"model {model!r} is not on the whitelist {MODELS}")
    own = client is None
    client = client or httpx.Client(timeout=40)
    try:
        last = ""
        for attempt in range(2):
            text = _request_text(client, model, key, prompt if attempt == 0 else f"{prompt}\n\n（上一次的回應不合格：{last}。請修正後重新輸出。）")
            try:
                return parse_advice(text, goal)
            except AdviceError as e:
                last = str(e)
                log.warning("invalid answer (attempt %d): %s", attempt + 1, last)
        raise AdviceError(f"AI 回應格式不合格（已重試一次）：{last}")
    finally:
        if own:
            client.close()


# ------------------------------------------------------------------------------------------------ CLI
def advise_job(db: Db, job: dict, key: str, model: str, goals: list[str], dry_run: bool = False) -> dict[str, dict | str]:
    rows = db.select("job_summaries", {"job_id": f"eq.{job['id']}", "select": "group_analysis,llm_advice"})
    if not rows:
        raise AdviceError("job has no summary yet (run the pipeline first)")
    summary = rows[0]
    if not stable_counts(summary):
        raise AdviceError("no writing guide in this job's analysis (too few real posts, or run `run --analyze-only` first)")
    results: dict[str, dict | str] = {}
    raw = summary.get("llm_advice")
    for goal in goals:
        try:
            advice = generate(build_prompt(job["username"], goal, summary), key, model, goal)
        except AdviceError as e:
            results[goal] = f"skipped: {e}"
            continue
        entry = {"goal": goal, "model": model, "generated_at": datetime.now(timezone.utc).isoformat(),
                 "n_posts": summary["group_analysis"]["real"]["writing_guide"]["n_posts"], "advice": advice}
        raw = with_entry(raw, entry)
        results[goal] = entry
    if not dry_run and any(isinstance(v, dict) for v in results.values()):
        db.update("job_summaries", {"job_id": f"eq.{job['id']}"}, {"llm_advice": raw})
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.pipeline.advice", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--job", action="append", metavar="ID", help="job id (repeatable)")
    g.add_argument("--all", action="store_true", help="every finished job with a summary")
    ap.add_argument("--mode", choices=["anonymous", "login"], help="with --all: only jobs of this scraping mode")
    ap.add_argument("--goal", choices=["both", *GOALS], default="both", help="default: both goals")
    ap.add_argument("--model", choices=MODELS, help=f"default: {DEFAULT_MODEL}")
    ap.add_argument("--dry-run", action="store_true", help="print the advice, do not store it")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    config.load_env()
    key = os.environ.get("LLM_API_KEY")
    if not key:
        raise SystemExit("LLM_API_KEY is not set (put it in .env).")
    model = args.model or DEFAULT_MODEL
    goals = GOALS if args.goal == "both" else [args.goal]

    db = Db()
    flt = {"status": "eq.done", "select": "id,username,mode", "order": "created_at", **({"mode": f"eq.{args.mode}"} if args.mode else {})}
    jobs = db.select("jobs", flt) if args.all else [j for i in args.job if (j := db.get_job(i))]
    if not jobs:
        log.error("no jobs to process")
        return 2
    failed = 0
    for job in jobs:
        try:
            res = advise_job(db, job, key, model, goals, args.dry_run)
        except AdviceError as e:
            failed += 1
            log.error("@%s (%s): %s", job["username"], job["id"][:8], e)
            continue
        for goal, r in res.items():
            if isinstance(r, dict):
                log.info("@%s (%s) %s: stored%s", job["username"], job["id"][:8], goal, " (dry run)" if args.dry_run else "")
                if args.dry_run:
                    print(json.dumps(r["advice"], ensure_ascii=False, indent=2))
            else:
                log.warning("@%s (%s) %s: %s", job["username"], job["id"][:8], goal, r)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
