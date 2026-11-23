"""AI advice: prompt input, validation, cache format, model whitelist, fallbacks (HTTP mocked; no real Gemini)."""

from __future__ import annotations

import json

import httpx
import pytest

from src.pipeline import advice as A

GOOD = {
    "goal": "擴大觸及",
    "summary": "下一篇請用較短的貼文。",
    "actions": [
        {"do": "把貼文控制在 30 字內", "why": "共鳴型字數中位數 26 字，低於其他貼文的 137 字（共鳴型 13 篇、其他 27 篇）", "test": "連續 4 篇 A/B，比較按讚率中位數"},
        {"do": "文中不放連結", "why": "共鳴型含連結占比 0%，低於其他貼文的 26%（13 篇 vs 27 篇）", "test": "同主題有／無連結各 4 篇，比較互動率中位數"},
    ],
    "avoid": "避開長篇活動公告。",
}


def _feat(key, label, direction, g, o, ng, no, share=True):
    return {"key": key, "label": label, "is_share": share, "direction": direction, "group_value": g, "others_value": o, "n_group": ng, "n_others": no, "halves": []}


def _summary(resonance=None, discussion=None, low=None, available=True):
    wg = {"available": available, "n_posts": 40, "halves": [20, 20], "goals": {},
          "groups": {"共鳴型": {"stable_features": resonance or []}, "討論型": {"stable_features": discussion or []}, "低迷型": {"stable_features": low or []}}}
    rep = {"n": 5, "avg_char_count": 41.6, "avg_like_rate": 0.0123, "avg_reply_rate": 0.0004, "keywords": [{"word": "活動"}], "question_share": 0.2, "link_share": 0.0}
    return {"group_analysis": {"real": {"counts": {"共鳴型": 13, "討論型": 11, "低迷型": 16}, "writing_guide": wg,
                                        "groups": {"共鳴型": {"profile_of_representatives": rep}, "討論型": {"profile_of_representatives": rep}}}}}


def _client(*responses):
    """A client that answers the given (status, body) pairs in order and records the request bodies."""
    calls, it = [], iter(responses)

    def handler(request):
        calls.append(json.loads(request.content))
        status, body = next(it)
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def _ok(obj):
    return 200, {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "想想", "thought": True}, {"text": json.dumps(obj, ensure_ascii=False)}]}}]}


def test_prompt_uses_only_stable_features_and_percentages():
    s = _summary(resonance=[_feat("char_median", "字數（中位數）", "lower", 26, 137, 13, 27, share=False), _feat("link_share", "含連結占比", "lower", 0.0, 0.26, 13, 27)],
                 low=[_feat("question_share", "提問句占比", "lower", 0.0, 0.17, 16, 24)])
    p = A.build_prompt("acct", "擴大觸及", s)
    data = json.loads(p.rsplit("\n", 1)[1])
    assert data["目標"] == "擴大觸及" and data["真實貼文數"] == 40 and data["前後兩半各"] == [20, 20]
    assert [f["特徵"] for f in data["目標組穩定特徵"]] == ["字數（中位數）", "含連結占比"]
    assert data["目標組穩定特徵"][0]["共鳴型"] == "26 字" and data["目標組穩定特徵"][1]["其他貼文"] == "26%"
    assert data["低迷型穩定特徵"][0]["篇數"] == "低迷型 16 篇、其他 24 篇"
    assert "個位數" not in p  # the old "only a handful of posts" wording is gone
    assert data["分組篇數"] == {"共鳴型": 13, "討論型": 11, "低迷型": 16}
    assert "真實貼文 40 篇（依發文時間分成前後各約 20、20 篇）" in p  # sample described by the real count


def test_no_stable_feature_or_no_guide_means_no_advice():
    with pytest.raises(A.AdviceError, match="沒有前後期一致"):
        A.build_prompt("a", "帶動討論", _summary(resonance=[_feat("char_median", "字數", "lower", 1, 2, 3, 4, False)]))
    with pytest.raises(A.AdviceError, match="樣本太少"):
        A.build_prompt("a", "擴大觸及", _summary(available=False))
    assert A.stable_counts(_summary(available=False)) is None
    assert A.stable_counts(_summary(resonance=[_feat("x", "x", "higher", 1, 0, 3, 3)])) == {"共鳴型": 1, "討論型": 0, "低迷型": 0}


@pytest.mark.parametrize("mutate,msg", [
    (lambda o: o.update(goal="帶動討論"), "goal"),
    (lambda o: o.update(summary=" "), "summary"),
    (lambda o: o.update(actions=o["actions"][:1]), "actions"),
    (lambda o: o["actions"][0].pop("test"), "do／why／test"),
    (lambda o: o.update(avoid=""), "avoid"),
    (lambda o: o["actions"][0].update(why="差異顯著（p 值 0.01）"), "推論用語"),
])
def test_validation_rejects_bad_answers(mutate, msg):
    obj = json.loads(json.dumps(GOOD))
    mutate(obj)
    with pytest.raises(A.AdviceError, match=msg):
        A.parse_advice(json.dumps(obj, ensure_ascii=False), "擴大觸及")
    assert A.parse_advice(json.dumps(GOOD, ensure_ascii=False), "擴大觸及")["actions"][0]["do"] == "把貼文控制在 30 字內"
    with pytest.raises(A.AdviceError, match="JSON"):
        A.parse_advice("不是 json", "擴大觸及")


def test_invalid_answer_is_retried_once_then_succeeds():
    bad = dict(GOOD, actions=GOOD["actions"][:1])
    client, calls = _client(_ok(bad), _ok(GOOD))
    out = A.generate("p", "k", "gemini-3.1-flash-lite", "擴大觸及", client)
    assert out["summary"] == GOOD["summary"] and len(calls) == 2
    assert "上一次的回應不合格" in calls[1]["contents"][0]["parts"][0]["text"]  # the retry says what was wrong
    assert calls[0]["generationConfig"]["responseMimeType"] == "application/json" and "responseSchema" in calls[0]["generationConfig"]


def test_still_invalid_after_the_retry_raises_and_nothing_is_returned():
    bad = dict(GOOD, actions=[])
    client, calls = _client(_ok(bad), _ok(bad))
    with pytest.raises(A.AdviceError, match="已重試一次"):
        A.generate("p", "k", "gemini-3.1-flash-lite", "擴大觸及", client)
    assert len(calls) == 2


def test_400_drops_thinking_then_schema():
    client, calls = _client((400, {"error": {"message": "thinkingConfig not supported"}}), (400, {"error": {"message": "schema"}}), _ok(GOOD))
    assert A.generate("p", "k", "gemini-3.8-flash", "擴大觸及", client)["goal"] == "擴大觸及"
    cfgs = [c["generationConfig"] for c in calls]
    assert "thinkingConfig" in cfgs[0] and "thinkingConfig" not in cfgs[1] and "responseSchema" in cfgs[1] and "responseSchema" not in cfgs[2]


def test_daily_quota_429_is_not_retried():
    quota = (429, {"error": {"message": "Quota exceeded ... Generate content requests per day limit exceeded on Free Tier."}})
    client, calls = _client(quota, _ok(GOOD))
    with pytest.raises(A.AdviceError, match="今日額度已用完，請改用快速模型"):
        A.generate("p", "k", "gemini-3.8-flash", "擴大觸及", client)
    assert len(calls) == 1  # no waiting, no second request


def test_model_must_be_on_the_whitelist():
    assert A.MODELS == ["gemini-3.8-flash", "gemini-3.1-flash-lite"] and A.DEFAULT_MODEL == "gemini-3.8-flash"
    with pytest.raises(A.AdviceError, match="whitelist"):
        A.generate("p", "k", "gemini-2.5-pro", "擴大觸及", _client()[0])


def test_cache_keeps_legacy_text_and_one_entry_per_goal_and_model():
    assert A.parse_store(None) == {"version": 2, "legacy_text": None, "entries": {}}
    legacy = "1. 舊版純文字建議。"
    assert A.parse_store(legacy) == {"version": 2, "legacy_text": legacy, "entries": {}}
    e1 = {"goal": "擴大觸及", "model": "gemini-3.1-flash-lite", "generated_at": "t", "n_posts": 40, "advice": GOOD}
    raw = A.with_entry(legacy, e1)  # first new entry on an old row keeps the old text
    s = A.parse_store(raw)
    assert s["legacy_text"] == legacy and list(s["entries"]) == ["擴大觸及|gemini-3.1-flash-lite"]
    e2 = dict(e1, model="gemini-3.8-flash")
    e3 = dict(e1, goal="帶動討論", advice=dict(GOOD, goal="帶動討論"))
    raw = A.with_entry(A.with_entry(raw, e2), e3)
    assert set(A.parse_store(raw)["entries"]) == {"擴大觸及|gemini-3.1-flash-lite", "擴大觸及|gemini-3.8-flash", "帶動討論|gemini-3.1-flash-lite"}
    assert A.parse_store(raw)["entries"]["擴大觸及|gemini-3.8-flash"]["model"] == "gemini-3.8-flash"
    e1b = dict(e1, generated_at="later")  # regenerating the same goal + model replaces its entry
    assert A.parse_store(A.with_entry(raw, e1b))["entries"]["擴大觸及|gemini-3.1-flash-lite"]["generated_at"] == "later"


def test_advise_job_generates_both_goals_and_skips_a_goal_without_stable_features(monkeypatch):
    class Db:
        updates: list = []

        def select(self, table, params=None):
            return [dict(_summary(resonance=[_feat("char_median", "字數（中位數）", "lower", 26, 137, 13, 27, False)]), llm_advice="舊版文字")]

        def update(self, table, filters, values):
            Db.updates.append(values)

    monkeypatch.setattr(A, "generate", lambda prompt, key, model, goal, client=None: dict(GOOD, goal=goal))
    res = A.advise_job(Db(), {"id": "j1", "username": "acct"}, "k", A.DEFAULT_MODEL, A.GOALS)
    assert isinstance(res["擴大觸及"], dict) and res["帶動討論"].startswith("skipped: 帶動討論")
    store = A.parse_store(Db.updates[-1]["llm_advice"])
    assert list(store["entries"]) == [f"擴大觸及|{A.DEFAULT_MODEL}"] and store["legacy_text"] == "舊版文字"


def test_entry_stores_the_basis_and_it_changes_with_the_stable_features():
    f1 = _feat("char_median", "字數（中位數）", "lower", 26, 137, 13, 27, False)
    s1 = _summary(resonance=[f1], low=[_feat("question_share", "提問句占比", "lower", 0.345, 1.0, 16, 24)])
    b1 = A.advice_basis("擴大觸及", s1)
    assert b1 == f"p{A.PROMPT_VERSION}|共鳴型:char_median:lower:26:137:13:27|低迷型:question_share:lower:0.345:1:16:24"  # numbers printed as JavaScript does
    assert A.advice_basis("擴大觸及", _summary(resonance=[f1])) != b1  # 低迷型 features are part of the basis
    assert A.advice_basis("擴大觸及", _summary(available=False)) == ""
    # an advice written under one guide no longer matches after the guide changes: the UI hides it
    assert A.advice_basis("擴大觸及", _summary(resonance=[dict(f1, group_value=30)], low=[_feat("question_share", "提問句占比", "lower", 0.345, 1.0, 16, 24)])) != b1


def test_prompt_change_requires_a_version_bump():
    """The prompt text is part of what advice was written with. If this fails you changed the prompt: bump PROMPT_VERSION in
    src/pipeline/advice.py AND src/lib/advice.ts (old advice is then hidden until regenerated), then update the two constants below."""
    import hashlib

    prompt = A.build_prompt("acct", "擴大觸及", _summary(resonance=[_feat("char_median", "字數（中位數）", "lower", 26, 137, 13, 27, False)]))
    assert (A.PROMPT_VERSION, hashlib.sha1(prompt.encode()).hexdigest()[:12]) == (3, "2f09ca7cf7ca")
