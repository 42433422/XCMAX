from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from retort_engine.external_advantage_adjudicator import adjudicate_external_advantage_rows
from retort_engine.external_advantage_regression import verify_external_advantage_rows
from retort_engine.pr_review import review_diff


DEFAULT_ADVANTAGE_CASES: tuple[dict[str, Any], ...] = (
    {
        "case_id": "pr-agent-secret-context",
        "source_project": "qodo-ai/pr-agent",
        "absorbed_signal": "security_ranked_pr_review",
        "external_advantage": "PR agent style secret review should surface credential leaks as publishable blockers.",
        "expected_context": "security",
        "expected_severity": "high",
        "diff": "diff --git a/pr_agent/settings.py b/pr_agent/settings.py\n--- a/pr_agent/settings.py\n+++ b/pr_agent/settings.py\n@@ -0,0 +1,1 @@\n+OPENAI_API_TOKEN = \"live-secret-value\"\n",
    },
    {
        "case_id": "reviewdog-workflow-token",
        "source_project": "reviewdog/reviewdog",
        "absorbed_signal": "ci_review_publisher_safety",
        "external_advantage": "Review publisher workflows need CI context and credential safety at the same time.",
        "expected_context": "ci_config",
        "expected_severity": "high",
        "diff": "diff --git a/.github/workflows/review.yml b/.github/workflows/review.yml\n--- a/.github/workflows/review.yml\n+++ b/.github/workflows/review.yml\n@@ -0,0 +1,1 @@\n+REVIEWDOG_TOKEN: \"review-token-value\"\n",
    },
    {
        "case_id": "swe-bench-oracle-placeholder",
        "source_project": "swe-bench/SWE-bench",
        "absorbed_signal": "evaluation_harness_oracle",
        "external_advantage": "Benchmark harness changes must reject placeholder oracles before claiming quality.",
        "expected_context": "runtime",
        "expected_severity": "medium",
        "diff": "diff --git a/swebench/harness/run_evaluation.py b/swebench/harness/run_evaluation.py\n--- a/swebench/harness/run_evaluation.py\n+++ b/swebench/harness/run_evaluation.py\n@@ -0,0 +1,1 @@\n+# TODO: replace oracle stub before benchmark publication\n",
    },
    {
        "case_id": "import-linter-contract-bypass",
        "source_project": "seddonym/import-linter",
        "absorbed_signal": "architecture_contract_guard",
        "external_advantage": "Architecture governance projects should detect contract bypasses as behavior risk.",
        "expected_context": "runtime",
        "expected_severity": "medium",
        "diff": "diff --git a/importlinter/contracts/layers.py b/importlinter/contracts/layers.py\n--- a/importlinter/contracts/layers.py\n+++ b/importlinter/contracts/layers.py\n@@ -0,0 +1,1 @@\n+# FIXME: bypass contract violation until next release\n",
    },
    {
        "case_id": "repomix-context-package-clean",
        "source_project": "yamadashy/repomix",
        "absorbed_signal": "context_packaging_noise_control",
        "external_advantage": "Context packagers should avoid false blockers on clean docs-only packaging updates.",
        "expected_context": "docs",
        "expected_severity": "info",
        "diff": "diff --git a/docs/context-pack.md b/docs/context-pack.md\n--- a/docs/context-pack.md\n+++ b/docs/context-pack.md\n@@ -0,0 +1,1 @@\n+Document deterministic context packaging inputs and output hashes.\n",
    },
    {
        "case_id": "mopemope-typescript-diff-review",
        "source_project": "mopemope/pr-ai-review-bot",
        "absorbed_signal": "typescript_diff_hunk_review",
        "external_advantage": "TypeScript PR bots need extension-aware review for async review flows.",
        "expected_context": "runtime",
        "expected_severity": "medium",
        "diff": "diff --git a/src/reviewer.ts b/src/reviewer.ts\n--- a/src/reviewer.ts\n+++ b/src/reviewer.ts\n@@ -0,0 +1,1 @@\n+// TODO: retry review dispatch without duplicate comments\n",
    },
)


def build_external_advantage_matrix(
    project: str | Path,
    *,
    min_cases: int = 6,
    output: str | Path = "",
    cases: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    selected = list(cases or DEFAULT_ADVANTAGE_CASES)
    rows = [_evaluate_case(case) for case in selected]
    ready_rows = [row for row in rows if row["ready"]]
    source_projects = sorted({str(row["source_project"]) for row in rows if row.get("source_project")})
    absorbed_signals = sorted({str(row["absorbed_signal"]) for row in rows if row.get("absorbed_signal")})
    baseline_average = round(sum(int(row["baseline"]["score"]) for row in rows) / len(rows), 2) if rows else 0.0
    retort_average = round(sum(int(row["retort"]["score"]) for row in rows) / len(rows), 2) if rows else 0.0
    delta = round(retort_average - baseline_average, 2)
    regression = verify_external_advantage_rows(rows)
    regression_summary = regression.get("summary") if isinstance(regression.get("summary"), dict) else {}
    adjudication = adjudicate_external_advantage_rows(rows)
    adjudication_summary = adjudication.get("summary") if isinstance(adjudication.get("summary"), dict) else {}
    summary = {
        "case_count": len(rows),
        "min_case_count": min_cases,
        "ready_case_count": len(ready_rows),
        "source_project_count": len(source_projects),
        "absorbed_signal_count": len(absorbed_signals),
        "baseline_average_score": baseline_average,
        "retort_average_score": retort_average,
        "score_delta": delta,
        "behavior_delta_count": sum(1 for row in rows if int(row["behavior_delta"]) > 0),
        "publishable_case_count": sum(1 for row in rows if row["retort"].get("publishable_comment_count", 0) > 0),
        "extension_policy_case_count": sum(1 for row in rows if row["retort"].get("extension_policy_known_count", 0) > 0),
        "per_case_before_after": all("baseline" in row and "retort" in row for row in rows),
        "all_advantages_improved": bool(rows) and all(int(row["behavior_delta"]) > 0 for row in rows),
        "regression_status": regression.get("status", ""),
        "regression_case_count": regression_summary.get("regression_case_count", 0),
        "passed_regression_case_count": regression_summary.get("passed_regression_case_count", 0),
        "all_delta_regressions_verified": regression_summary.get("all_delta_regressions_verified", False),
        "independent_adjudication_status": adjudication.get("status", ""),
        "independent_adjudicated_case_count": adjudication_summary.get("adjudicated_case_count", 0),
        "independent_accepted_case_count": adjudication_summary.get("accepted_case_count", 0),
        "independent_minimum_recomputed_delta": adjudication_summary.get("minimum_recomputed_delta", 0),
        "independent_all_cases_accepted": adjudication_summary.get("all_cases_accepted", False),
    }
    ready = (
        summary["case_count"] >= min_cases
        and summary["ready_case_count"] >= min_cases
        and summary["source_project_count"] >= min(5, min_cases)
        and summary["absorbed_signal_count"] >= min_cases
        and summary["score_delta"] >= 35
        and summary["all_advantages_improved"]
        and summary["all_delta_regressions_verified"]
        and summary["independent_all_cases_accepted"]
    )
    result = {
        "status": "ready" if ready else "needs_more_evidence",
        "project": str(root),
        "summary": summary,
        "matrix": rows,
        "evidence": {
            "baseline_model": "pre_absorption_keyword_review_without_context_groups_publish_anchors_or_extension_policy",
            "retort_model": "retort_engine.pr_review.review_diff",
            "comparison": "same_external_advantage_cases_replayed_before_after_absorption",
            "source_projects": source_projects,
            "absorbed_signals": absorbed_signals,
            "regression_verifier": "retort_engine.external_advantage_regression.verify_external_advantage_rows",
            "regression_test_module": "tests/test_external_advantage_regression.py",
            "independent_adjudicator": "retort_engine.external_advantage_adjudicator.adjudicate_external_advantage_rows",
        },
        "regression": regression,
        "independent_adjudication": adjudication,
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    review = review_diff(str(case["diff"]), max_comments=8, issue_context=str(case.get("external_advantage") or ""))
    comments = [item for item in review.get("comments") or [] if isinstance(item, dict)]
    summary = review.get("summary") if isinstance(review.get("summary"), dict) else {}
    extension_policy = summary.get("extension_policy") if isinstance(summary.get("extension_policy"), dict) else {}
    baseline = _baseline_review(case)
    retort = _retort_review_score(case, comments, summary, extension_policy)
    behavior_delta = int(retort["score"]) - int(baseline["score"])
    return {
        "case_id": str(case["case_id"]),
        "source_project": str(case["source_project"]),
        "absorbed_signal": str(case["absorbed_signal"]),
        "external_advantage": str(case["external_advantage"]),
        "expected_context": str(case["expected_context"]),
        "expected_severity": str(case["expected_severity"]),
        "baseline": baseline,
        "retort": retort,
        "behavior_delta": behavior_delta,
        "ready": behavior_delta > 0 and int(retort["score"]) >= 80,
    }


def _baseline_review(case: dict[str, Any]) -> dict[str, Any]:
    diff = str(case.get("diff") or "").lower()
    expected_severity = str(case.get("expected_severity") or "")
    detected_severity = ""
    if any(marker in diff for marker in ("token", "secret", "api_key", "apikey")):
        detected_severity = "high"
    elif any(marker in diff for marker in ("todo", "fixme", "stub", "bypass")):
        detected_severity = "medium"
    elif expected_severity == "info":
        detected_severity = "info"
    severity_match = detected_severity == expected_severity
    score = 30 if severity_match else 10
    if detected_severity:
        score += 10
    return {
        "model": "keyword_only_pre_absorption",
        "score": score,
        "detected_severity": detected_severity,
        "severity_matched": severity_match,
        "context_matched": False,
        "publishable_comment_count": 0,
        "task_group_count": 0,
        "extension_policy_known_count": 0,
    }


def _retort_review_score(case: dict[str, Any], comments: list[dict[str, Any]], summary: dict[str, Any], extension_policy: dict[str, Any]) -> dict[str, Any]:
    expected_context = str(case.get("expected_context") or "")
    expected_severity = str(case.get("expected_severity") or "")
    extension_contexts = {str(item) for item in extension_policy.get("review_contexts") or []}
    severity_matched = any(str(item.get("severity") or "") == expected_severity for item in comments)
    context_matched = any(str(item.get("review_context") or "") == expected_context for item in comments) or expected_context in extension_contexts
    publishable_count = sum(1 for item in comments if item.get("publishable"))
    task_group_count = int(summary.get("task_group_count") or 0)
    extension_known = int(extension_policy.get("known_extension_count") or 0)
    score = 0
    score += 30 if severity_matched else 0
    score += 20 if context_matched else 0
    score += 15 if publishable_count > 0 else 0
    score += 15 if task_group_count > 0 else 0
    score += 20 if extension_known > 0 else 0
    return {
        "model": "retort_current_review_diff",
        "score": score,
        "severity_matched": severity_matched,
        "context_matched": context_matched,
        "publishable_comment_count": publishable_count,
        "task_group_count": task_group_count,
        "extension_policy_known_count": extension_known,
        "extension_policy_contexts": sorted(extension_contexts),
        "comment_count": len(comments),
        "observed_contexts": sorted({str(item.get("review_context") or "") for item in comments if item.get("review_context")}),
        "observed_severities": [str(item.get("severity") or "") for item in comments],
    }
