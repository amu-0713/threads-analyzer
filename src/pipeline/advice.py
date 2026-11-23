"""Pre-generate the AI advice (one per goal) and cache it in job_summaries.llm_advice, server-side, no browser.

    python -m src.pipeline.advice --job <job-id> [--job <job-id> ...]
    python -m src.pipeline.advice --all [--mode login]    # every finished job that has a summary
    python -m src.pipeline.advice --all --dry-run         # print the advice, store nothing

Both goals (提高按讚、建立好感 / 帶動討論) are generated for each job. Needs LLM_API_KEY in .env (Gemini API key) plus the usual
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

GOALS = ["提高按讚、建立好感", "帶動討論"]
GOAL_GROUP = {"提高按讚、建立好感": "共鳴型", "帶動討論": "討論型"}
GOAL_TEXT = {
    "提高按讚、建立好感": "提高按讚、建立好感（共鳴型：按讚百分位高）",
    "帶動討論": "帶動討論、收集意見（討論型：回覆百分位高）",
}
# the groups are defined by like / reply percentiles, so each goal is verified with that rate (there is no reach data)
GOAL_METRIC = {"提高按讚、建立好感": "按讚率中位數", "帶動討論": "回覆率中位數"}
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
            "type": "ARRAY", "minItems": 1, "maxItems": 4,
            "items": {"type": "OBJECT", "properties": {"do": {"type": "STRING"}, "why": {"type": "STRING"}, "test": {"type": "STRING"}},
                      "required": ["do", "why", "test"]},
        },
        "avoid": {"type": "STRING"},
    },
    "required": ["goal", "summary", "actions", "avoid"],
}
# inferential wording + causal promises (a reply using any of these is retried once with the reason, never stored)
FORBIDDEN = re.compile(r"顯著|明顯優於|統計上|p\s*值|p\s*=|證明|以提升|為提升|以增加|以提高|有助於|確保|導致|造成")


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


# Bump together with PROMPT_VERSION in src/lib/advice.ts whenever the prompt text changes (a test fails otherwise).
PROMPT_VERSION = 7


def advice_basis(goal: str, summary: dict) -> str:
    """Fingerprint of the stable features behind one goal's advice (mirrors adviceBasis in advice.ts)."""
    wg = ((summary.get("group_analysis") or {}).get("real") or {}).get("writing_guide") or {}
    if not wg.get("available"):
        return ""

    def part(g: str) -> str:
        fs = (wg.get("groups", {}).get(g) or {}).get("stable_features") or []
        return ",".join(f"{g}:{f['key']}:{f['direction']}:{_js(f['group_value'])}:{_js(f['others_value'])}:{f['n_group']}:{f['n_others']}" for f in fs)

    return f"p{PROMPT_VERSION}|{part(GOAL_GROUP[goal])}|{part('低迷型')}"


def _js(x: float) -> str:
    """Number as JavaScript prints it in a template string (1.0 -> '1', 0.345 -> '0.345')."""
    return str(int(x)) if float(x).is_integer() else repr(float(x))


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
        "驗證指標": GOAL_METRIC[goal],
        "建議點數": len(feats),
        "真實貼文數": wg["n_posts"],
        "前後兩半各": wg["halves"],
        "分組篇數": {"共鳴型": counts.get("共鳴型"), "討論型": counts.get("討論型"), "低迷型": counts.get("低迷型")},
        "目標組穩定特徵": [_feature(group, f) for f in feats],
        "目標組代表貼文特徵": rep and {
            "代表貼文數": rep.get("n"),
            "平均字數": None if rep.get("avg_char_count") is None else _half_up(rep["avg_char_count"]),
            "平均按讚率": pct(rep.get("avg_like_rate")),
            "平均回覆率": pct(rep.get("avg_reply_rate")),
            # common keywords are NOT sent: rule 10 forbids citing them, and in tests the model used them anyway (AI_LOG D-14)
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
        f"1. 只能使用資料裡的穩定特徵。actions 剛好 {data['建議點數']} 點：「目標組穩定特徵」每個特徵各寫一點（依資料順序，同一個特徵不可寫兩點）；「低迷型穩定特徵」只能用在 avoid，不可寫進 do。",
        "2. do 是使用者下一篇就能照著寫的做法，只依據該點的那一個特徵，而且只寫方向或大約範圍，不可變成單篇的精確目標：字數寫成「控制在約 N 字左右以內」或「寫到約 N 字左右以上」，N 取自目標組自己的值（可取到十位），不可拿「其他貼文」的值當目標；占比類特徵（提問句、含連結、晚間）只能寫成這一篇「要不要」有提問句、放連結、在晚間發，不可寫「比例調整為 X%」或任何百分比目標。",
        "3. 晚間的定義是 18:00–23:59。建議不在晚間發時寫「18 點以前發」，不可寫「23 點以後」。",
        "4. why 一律照這個格式寫：「{組別} {N} 篇 vs 其他 {M} 篇：{特徵}{組別}較高或較低（{組別的值} vs {其他貼文的值}）」，數字照抄資料中的篇數、方向與兩個值，不可省略或改寫。",
        f"5. test 寫怎麼驗證：連續幾篇照做，和沒照做的貼文比較「{data['驗證指標']}」；只能用這個指標，不可寫觸及人數、觀看數或其他指標。",
        "6. avoid 用一句話說要避開什麼，只依據一個低迷型穩定特徵，同樣只寫方向或「要不要」，句末用括號照規則 4 的格式寫出依據（例如「（低迷型 16 篇 vs 其他 24 篇：提問句占比低迷型較低（0% vs 17%））」）；若「低迷型穩定特徵」是空的，寫「低迷型目前沒有前後期一致的特徵，沒有足夠依據指出要避開的寫法」。",
        "7. 用中立字詞：不可使用「顯著」「明顯優於」「統計上」「p 值」「證明」等推論用語，也不可寫「顯示」「相關」「導致」「造成」「以提升」「為提升」「以增加」「以提高」「有助於」「確保」等因果或關聯說法；不可使用「觸及」這個詞（資料沒有觸及數）。",
        f"8. 依實際篇數描述樣本：真實貼文 {data['真實貼文數']} 篇（依發文時間分成前後各約 {'、'.join(str(x) for x in data['前後兩半各'])} 篇）。特徵方向只代表該組貼文與其他貼文的差別，不代表因果；summary 要提醒仍需實際測試。",
        "9. summary、do、avoid 與 why 一樣，只能引用穩定清單內的特徵；不可提到清單以外的特徵（例如關鍵字、貼文類型、時段、字數等沒有列在穩定清單的項目）；資料沒有圖片或影片資訊，不可提及素材類型；do 不要指定貼文主題或內容題材。「目標組代表貼文特徵」只是背景，不可當成依據或寫進建議。",
        f"10. 輸出 JSON：goal 必須是「{goal}」；summary 一句話（不超過 60 字，這個帳號要達成這個目標，下一篇該怎麼寫）；actions 剛好 {data['建議點數']} 點，每點有 do、why、test（do、test 各不超過 60 字）；avoid 一句話。",
        "",
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
    ])


# ------------------------------------------------------------------------------------------------ validation + cache
SHARE_TARGET = re.compile(r"\d+(?:\.\d+)?\s*[%％]")
LENGTH = re.compile(r"(約|大約)?\s*(\d+)\s*字(左右|以內|以下|以上|上下|內)?")
LATE_NIGHT = re.compile(r"23\s*點\s*(?:以後|後)|午夜|凌晨")


def _content_problem(obj: dict, goal: str, n_actions: int | None = None) -> str | None:
    """Semantic rules that can be checked without a model (mirrors contentProblem in advice.ts). First problem or None."""
    n = len(obj["actions"])
    if (n != n_actions) if n_actions else not 1 <= n <= 4:
        return f"actions 必須剛好 {n_actions} 點（目標組每個穩定特徵一點）" if n_actions else "actions 必須是 1–4 點"
    blob = " ".join([obj["summary"], obj["avoid"], *[a[k] for a in obj["actions"] for k in ("do", "why", "test")]])
    if FORBIDDEN.search(blob):
        return "內容含有推論用語"
    if "觸及" in blob:
        return "不可使用「觸及」（沒有觸及資料，請用按讚率或回覆率）"
    metric = GOAL_METRIC[goal][:3]  # 按讚率 / 回覆率
    other = "回覆率" if metric == "按讚率" else "按讚率"
    for t in [obj["summary"], *[a["do"] for a in obj["actions"]]]:
        if SHARE_TARGET.search(t):
            return "summary／do 不可寫百分比目標；占比類特徵只能寫這篇要不要有提問句、放連結、在晚間發"
        if any(not m.group(1) and not m.group(3) for m in LENGTH.finditer(t)):
            return "字數只能寫成大約範圍（例如「控制在約 30 字左右以內」），不可寫成單篇的精確字數"
        if LATE_NIGHT.search(t):
            return "晚間是 18:00–23:59；不在晚間發請寫「18 點以前」"
    for a in obj["actions"]:
        if "低迷型" in a["do"]:
            return "do 只能依據目標組的穩定特徵；低迷型只能用在 avoid"
        if metric not in a["test"] or other in a["test"]:
            return f"test 必須比較{GOAL_METRIC[goal]}"
    return None


def parse_advice(text: str, goal: str, n_actions: int | None = None) -> dict:
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
    if not isinstance(acts, list) or not 1 <= len(acts) <= 4:
        raise AdviceError("actions 必須是 1–4 點")
    for a in acts:
        if not (isinstance(a, dict) and s(a.get("do")) and s(a.get("why")) and s(a.get("test"))):
            raise AdviceError("某一點缺少 do／why／test")
    if not s(obj.get("avoid")):
        raise AdviceError("缺少 avoid")
    out = {"goal": goal, "summary": obj["summary"].strip(),
           "actions": [{"do": a["do"].strip(), "why": a["why"].strip(), "test": a["test"].strip()} for a in acts],
           "avoid": obj["avoid"].strip()}
    problem = _content_problem(out, goal, n_actions)
    if problem:
        raise AdviceError(problem)
    return out


def action_count(goal: str, summary: dict) -> int:
    """How many actions the advice for a goal must have: one per stable feature of the goal's group."""
    wg = ((summary.get("group_analysis") or {}).get("real") or {}).get("writing_guide") or {}
    return len((wg.get("groups", {}).get(GOAL_GROUP[goal]) or {}).get("stable_features") or [])


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
        if res.status_code == 429 and "per day" in res.text.lower():  # a per-day quota does not recover within seconds
            raise AdviceError("今日額度已用完，請改用快速模型" if model == DEFAULT_MODEL else "今日額度已用完，請明天再試")
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


def generate(prompt: str, key: str, model: str, goal: str, client: httpx.Client | None = None, n_actions: int | None = None) -> dict:
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
                return parse_advice(text, goal, n_actions)
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
            advice = generate(build_prompt(job["username"], goal, summary), key, model, goal, n_actions=action_count(goal, summary))
        except AdviceError as e:
            results[goal] = f"skipped: {e}"
            continue
        entry = {"goal": goal, "model": model, "generated_at": datetime.now(timezone.utc).isoformat(),
                 "n_posts": summary["group_analysis"]["real"]["writing_guide"]["n_posts"], "basis": advice_basis(goal, summary), "advice": advice}
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
