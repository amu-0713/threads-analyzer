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
