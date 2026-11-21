"""Can the analysis find the 3 patterns planted in the mock data? (docs/mock_design.md)

    python -m src.pipeline.validate_mock --job <job-id>

Runs the same pattern checks the pipeline stores as insights, on three views of the job's posts:
all (real + mock), real only, mock only. Prints a markdown table.
"""

from __future__ import annotations

import argparse

from .analysis import pattern_checks
from .db import Db

EXPECTED = {"question_reply": "higher", "evening_like": "higher", "link_interaction": "lower"}
LABEL = {"question_reply": "提問句 → 回覆率較高", "evening_like": "晚間 → 按讚率較高", "link_interaction": "含連結 → 互動較低"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    args = ap.parse_args()
    posts = Db().select("posts", {"job_id": f"eq.{args.job}", "select": "*"})
    views = {"all": posts, "real": [p for p in posts if p["source"] == "real"], "mock": [p for p in posts if p["source"] == "mock"]}
    print("| 規律 | 資料 | n（組 A / 組 B） | 比值 A/B | p 值 | 判定 | 找回？ |")
    print("|---|---|---|---|---|---|---|")
    for scope, ps in views.items():
        for chk in pattern_checks(ps):
            ev, k = chk["evidence"], chk["key"]
            if ev["enough_data"]:
                found = "✅" if chk["verdict"] == EXPECTED[k] else "❌"
                print(f"| {LABEL[k]} | {scope}（{len(ps)} 篇） | {ev['n_a']} / {ev['n_b']} | {ev['ratio']} | {ev['p_value']} | {chk['verdict']} | {found} |")
            else:
                print(f"| {LABEL[k]} | {scope}（{len(ps)} 篇） | {ev['n_a']} / {ev['n_b']} | – | – | 樣本不足 | – |")


if __name__ == "__main__":
    main()
