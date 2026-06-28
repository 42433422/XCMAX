from __future__ import annotations

from typing import Any


def verify_external_advantage_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    cases = [_verify_row(row) for row in rows]
    passed = [case for case in cases if case["passed"]]
    return {
        "status": "ready" if cases and len(passed) == len(cases) else "needs_attention",
        "summary": {
            "regression_case_count": len(cases),
            "passed_regression_case_count": len(passed),
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
            "model": "same_rows_replayed_as_behavior_regression_contract",
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
    checks = {
        "before_after_scores": retort_score > baseline_score >= 0,
        "positive_delta": behavior_delta == retort_score - baseline_score and behavior_delta > 0,
        "expected_context": bool(expected_context) and (bool(retort.get("context_matched")) or expected_context in observed_contexts),
        "expected_severity": bool(expected_severity) and (bool(retort.get("severity_matched")) or expected_severity in observed_severities),
        "publishable_output": int(retort.get("publishable_comment_count") or 0) > 0,
    }
    return {
        "case_id": str(row.get("case_id") or ""),
        "source_project": str(row.get("source_project") or ""),
        "absorbed_signal": str(row.get("absorbed_signal") or ""),
        "baseline_score": baseline_score,
        "retort_score": retort_score,
        "behavior_delta": behavior_delta,
        "checks": checks,
        "passed": all(checks.values()),
    }
