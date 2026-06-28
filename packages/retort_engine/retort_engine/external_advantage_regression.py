from __future__ import annotations

from typing import Any

from retort_engine.pr_review import review_diff


def verify_external_advantage_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    cases = [_verify_row(row) for row in rows]
    passed = [case for case in cases if case["passed"]]
    direct_cases = [case for case in cases if case["checks"]["direct_review_execution"]]
    return {
        "status": "ready" if cases and len(passed) == len(cases) else "needs_attention",
        "summary": {
            "regression_case_count": len(cases),
            "passed_regression_case_count": len(passed),
            "direct_execution_case_count": len(direct_cases),
            "all_use_direct_review_execution": bool(cases) and len(direct_cases) == len(cases),
            "all_delta_regressions_verified": bool(cases) and len(passed) == len(cases),
            "all_have_before_after_scores": all(case["checks"]["before_after_scores"] for case in cases) if cases else False,
            "all_have_positive_delta": all(case["checks"]["positive_delta"] for case in cases) if cases else False,
            "all_match_expected_context": all(case["checks"]["expected_context"] for case in cases) if cases else False,
            "all_match_expected_severity": all(case["checks"]["expected_severity"] for case in cases) if cases else False,
            "all_have_publishable_output": all(case["checks"]["publishable_output"] for case in cases) if cases else False,
        },
        "cases": cases,
        "evidence": {
            "verifier": "retort_engine.external_advantage_regression.verify_external_advantage_rows",
            "model": "same_external_diffs_replayed_through_review_diff_runtime",
            "direct_runtime": "retort_engine.pr_review.review_diff",
        },
    }


def _verify_row(row: dict[str, Any]) -> dict[str, Any]:
    baseline = row.get("baseline") if isinstance(row.get("baseline"), dict) else {}
    retort = row.get("retort") if isinstance(row.get("retort"), dict) else {}
    expected_context = str(row.get("expected_context") or "")
    expected_severity = str(row.get("expected_severity") or "")
    observed_contexts = {str(item) for item in retort.get("observed_contexts") or [] if str(item)}
    observed_severities = {str(item) for item in retort.get("observed_severities") or [] if str(item)}
    try:
        baseline_score = int(baseline.get("score") or 0)
        retort_score = int(retort.get("score") or 0)
        behavior_delta = int(row.get("behavior_delta") or 0)
    except (TypeError, ValueError):
        baseline_score = 0
        retort_score = 0
        behavior_delta = 0
    direct = _direct_review_assertions(row, expected_context, expected_severity)
    checks = {
        "before_after_scores": retort_score > baseline_score >= 0,
        "positive_delta": behavior_delta == retort_score - baseline_score and behavior_delta > 0,
        "expected_context": bool(expected_context)
        and (bool(retort.get("context_matched")) or expected_context in observed_contexts)
        and direct["context_matched"],
        "expected_severity": bool(expected_severity)
        and (bool(retort.get("severity_matched")) or expected_severity in observed_severities)
        and direct["severity_matched"],
        "publishable_output": int(retort.get("publishable_comment_count") or 0) > 0 and direct["publishable_output"],
        "direct_review_execution": direct["executed"],
    }
    return {
        "case_id": str(row.get("case_id") or ""),
        "source_project": str(row.get("source_project") or ""),
        "absorbed_signal": str(row.get("absorbed_signal") or ""),
        "baseline_score": baseline_score,
        "retort_score": retort_score,
        "behavior_delta": behavior_delta,
        "checks": checks,
        "direct_review_assertions": direct,
        "passed": all(checks.values()),
    }


def _direct_review_assertions(row: dict[str, Any], expected_context: str, expected_severity: str) -> dict[str, Any]:
    diff = str(row.get("diff") or "")
    if not diff.strip():
        return {
            "executed": False,
            "context_matched": False,
            "severity_matched": False,
            "publishable_output": False,
            "comment_count": 0,
            "observed_contexts": [],
            "observed_severities": [],
        }
    review = review_diff(diff, issue_context=str(row.get("external_advantage") or row.get("absorbed_signal") or ""), max_comments=8)
    comments = [item for item in review.get("comments") or [] if isinstance(item, dict)]
    summary = review.get("summary") if isinstance(review.get("summary"), dict) else {}
    extension_policy = summary.get("extension_policy") if isinstance(summary.get("extension_policy"), dict) else {}
    contexts = {str(item.get("review_context") or "") for item in comments if item.get("review_context")}
    contexts.update(str(item) for item in extension_policy.get("review_contexts") or [] if str(item))
    severities = {str(item.get("severity") or "") for item in comments if item.get("severity")}
    publishable_count = sum(1 for item in comments if item.get("publishable"))
    return {
        "executed": True,
        "context_matched": bool(expected_context) and expected_context in contexts,
        "severity_matched": bool(expected_severity) and expected_severity in severities,
        "publishable_output": publishable_count > 0,
        "comment_count": len(comments),
        "publishable_comment_count": publishable_count,
        "observed_contexts": sorted(contexts),
        "observed_severities": sorted(severities),
    }
