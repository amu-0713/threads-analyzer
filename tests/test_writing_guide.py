"""Stability filter of the writing guide (src/pipeline/analysis.py)."""

from __future__ import annotations

import random

from src.pipeline.analysis import GUIDE_MIN_POSTS, REP_KEY, analyze, rewrite_example, writing_guide


def _post(i: int, *, question: bool, link: bool, chars: int, evening: bool = False, source: str = "real") -> dict:
    hour = 20 if evening else 10
    return {
        "post_url": f"https://www.threads.com/@x/post/P{i:03d}", "source": source,
        "posted_at": f"2026-11-{1 + i // 2:02d}T{hour:02d}:{(i % 2) * 30:02d}:00+08:00",
        "text": "你覺得呢？" if question else "公告", "url_count": 1 if link else 0, "char_count": chars,
        "views": 1000, "likes": 10, "replies": 1, "reposts": 0, "quotes": 0, "post_type": "純文字", "views_rounded": False,
    }


def _build():
    """24 posts, older half = index 0..11, newer half = 12..23.
    共鳴型 6 + 6 posts: always asks a question and is long, link share FLIPS between the halves, evening never differs.
    低迷型 has 2 posts in the older half (< 3), 討論型 has 2 in the newer half (< 3)."""
    posts, labels = [], {}
    plan = []  # (group, half)
    plan += [("共鳴型", 0)] * 6 + [("低迷型", 0)] * 2 + [("討論型", 0)] * 4
    plan += [("共鳴型", 1)] * 6 + [("低迷型", 1)] * 4 + [("討論型", 1)] * 2
    for i, (g, half) in enumerate(plan):
        resonance = g == "共鳴型"
        # link: 共鳴型 has links only in the older half, the other groups only in the newer half
        link = resonance if half == 0 else not resonance
        p = _post(i, question=resonance, link=link, chars=100 if resonance else 50)
        posts.append(p)
        labels[p["post_url"]] = g
    return posts, labels


def test_only_the_stable_feature_survives():
    posts, labels = _build()
    guide = writing_guide(posts, labels)
    assert guide["available"] and guide["halves"] == [12, 12]
    keys = {f["key"]: f for f in guide["groups"]["共鳴型"]["stable_features"]}
    # question share and length point the same way in both halves -> kept
    assert set(keys) == {"question_share", "char_median"}
    assert keys["question_share"]["direction"] == "higher" and keys["question_share"]["group_value"] == 1.0
    assert keys["char_median"]["direction"] == "higher" and keys["char_median"]["n_group"] == 12
    # link share is higher in the older half and lower in the newer half -> dropped (never listed)
    assert "link_share" not in keys
    # evening share is identical (0 vs 0) in both halves -> no direction -> dropped
    assert "evening_share" not in keys
    assert guide["groups"]["共鳴型"]["n_unstable"] == 2


def test_group_needs_three_posts_in_each_half():
    posts, labels = _build()
    guide = writing_guide(posts, labels)
    assert guide["groups"]["低迷型"]["stable_features"] == []  # only 2 posts in the older half
    assert guide["groups"]["討論型"]["stable_features"] == []  # only 2 posts in the newer half


def test_small_samples_get_no_guide():
    posts, labels = _build()
    few = posts[: GUIDE_MIN_POSTS - 1]
    guide = writing_guide(few, labels)
    assert guide["available"] is False and guide["reason"] == "sample_too_small" and "groups" not in guide


def test_halves_use_the_same_grouping_not_a_regrouping():
    posts, labels = _build()
    relabeled = dict(labels)
    for p in posts[12:]:  # flipping labels in the newer half only changes who is "in" the group there
        relabeled[p["post_url"]] = "討論型"
    guide = writing_guide(posts, relabeled)
    # 共鳴型 now has no posts in the newer half -> cannot be stable
    assert guide["groups"]["共鳴型"]["stable_features"] == []


def test_rewrite_example_names_the_missing_features():
    posts, labels = _build()
    for p in posts:
        p["_like_pct"], p["_reply_pct"] = 0.1, 0.1
    guide = writing_guide(posts, labels)
    # make 共鳴型 stable features apply to the low post: it has no question and is short
    low = next(p for p in posts if labels[p["post_url"]] == "低迷型")
    ex = rewrite_example(posts, labels, guide)
    assert ex is not None and ex["post"]["post_url"] == low["post_url"]
    texts = " ".join(d["text"] for d in ex["differences"])
    assert "這篇沒有提問句" in texts and "共鳴型" in texts and "字" in texts


def test_analyze_adds_the_guide_to_real_scope_only():
    rng = random.Random(3)
    rows = []
    for i in range(40):
        views = rng.randint(800, 5000)
        rows.append({"post_url": f"https://x/{i}", "source": "real", "posted_at": f"2026-10-{1 + i // 2:02d}T0{(i % 8) + 1}:00:00+00:00",
                     "text": "好玩嗎？" if i % 3 == 0 else "分享", "url_count": 1 if i % 7 == 0 else 0, "char_count": rng.randint(10, 300),
                     "views": views, "likes": rng.randint(0, 200), "replies": rng.randint(0, 40), "reposts": 0, "quotes": 0,
                     "post_type": "純文字", "views_rounded": False})
    rows += [dict(rows[0], post_url=f"https://x/m{i}", source="mock") for i in range(10)]
    res = analyze(rows)
    real, allscope = res["group_analysis"]["real"], res["group_analysis"]["all"]
    assert real["writing_guide"]["available"] and "writing_guide" not in allscope
    assert real["groups"]["共鳴型"]["goal"] == "提高按讚、建立好感" and real["groups"]["討論型"]["goal"] == "帶動討論、收集意見"
    # every listed feature really is stable: same non-"same" direction in both halves with >= 3 group posts each
    for g, grp in real["writing_guide"]["groups"].items():
        for f in grp["stable_features"]:
            h1, h2 = f["halves"]
            assert h1["direction"] == h2["direction"] == f["direction"] != "same"
            assert h1["n_group"] >= 3 and h2["n_group"] >= 3


# ---------------------------------------------------------------- minimum gap (relative 20 % for length, 10 points for shares)
def _two_groups(chars_g: tuple[int, int], chars_o: tuple[int, int], q_g: tuple[float, float], q_o: tuple[float, float]):
    """共鳴型 vs 低迷型, 6 posts each per half. chars_*/q_* = (older half, newer half) median length / question share."""
    posts, labels, i = [], {}, 0
    for half in (0, 1):
        for g, chars, qshare in (("共鳴型", chars_g[half], q_g[half]), ("低迷型", chars_o[half], q_o[half])):
            for k in range(6):
                p = _post(i, question=k < round(qshare * 6), link=False, chars=chars)
                posts.append(p)
                labels[p["post_url"]] = g
                i += 1
    return posts, labels


def _keys(posts, labels, group="共鳴型"):
    return {f["key"] for f in writing_guide(posts, labels)["groups"][group]["stable_features"]}


def test_small_gap_is_dropped_even_when_the_direction_is_the_same():
    # length: 38 vs 35 chars (about 9 %) in both halves; questions: 100 % vs 0 % in both halves
    posts, labels = _two_groups((38, 38), (35, 35), (1.0, 1.0), (0.0, 0.0))
    assert _keys(posts, labels) == {"question_share"}


def test_gap_must_be_big_enough_in_both_halves():
    # length: 100 vs 50 in the older half (+100 %) but 52 vs 50 in the newer half (+4 %) -> dropped
    posts, labels = _two_groups((100, 52), (50, 50), (1.0, 1.0), (0.0, 0.0))
    assert "char_median" not in _keys(posts, labels)
    # question share: 4/6 vs 3/6 in the older half (17 points), 3/6 vs 3/6 in the newer half (no gap) -> dropped
    posts, labels = _two_groups((100, 100), (50, 50), (4 / 6, 3 / 6), (3 / 6, 3 / 6))
    assert "question_share" not in _keys(posts, labels)  # newer half: 50 % vs 50 %


def test_exact_threshold_values():
    from src.pipeline.analysis import gap_big_enough

    assert gap_big_enough(60, 50, False)          # exactly +20 % of the others value
    assert not gap_big_enough(59, 50, False)      # +18 %
    assert gap_big_enough(40, 50, False)          # exactly -20 %
    assert not gap_big_enough(35, 38, False)      # the pchome24h case: about 8 %
    assert gap_big_enough(0.6, 0.5, True)         # exactly 10 points
    assert not gap_big_enough(0.55, 0.5, True)    # 5 points
    assert not gap_big_enough(None, 0.5, True) and not gap_big_enough(50, 50, False)
