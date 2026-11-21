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
