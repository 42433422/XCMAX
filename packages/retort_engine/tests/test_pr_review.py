from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.pr_review import group_related_files_for_review, parse_unified_diff, review_context_for_file, review_diff


SAMPLE_DIFF = """diff --git a/app.py b/app.py
index 1111111..2222222 100644
--- a/app.py
+++ b/app.py
@@ -1,2 +1,4 @@
 def handler():
+    api_key = "live-secret"
+    # TODO: replace with real absorption action
     return True
"""

PREVIOUS_DIFF = """diff --git a/app.py b/app.py
index 1111111..2222222 100644
--- a/app.py
+++ b/app.py
@@ -1,2 +1,3 @@
 def handler():
+    # TODO: replace with real absorption action
     return True
"""

INCREMENTAL_DIFF = """diff --git a/app.py b/app.py
index 1111111..3333333 100644
--- a/app.py
+++ b/app.py
@@ -1,2 +1,4 @@
 def handler():
+    # TODO: replace with real absorption action
+    token = "live-secret"
     return True
"""


def test_review_diff_returns_line_comments_and_groups() -> None:
    result = review_diff(SAMPLE_DIFF)
    severities = {comment["severity"] for comment in result["comments"]}

    assert result["status"] == "reviewed"
    assert result["summary"]["ready_for_employee_tasking"] is True
    assert {"high", "medium"}.issubset(severities)
    assert result["task_groups"]
    assert result["summary"]["deep_review_pipeline"] is True
    assert result["summary"]["stage_count"] >= 5
    assert result["summary"]["review_context_group_count"] == 1
    assert result["summary"]["absorbed_file_grouping"] is True
    assert result["summary"]["absorbed_context_rank_weights"]["runtime"] >= 20
    assert "absorbed_policy_rank_weights" in result["summary"]
    assert "absorbed_review_policy" in result["summary"]
    assert result["summary"]["calibration_policy"]["enabled"] is True
    assert result["summary"]["calibration_rank_weights"]["runtime"] > 0
    assert result["summary"]["risk_counts"]["high"] >= 1
    assert result["summary"]["comment_ranking_model"] == "severity_context_publishability_v1"
    assert result["summary"]["publishable_comment_count"] == len(result["comments"])
    assert result["comments"][0]["rank_score"] >= result["comments"][1]["rank_score"]
    assert result["comments"][0]["absorbed_context_rank_weight"] >= 20
    assert "bias=" in result["comments"][0]["rank_reason"]
    assert "policy=" in result["comments"][0]["rank_reason"]
    assert "calibration=" in result["comments"][0]["rank_reason"]
    assert result["comments"][0]["calibration_rank_weight"] > 0
    assert result["comments"][0]["publish_payload"]["side"] == "RIGHT"
    assert result["comments"][0]["comment_anchor"]["line"] == result["comments"][0]["line"]
    assert result["file_summaries"][0]["stages"]
    assert result["file_summaries"][0]["review_context"] == "runtime"
    assert result["comments"][0]["review_stage"]
    assert result["comments"][0]["review_context"] == "runtime"
    assert result["comments"][0]["employee_actionable"] is True
    assert result["task_groups"][0]["risk_counts"]
    assert result["task_groups"][0]["publishable_comment_count"] >= 1
    assert result["context_groups"][0]["review_focus"] == "core_execution_path"
    assert result["incremental"]["enabled"] is False
    assert validate_contract("pr_review_result", result)["valid"] is True


def test_review_diff_can_review_only_new_changes() -> None:
    result = review_diff(INCREMENTAL_DIFF, previous_diff_text=PREVIOUS_DIFF)

    assert result["status"] == "reviewed"
    assert result["incremental"]["enabled"] is True
    assert result["summary"]["skipped_existing_change_count"] == 1
    assert result["summary"]["reviewed_new_change_count"] == 1
    assert [comment["severity"] for comment in result["comments"]] == ["high"]
    assert result["comments"][0]["line"] == 3
    assert validate_contract("pr_review_result", result)["valid"] is True


def test_review_diff_ranks_high_risk_later_files_before_low_noise() -> None:
    diff = """diff --git a/app/debug.py b/app/debug.py
--- a/app/debug.py
+++ b/app/debug.py
@@ -0,0 +1,2 @@
+print("debug")
+def ok(): return True
diff --git a/app/security.py b/app/security.py
--- a/app/security.py
+++ b/app/security.py
@@ -0,0 +1,1 @@
+SERVICE_TOKEN = "live-secret-value"
"""

    result = review_diff(diff, max_comments=1)

    assert result["summary"]["candidate_comment_count"] > result["summary"]["comment_count"]
    assert result["summary"]["suppressed_comment_count"] >= 1
    assert result["comments"][0]["severity"] == "high"
    assert result["comments"][0]["file"] == "app/security.py"
    assert result["comments"][0]["rank_position"] == 1
    assert result["comments"][0]["publish_payload"] == {
        "path": "app/security.py",
        "line": 1,
        "side": "RIGHT",
        "body": result["comments"][0]["message"],
    }


def test_review_diff_keeps_publishable_anchors_for_multiple_languages() -> None:
    diff = """diff --git a/src/main.go b/src/main.go
--- a/src/main.go
+++ b/src/main.go
@@ -0,0 +1,2 @@
+func main() {}
+// TODO: replace generated worker
diff --git a/src/App.tsx b/src/App.tsx
--- a/src/App.tsx
+++ b/src/App.tsx
@@ -0,0 +1,1 @@
+const token = "live-secret-value"
"""

    result = review_diff(diff)

    assert {comment["file"] for comment in result["comments"]} >= {"src/main.go", "src/App.tsx"}
    assert all(comment["publishable"] is True for comment in result["comments"])
    assert all(comment["comment_anchor"]["side"] == "RIGHT" for comment in result["comments"])
    assert {comment["review_context"] for comment in result["comments"]} >= {"runtime", "frontend"}


def test_review_diff_ignores_documented_or_fake_secret_terms() -> None:
    diff = '''diff --git a/tests/test_keys.py b/tests/test_keys.py
--- a/tests/test_keys.py
+++ b/tests/test_keys.py
@@ -0,0 +1,5 @@
+# resolve_api_key uses platform-key in tests only.
+"""Documented SERVICE_TOKEN fallback is redacted."""
+monkeypatch.setattr(resolver, "resolve_api_key", lambda *a: ("platform-key", "platform"))
+TOKEN_EXAMPLE = "redacted"
+REAL_TOKEN = "live-secret-value"
'''

    result = review_diff(diff)

    high_comments = [item for item in result["comments"] if item["severity"] == "high"]
    assert len(high_comments) == 1
    assert high_comments[0]["line"] == 5


def test_review_diff_surfaces_static_analysis_findings() -> None:
    diff = """diff --git a/app/runner.py b/app/runner.py
--- a/app/runner.py
+++ b/app/runner.py
@@ -0,0 +1,2 @@
+subprocess.run(command, shell=True)
+yaml.load(payload)
"""

    result = review_diff(diff)

    assert result["summary"]["static_analysis"]["high_count"] == 2
    assert {comment["capability"] for comment in result["comments"]} >= {"static_analysis"}
    assert {comment["line"] for comment in result["comments"] if comment["capability"] == "static_analysis"} == {1, 2}


def test_review_diff_surfaces_issue_intent_mismatch() -> None:
    diff = """diff --git a/app/theme.css b/app/theme.css
--- a/app/theme.css
+++ b/app/theme.css
@@ -0,0 +1,2 @@
+.hero { color: blue; }
+.card { border-radius: 8px; }
"""

    result = review_diff(diff, issue_context="Fix password reset token expiry in auth flow", pr_body="Refresh dashboard colors")

    assert result["intent_alignment"]["status"] == "misaligned"
    assert result["summary"]["intent_alignment"]["aligned"] is False
    assert any(comment["capability"] == "intent_alignment" for comment in result["comments"])
    assert validate_contract("pr_review_result", result)["valid"] is True


def test_review_diff_groups_related_files_by_review_context() -> None:
    diff = """diff --git a/app/auth.py b/app/auth.py
--- a/app/auth.py
+++ b/app/auth.py
@@ -1,2 +1,3 @@
 def login():
+    api_key = "live-secret-value"
     return True
diff --git a/tests/test_auth.py b/tests/test_auth.py
--- a/tests/test_auth.py
+++ b/tests/test_auth.py
@@ -1,2 +1,3 @@
 def test_login():
+    assert True
     pass
diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -1,2 +1,3 @@
 name: ci
+on: [push]
 jobs: {}
diff --git a/docs/review.md b/docs/review.md
--- a/docs/review.md
+++ b/docs/review.md
@@ -1,2 +1,3 @@
 # Review
+Deep absorption evidence
"""

    result = review_diff(diff)
    contexts = {group["context"] for group in result["context_groups"]}

    assert {"security", "tests", "ci_config", "docs"}.issubset(contexts)
    assert result["summary"]["review_context_group_count"] >= 4
    assert result["summary"]["absorbed_context_signal_strength"] >= 40
    assert any(comment["review_context"] == "security" for comment in result["comments"])
    assert any(group["review_focus"] == "repeatable_gates_and_release_safety" for group in result["context_groups"])
    assert validate_contract("pr_review_result", result)["valid"] is True


def test_review_diff_balances_contexts_for_large_diffs() -> None:
    sections = [
        _single_add_diff("app/auth.py", 'API_TOKEN = "live-secret-value"'),
        _single_add_diff("tests/test_auth.py", "# TODO: assert auth behavior"),
        _single_add_diff(".github/workflows/ci.yml", 'DEPLOY_TOKEN: "live-secret-value"'),
        _single_add_diff("settings/runtime.yaml", 'SERVICE_TOKEN: "live-secret-value"'),
        _single_add_diff("app/runtime_1.py", "# TODO: runtime follow-up 1"),
        _single_add_diff("app/runtime_2.py", "# TODO: runtime follow-up 2"),
        _single_add_diff("app/runtime_3.py", "# TODO: runtime follow-up 3"),
        _single_add_diff("app/runtime_4.py", "# TODO: runtime follow-up 4"),
        _single_add_diff("docs/release.md", "# TODO: document release"),
    ]

    result = review_diff("".join(sections), max_comments=4)
    contexts = [comment["review_context"] for comment in result["comments"]]

    assert result["summary"]["large_diff_chunking"] is True
    assert result["summary"]["large_diff_context_balancing"] is True
    assert result["summary"]["large_diff_chunk_count"] >= 5
    assert len(result["comments"]) == 4
    assert {"security", "tests", "ci_config", "config"}.issubset(set(contexts))
    assert contexts[0] == "security"
    assert all(comment["publishable"] is True for comment in result["comments"])


def test_review_diff_employee_feedback_changes_next_ranking() -> None:
    diff = _single_add_diff("app/runtime.py", "# TODO: finish runtime behavior") + _single_add_diff("tests/test_runtime.py", "# TODO: assert runtime behavior")

    before = review_diff(diff, max_comments=1)
    after = review_diff(diff, max_comments=1, employee_feedback=[{"dimension": "test_gate_evidence", "status": "failed"}])

    assert before["comments"][0]["review_context"] == "runtime"
    assert before["summary"]["employee_feedback_ranked"] is False
    assert after["comments"][0]["review_context"] == "tests"
    assert after["comments"][0]["feedback_rank_weight"] >= 100
    assert "feedback=" in after["comments"][0]["rank_reason"]
    assert after["summary"]["employee_feedback_ranked"] is True
    assert after["summary"]["employee_feedback_context_weights"]["tests"] >= 100


def test_review_context_helpers_classify_common_project_files() -> None:
    assert review_context_for_file("app/auth.py") == "security"
    assert review_context_for_file("tests/test_auth.py") == "tests"
    assert review_context_for_file(".github/workflows/ci.yml") == "ci_config"
    assert review_context_for_file("docs/review.md") == "docs"
    groups = group_related_files_for_review(["app/auth.py", "tests/test_auth.py"])
    assert [group["context"] for group in groups] == ["security", "tests"]


def test_review_diff_employee_feedback_changes_ranking_across_core_dimensions() -> None:
    diff = (
        _single_add_diff("app/runtime.py", "# TODO: finish runtime behavior")
        + _single_add_diff("tests/test_runtime.py", "# TODO: assert runtime behavior")
        + _single_add_diff(".github/workflows/ci.yml", "# TODO: prove release gate")
        + _single_add_diff("app/security.py", "# TODO: verify auth boundary")
    )

    cases = [
        {
            "dimension": "test_gate_evidence",
            "expected_context": "tests",
            "expected_file": "tests/test_runtime.py",
            "expected_weight": 120,
        },
        {
            "dimension": "operational_readiness",
            "expected_context": "ci_config",
            "expected_file": ".github/workflows/ci.yml",
            "expected_weight": 100,
        },
        {
            "dimension": "feedback_loop_closure",
            "expected_context": "runtime",
            "expected_file": "app/runtime.py",
            "expected_weight": 80,
        },
        {
            "dimension": "safety_license_gate",
            "expected_context": "security",
            "expected_file": "app/security.py",
            "expected_weight": 110,
        },
        {
            "dimension": "architecture_depth",
            "expected_context": "runtime",
            "expected_file": "app/runtime.py",
            "expected_weight": 70,
        },
    ]

    for case in cases:
        result = review_diff(
            diff,
            max_comments=1,
            employee_feedback=[{"dimension": case["dimension"], "status": "failed"}],
        )
        first = result["comments"][0]

        assert first["file"] == case["expected_file"]
        assert first["review_context"] == case["expected_context"]
        assert first["feedback_rank_weight"] >= case["expected_weight"]
        assert result["summary"]["employee_feedback_ranked"] is True
        assert result["summary"]["employee_feedback_context_weights"][case["expected_context"]] >= case["expected_weight"]


def test_review_diff_product_feedback_prioritizes_frontend_without_security_override() -> None:
    diff = (
        _single_add_diff("tests/test_runtime.py", "# TODO: assert runtime behavior")
        + _single_add_diff("ui/App.tsx", "# TODO: prove user flow")
        + _single_add_diff("docs/ops.md", "# TODO: document operator path")
    )

    before = review_diff(diff, max_comments=4)
    after = review_diff(
        diff,
        max_comments=4,
        employee_feedback=[{"dimension": "product_operability", "status": "failed"}],
    )
    before_frontend = next(comment for comment in before["comments"] if comment["review_context"] == "frontend")
    after_frontend = next(comment for comment in after["comments"] if comment["review_context"] == "frontend")

    assert before["comments"][0]["review_context"] != "frontend"
    assert after_frontend["rank_position"] < before_frontend["rank_position"]
    assert after_frontend["file"] == "ui/App.tsx"
    assert after_frontend["feedback_rank_weight"] >= 90
    assert after["summary"]["employee_feedback_context_weights"]["frontend"] >= 90
    assert after["summary"]["employee_feedback_context_weights"]["docs"] >= 60


def test_review_diff_ignores_successful_employee_feedback_for_ranking() -> None:
    diff = (
        _single_add_diff("app/runtime.py", "# TODO: finish runtime behavior")
        + _single_add_diff("tests/test_runtime.py", "# TODO: assert runtime behavior")
    )

    before = review_diff(diff, max_comments=1)
    after = review_diff(
        diff,
        max_comments=1,
        employee_feedback=[{"dimension": "test_gate_evidence", "status": "completed"}],
    )

    assert after["comments"][0]["file"] == before["comments"][0]["file"]
    assert after["summary"]["employee_feedback_ranked"] is False
    assert after["summary"]["employee_feedback_context_weights"] == {}


def test_review_diff_employee_feedback_accepts_nested_task_dimension() -> None:
    diff = (
        _single_add_diff("app/runtime.py", "# TODO: finish runtime behavior")
        + _single_add_diff("tests/test_runtime.py", "# TODO: assert runtime behavior")
    )

    result = review_diff(
        diff,
        max_comments=1,
        employee_feedback=[{"task": {"dimension": "test_gate_evidence"}, "status": "blocked"}],
    )

    assert result["comments"][0]["file"] == "tests/test_runtime.py"
    assert result["comments"][0]["review_context"] == "tests"
    assert result["comments"][0]["feedback_rank_weight"] >= 120
    assert result["summary"]["employee_feedback_ranked"] is True


def test_parse_unified_diff_keeps_new_line_numbers() -> None:
    files = parse_unified_diff(SAMPLE_DIFF)
    added = [change for change in files[0]["hunks"][0]["changes"] if change["type"] == "add"]

    assert files[0]["path"] == "app.py"
    assert [change["line"] for change in added] == [2, 3]


def _single_add_diff(path: str, line: str) -> str:
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -0,0 +1,1 @@\n+{line}\n"


def test_review_diff_cli_outputs_contract(tmp_path: Path) -> None:
    diff_file = tmp_path / "change.diff"
    previous_file = tmp_path / "previous.diff"
    diff_file.write_text(SAMPLE_DIFF, encoding="utf-8")
    previous_file.write_text(PREVIOUS_DIFF, encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "retort_engine.cli",
            "review-diff",
            "--diff-file",
            str(diff_file),
            "--previous-diff-file",
            str(previous_file),
            "--json",
        ],
        check=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = json.loads(result.stdout)

    assert payload["summary"]["comment_count"] >= 1
    assert payload["summary"]["skipped_existing_change_count"] == 1
    assert validate_contract("pr_review_result", payload)["valid"] is True
