from __future__ import annotations

from retort_engine.contracts import validate_contract
from retort_engine.pr_dry_run import pr_diff_url, review_pr_url


PR_DIFF = """diff --git a/app.py b/app.py
index 1111111..2222222 100644
--- a/app.py
+++ b/app.py
@@ -1,2 +1,4 @@
 def handler():
+    token = "live-secret"
+    print("debug")
     return True
"""


def test_pr_diff_url_normalizes_github_pull_url() -> None:
    assert pr_diff_url("https://github.com/sourcefuse/ai-pr-reviewer/pull/12") == "https://github.com/sourcefuse/ai-pr-reviewer/pull/12.diff"
    assert pr_diff_url("https://github.com/sourcefuse/ai-pr-reviewer/pull/12.diff") == "https://github.com/sourcefuse/ai-pr-reviewer/pull/12.diff"


def test_review_pr_url_fetches_diff_and_returns_contract(monkeypatch) -> None:
    def fake_fetch(url: str, *, max_bytes: int) -> tuple[str, int, bool]:
        assert url == "https://github.com/sourcefuse/ai-pr-reviewer/pull/12.diff"
        return PR_DIFF, len(PR_DIFF.encode("utf-8")), False

    monkeypatch.setattr("retort_engine.pr_dry_run._fetch_diff", fake_fetch)

    result = review_pr_url("https://github.com/sourcefuse/ai-pr-reviewer/pull/12", max_comments=5)

    assert result["status"] == "reviewed"
    assert result["summary"]["file_count"] == 1
    assert result["summary"]["comment_count"] >= 2
    assert result["summary"]["fetched_bytes"] == len(PR_DIFF.encode("utf-8"))
    assert validate_contract("pr_dry_run_result", result)["valid"] is True
