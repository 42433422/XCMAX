from retort_engine.absorbed_hunk_semantic_rules import (
    absorbed_hunk_rules,
    match_absorbed_hunk_findings,
)
from retort_engine.pr_review import review_diff


def test_absorbed_hunk_semantic_rules_change_review_diff() -> None:
    rules = absorbed_hunk_rules()
    assert rules["run_id"]
    assert match_absorbed_hunk_findings(["eval(payload)"])

    diff = """diff --git a/web/app.js b/web/app.js
--- a/web/app.js
+++ b/web/app.js
@@ -0,0 +1,2 @@
+const token = localStorage.getItem('api_token');
+eval(token);
"""
    result = review_diff(diff, max_comments=6)
    semantic = [
        row
        for row in result["comments"]
        if row.get("capability") == "hunk_semantic_review"
    ]
    assert semantic
    assert any(
        str(row.get("semantic_finding_type") or "").startswith("absorbed_")
        for row in semantic
    ) or any(
        "eval" in str(row.get("body") or row.get("message") or "").lower()
        for row in semantic
    )
