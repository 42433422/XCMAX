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
    assert result["summary"]["comment_ranking_model"] == "severity_context_transfer_publishability_v5_external_diagnostics"
    assert result["summary"]["publishable_comment_count"] == len(result["comments"])
    assert result["summary"]["task_group_count"] == len(result["task_groups"])
    assert result["summary"]["actionable_task_group_count"] >= 1
    assert result["comments"][0]["rank_score"] >= result["comments"][1]["rank_score"]
    assert result["comments"][0]["absorbed_context_rank_weight"] >= 20
    assert "bias=" in result["comments"][0]["rank_reason"]
    assert "policy=" in result["comments"][0]["rank_reason"]
    assert "calibration=" in result["comments"][0]["rank_reason"]
    assert "semantic=" in result["comments"][0]["rank_reason"]
    assert result["comments"][0]["calibration_rank_weight"] > 0
    assert result["comments"][0]["publish_payload"]["side"] == "RIGHT"
    assert result["comments"][0]["comment_anchor"]["line"] == result["comments"][0]["line"]
    assert result["file_summaries"][0]["stages"]
    assert result["file_summaries"][0]["review_context"] == "runtime"
    assert result["comments"][0]["review_stage"]
    assert result["comments"][0]["review_context"] == "security"
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


def test_review_diff_secret_line_overrides_file_context_to_security() -> None:
    result = review_diff(_single_add_diff("pr_agent/settings.py", 'OPENAI_API_TOKEN = "live-secret-value"'))

    assert result["comments"][0]["severity"] == "high"
    assert result["comments"][0]["review_context"] == "security"


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
    assert result["summary"]["extension_policy"]["language_family_count"] >= 2
    assert result["summary"]["extension_policy"]["known_extension_count"] == 2
    assert {summary["extension_policy"]["family"] for summary in result["file_summaries"]} >= {"go", "typescript"}


def test_review_diff_applies_holdout_extension_policy_to_cross_language_files() -> None:
    diff = (
        _single_add_diff("src/lib.rs", 'let token = "live-secret-value";')
        + _single_add_diff("native/buffer.cpp", "// TODO: audit pointer lifetime")
        + _single_add_diff("service/Worker.csproj", '<PackageReference Include="Example" Version="1.0.0" />')
        + _single_add_diff("docs/architecture.adoc", "= Architecture")
        + _single_add_diff("go.mod", "require github.com/example/lib v1.2.3")
        + _single_add_diff("scripts/review.unknownext", "# TODO: unknown extension")
    )

    result = review_diff(diff, max_comments=8)
    summary = result["summary"]["extension_policy"]
    summaries_by_file = {item["file"]: item for item in result["file_summaries"]}

    assert summary["policy_source"] == "retort_holdout_extension_policy_v1"
    assert summary["file_count"] == 6
    assert summary["known_extension_count"] == 5
    assert summary["unknown_extension_count"] == 1
    assert summary["language_family_count"] >= 5
    assert {"runtime", "ci_config", "docs", "config"}.issubset(set(summary["review_contexts"]))
    assert {"memory_safety", "dependency_graph", "operator_contract"}.issubset(set(summary["risk_tags"]))
    assert summaries_by_file["src/lib.rs"]["extension_policy"]["family"] == "rust"
    assert summaries_by_file["native/buffer.cpp"]["extension_policy"]["risk_tags"] == ["memory_safety", "build_flags"]
    assert summaries_by_file["service/Worker.csproj"]["review_context"] == "ci_config"
    assert summaries_by_file["docs/architecture.adoc"]["review_context"] == "docs"
    assert summaries_by_file["go.mod"]["extension_policy"]["family"] == "go"
    assert summaries_by_file["scripts/review.unknownext"]["extension_policy"]["known"] is False


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


def test_review_diff_maps_cross_language_pr_bot_patterns_into_core_comments() -> None:
    diff = """diff --git a/.github/workflows/review.yml b/.github/workflows/review.yml
--- a/.github/workflows/review.yml
+++ b/.github/workflows/review.yml
@@ -0,0 +1,4 @@
+on: pull_request_target
+permissions:
+  pull-requests: write
+  issues: write
diff --git a/src/reviewer.ts b/src/reviewer.ts
--- a/src/reviewer.ts
+++ b/src/reviewer.ts
@@ -0,0 +1,3 @@
+const provider = "openai"
+await octokit.rest.pulls.createReview({ pull_number })
+const prompt = buildPrompt(model)
diff --git a/retort_engine/review_bridge.py b/retort_engine/review_bridge.py
--- a/retort_engine/review_bridge.py
+++ b/retort_engine/review_bridge.py
@@ -0,0 +1,2 @@
+subprocess.Popen(["retort-worker"])
+publish(review)
"""

    result = review_diff(diff, max_comments=10)
    transfer = result["summary"]["cross_language_transfer"]
    transfer_comments = [comment for comment in result["comments"] if comment["capability"] == "cross_language_transfer"]

    assert transfer["cross_language_core_mapping"] is True
    assert transfer["language_family_count"] >= 3
    assert transfer["finding_count"] >= 5
    assert transfer["pattern_count"] >= 4
    assert transfer["severity_counts"]["high"] >= 2
    assert transfer_comments
    assert {comment["review_context"] for comment in transfer_comments} >= {"ci_config", "config", "runtime"}
    assert {comment["file"] for comment in transfer_comments} >= {".github/workflows/review.yml", "src/reviewer.ts", "retort_engine/review_bridge.py"}
    assert transfer_comments[0]["rank_reason"].startswith("high:ci_config:cross_language_transfer")
    assert result["summary"]["core_review_score"]["cross_language_core_behavior_active"] is True
    assert result["summary"]["core_review_score"]["cross_language_ranked_comment_count"] == len(transfer_comments)
    assert result["summary"]["core_review_score"]["hunk_semantic_core_behavior_active"] is True
    assert result["summary"]["core_review_score"]["hunk_semantic_top_ranked"] is True
    assert result["cross_language_transfer"]["evidence"]["source"] == "absorbed_pr_bot_cross_language_transfer"


def test_review_diff_ingests_reviewdog_style_external_diagnostics_into_core_ranking() -> None:
    diff = """diff --git a/.github/workflows/reviewdog.yml b/.github/workflows/reviewdog.yml
--- a/.github/workflows/reviewdog.yml
+++ b/.github/workflows/reviewdog.yml
@@ -0,0 +1,4 @@
+on: pull_request_target
+permissions:
+  contents: write
+  pull-requests: write
diff --git a/src/reviewer.go b/src/reviewer.go
--- a/src/reviewer.go
+++ b/src/reviewer.go
@@ -0,0 +1,2 @@
+func publish() { createReviewComment() }
+func ignore() {}
"""

    result = review_diff(
        diff,
        max_comments=8,
        external_diagnostics=[
            {
                "source_project": "reviewdog/reviewdog",
                "path": ".github/workflows/reviewdog.yml",
                "line": 3,
                "rule_id": "reviewdog:github-token-write-scope",
                "severity": "error",
                "message": "reviewdog reporter would publish from a broad token scope",
            },
            {
                "source_project": "reviewdog/reviewdog",
                "path": "src/reviewer.go",
                "line": 99,
                "rule_id": "reviewdog:stale-diagnostic",
                "severity": "warning",
                "message": "this should be dropped because it is outside the added diff",
            },
        ],
    )

    external = [comment for comment in result["comments"] if comment["capability"] == "external_diagnostic_ingestion"]

    assert result["summary"]["external_diagnostic_ingestion"]["accepted_count"] == 1
    assert result["summary"]["external_diagnostic_ingestion"]["dropped_count"] == 1
    assert result["summary"]["external_diagnostic_ingestion"]["diff_line_anchor_enforced"] is True
    assert result["summary"]["core_review_score"]["external_diagnostic_core_behavior_active"] is True
    assert external
    assert external[0]["publishable"] is True
    assert external[0]["line"] == 3
    assert external[0]["external_diagnostic_source"] == "reviewdog/reviewdog"
    assert external[0]["rank_score"] >= 600


def test_review_diff_uses_hunk_semantics_for_validation_regression() -> None:
    diff = """diff --git a/retort_engine/pr_publish.py b/retort_engine/pr_publish.py
--- a/retort_engine/pr_publish.py
+++ b/retort_engine/pr_publish.py
@@ -10,8 +10,8 @@
 def publish_comment(payload):
-    validate_permissions(payload)
-    assert payload["rollback_receipt"]
+    publish(payload)
+    return True
     return payload
"""

    result = review_diff(diff, max_comments=3)
    semantic_comments = [comment for comment in result["comments"] if comment["capability"] == "hunk_semantic_review"]

    assert semantic_comments
    assert semantic_comments[0]["semantic_finding_type"] == "validation_regression"
    assert semantic_comments[0]["severity"] == "high"
    assert semantic_comments[0]["rank_position"] == 1
    assert semantic_comments[0]["semantic_removed_evidence"]
    assert result["summary"]["hunk_semantic_analysis"]["core_behavior_active"] is True
    assert result["summary"]["hunk_semantic_analysis"]["finding_count"] >= 1
    assert result["summary"]["core_review_score"]["hunk_semantic_top_ranked"] is True
    assert result["summary"]["core_review_score"]["hunk_semantic_core_behavior_active"] is True


def test_review_diff_uses_hunk_semantics_for_test_weakening() -> None:
    diff = """diff --git a/tests/test_absorption.py b/tests/test_absorption.py
--- a/tests/test_absorption.py
+++ b/tests/test_absorption.py
@@ -1,3 +1,3 @@
 def test_absorption_merge():
-    assert result["gates_passed"] is True
+    return True
"""

    result = review_diff(diff, max_comments=2)
    semantic_comments = [comment for comment in result["comments"] if comment["capability"] == "hunk_semantic_review"]

    assert semantic_comments
    assert semantic_comments[0]["semantic_finding_type"] == "test_weakening"
    assert semantic_comments[0]["review_context"] == "tests"
    assert result["summary"]["hunk_semantic_analysis"]["finding_types"] == ["test_weakening"]


def test_cross_language_transfer_weight_changes_core_comment_ordering() -> None:
    diff = """diff --git a/app/runtime.py b/app/runtime.py
--- a/app/runtime.py
+++ b/app/runtime.py
@@ -0,0 +1,2 @@
+# TODO: normal runtime cleanup
+subprocess.Popen(["retort-worker"])
"""

    result = review_diff(diff, max_comments=2)

    assert result["comments"][0]["capability"] == "cross_language_transfer"
    assert result["comments"][0]["rank_score"] > result["comments"][1]["rank_score"]
    assert result["summary"]["core_review_score"]["cross_language_top_ranked"] is True


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
    assert review_context_for_file("settings/runtime.yaml") == "config"
    assert review_context_for_file("service/Worker.csproj") == "ci_config"
    assert review_context_for_file("docs/architecture.adoc") == "docs"
    assert review_context_for_file("native/buffer.cpp") == "runtime"
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
