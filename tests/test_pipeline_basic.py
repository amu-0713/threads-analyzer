from src.pipeline.features import text_features
from src.pipeline.scraper import parse_views


def test_parse_views():
    assert parse_views("1,479 次瀏覽") == (1479, False)
    assert parse_views("1.5\xa0萬次瀏覽") == (15000, True)
    assert parse_views("1 萬次瀏覽") == (10000, True)
    assert parse_views("nothing here") == (None, False)


def test_text_features():
    f = text_features("看這裡 https://7-11.tw/a?x=1 #優惠 @7eleventw")
    assert (f["url_count"], f["hashtag_count"], f["mention_count"]) == (1, 1, 1)
    assert f["post_type"] == "含連結"  # link > hashtag > mention > plain
    assert text_features("純文字")["post_type"] == "純文字"
    assert text_features("a@b.com 12/5 14:30")["mention_count"] == 0


def _real_rows():
    from datetime import datetime, timedelta, timezone
    base = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
    rows = []
    for i in range(8):
        v = 1000 * (i + 2)
        rows.append({"views": v, "likes": v // 50, "replies": v // 400, "reposts": v // 500, "quotes": v // 2000,
                     "char_count": 40 + 10 * i, "posted_at": (base - timedelta(days=i)).isoformat()})
    return rows


def test_mock_fills_to_target_and_is_deterministic():
    from src.pipeline.mock import generate_mock
    a = generate_mock("job-1", "someone", _real_rows(), 30)
    assert len(a) == 22 and {r["source"] for r in a} == {"mock"}
    assert a == generate_mock("job-1", "someone", _real_rows(), 30)
    assert len({r["post_url"] for r in a}) == 22
    assert generate_mock("job-1", "someone", _real_rows() * 4, 30) == []  # already >= 30


def test_mock_plants_the_three_patterns():
    from src.pipeline.mock import generate_mock
    rows = generate_mock("job-2", "someone", _real_rows(), 400)  # big sample so the effects are unmistakable
    def rate(rs, k): return sum(r[k] / r["views"] for r in rs) / len(rs)
    q = [r for r in rows if r["text"].rstrip().endswith("？") or "？" in r["text"]]
    nq = [r for r in rows if r not in q]
    assert rate(q, "replies") > 1.8 * rate(nq, "replies")
    from datetime import datetime
    ev = [r for r in rows if datetime.fromisoformat(r["posted_at"]).hour >= 18]
    nev = [r for r in rows if r not in ev]
    assert rate(ev, "likes") > 1.5 * rate(nev, "likes")
    ln = [r for r in rows if r["url_count"]]
    nln = [r for r in rows if not r["url_count"]]
    assert rate(ln, "likes") < 0.7 * rate(nln, "likes")


def _gemini(body, status=200):
    import httpx
    calls = []

    def handler(request):
        import json as _json
        calls.append(_json.loads(request.content))
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


GOOD = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "思考", "thought": True}, {"text": "建議。" * 80}]}}]}


def test_advice_stores_only_complete_answers():
    import pytest
    from src.pipeline.advice import AdviceError, generate
    client, calls = _gemini(GOOD)
    text = generate("p", "k", "m", client)
    assert text == ("建議。" * 80) and calls[0]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "minimal"}
    cut = {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "半句" * 100}]}}]}
    with pytest.raises(AdviceError, match="MAX_TOKENS"):
        generate("p", "k", "m", _gemini(cut)[0])
    short = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "太短"}]}}]}
    with pytest.raises(AdviceError, match="too short"):
        generate("p", "k", "m", _gemini(short)[0])
    with pytest.raises(AdviceError, match="404"):
        generate("p", "k", "m", _gemini({"error": {"message": "gone"}}, 404)[0])


def test_advice_prompt_is_real_only_aggregates():
    from src.pipeline.advice import build_prompt
    rows = [dict(source="real", views=1000 * (i + 1), likes=10 * (i + 1) + i, replies=i, reposts=0, quotes=0, char_count=20 * (i + 1),
                 post_type="純文字", posted_at=f"2026-11-0{i + 1}T1{i}:00:00+00:00") for i in range(5)]
    rows.append(dict(source="mock", views=10, likes=99999, replies=0, reposts=0, quotes=0, char_count=5, post_type="含連結", posted_at="2026-11-01T00:00:00+00:00"))
    summary = {"metrics": {"real": {"keywords": [{"word": "a"}] * 20}}, "group_analysis": {}, "insights": {"real": [{"text": "p=0.03 顯著"}]}}
    p = build_prompt("acct", summary, rows)
    assert '"真實貼文數": 5' in p and "99999" not in p and "@acct" in p and p.count('"a"') == 8
    assert "顯著" not in p.split("\n\n", 1)[1]  # stored inferential insight text is no longer sent
    import re
    assert "%" in p and not re.search(r"\b0\.\d{3,}", p.split("\n\n", 1)[1])  # percentages, no 0.0359-style fractions
    assert '"中位數"' in p and p.index("中位數") < p.index("平均數")
