from retort_engine.absorbed_review_rank_weights import (
    capability_rank_boost,
    external_source_boost,
    absorbed_rank_weights,
)
from retort_engine.pr_review import review_diff


def test_absorbed_review_rank_weights_change_external_diagnostic_ranking() -> None:
    weights = absorbed_rank_weights()
    assert weights["run_id"]
    assert (
        external_source_boost(
            "reviewdog/reviewdog", "reviewdog:github-token-write-scope"
        )
        >= 20
    )
    assert capability_rank_boost("external_diagnostic_ingestion") >= 10

    diff = """diff --git a/.github/workflows/reviewdog.yml b/.github/workflows/reviewdog.yml
--- a/.github/workflows/reviewdog.yml
+++ b/.github/workflows/reviewdog.yml
@@ -0,0 +1,3 @@
+on: pull_request_target
+permissions:
+  contents: write
"""
    result = review_diff(
        diff,
        max_comments=6,
        external_diagnostics=[
            {
                "source_project": "reviewdog/reviewdog",
                "path": ".github/workflows/reviewdog.yml",
                "line": 3,
                "rule_id": "reviewdog:github-token-write-scope",
                "severity": "error",
                "message": "write scope on pull_request_target",
            }
        ],
    )
    external = [
        row
        for row in result["comments"]
        if row.get("capability") == "external_diagnostic_ingestion"
    ]
    assert external
    assert external[0]["external_diagnostic_rank_weight"] >= 55 + 20
    assert result["comments"][0]["capability"] == "external_diagnostic_ingestion"
