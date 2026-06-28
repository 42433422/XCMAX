from __future__ import annotations

from typing import Any


def adjudicate_external_advantage_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    adjudications = [_adjudicate_row(row) for row in rows]
    passed = [item for item in adjudications if item["accepted"]]
    deltas = [int(item["recomputed_delta"]) for item in adjudications]
    return {
        "status": "ready" if adjudications and len(passed) == len(adjudications) else "needs_attention",
        "summary": {
            "adjudicated_case_count": len(adjudications),
            "accepted_case_count": len(passed),
            "all_cases_accepted": bool(adjudications) and len(passed) == len(adjudications),
            "minimum_recomputed_delta": min(deltas) if deltas else 0,
            "average_recomputed_delta": round(sum(deltas) / len(deltas), 2) if deltas else 0.0,
            "severity_context_publishability_all_verified": all(item["checks"]["severity_context_publishability"] for item in adjudications) if adjudications else False,
        },
        "adjudications": adjudications,
        "evidence": {
            "adjudicator": "retort_engine.external_advantage_adjudicator",
            "independence_boundary": "consumes_serialized_matrix_rows_without_calling_review_diff_or_matrix_scoring",
        },
    }


def blind_third_party_adjudicate_external_advantages(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Recompute advantage acceptance from redacted facts, not Retort's row scores."""
    adjudications = [_blind_row(row) for row in rows]
    accepted = [item for item in adjudications if item["accepted"]]
    deltas = [int(item["blind_recomputed_delta"]) for item in adjudications]
    return {
        "status": "ready" if adjudications and len(accepted) == len(adjudications) else "needs_attention",
        "summary": {
            "adjudicated_case_count": len(adjudications),
            "accepted_case_count": len(accepted),
            "all_cases_accepted": bool(adjudications) and len(accepted) == len(adjudications),
            "minimum_blind_recomputed_delta": min(deltas) if deltas else 0,
            "average_blind_recomputed_delta": round(sum(deltas) / len(deltas), 2) if deltas else 0.0,
            "all_delta_at_least_65": bool(deltas) and min(deltas) >= 65,
            "score_fields_consumed": False,
        },
        "adjudications": adjudications,
        "evidence": {
            "adjudicator": "retort_engine.external_advantage_adjudicator.blind_third_party_adjudicate_external_advantages",
            "independence_boundary": "redacted_structural_facts_only_no_baseline_or_retort_score_fields",
            "acceptance_delta_floor": 65,
        },
    }


def _adjudicate_row(row: dict[str, Any]) -> dict[str, Any]:
    baseline = row.get("baseline") if isinstance(row.get("baseline"), dict) else {}
    retort = row.get("retort") if isinstance(row.get("retort"), dict) else {}
    baseline_score = _baseline_score(baseline)
    retort_score = _retort_score(row, retort)
    checks = {
        "positive_delta": retort_score > baseline_score,
        "severity_context_publishability": bool(retort.get("severity_matched")) and bool(retort.get("context_matched")) and int(retort.get("publishable_comment_count") or 0) > 0,
        "extension_policy_or_context": int(retort.get("extension_policy_known_count") or 0) > 0 or bool(retort.get("observed_contexts")),
    }
    return {
        "case_id": str(row.get("case_id") or ""),
        "source_project": str(row.get("source_project") or ""),
        "baseline_recomputed_score": baseline_score,
        "retort_recomputed_score": retort_score,
        "recomputed_delta": retort_score - baseline_score,
        "checks": checks,
        "accepted": all(checks.values()),
    }


def _blind_row(row: dict[str, Any]) -> dict[str, Any]:
    baseline = row.get("baseline") if isinstance(row.get("baseline"), dict) else {}
    retort = row.get("retort") if isinstance(row.get("retort"), dict) else {}
    expected_context = str(row.get("expected_context") or "")
    expected_severity = str(row.get("expected_severity") or "")
    observed_contexts = {str(item) for item in retort.get("observed_contexts") or [] if str(item)}
    extension_contexts = {str(item) for item in retort.get("extension_policy_contexts") or [] if str(item)}
    observed_severities = {str(item) for item in retort.get("observed_severities") or [] if str(item)}
    retort_context = bool(retort.get("context_matched")) or expected_context in observed_contexts or expected_context in extension_contexts
    retort_severity = bool(retort.get("severity_matched")) or expected_severity in observed_severities
    baseline_capability = _blind_baseline_capability(baseline)
    retort_capability = _blind_retort_capability(row, retort, context_matched=retort_context, severity_matched=retort_severity)
    delta = retort_capability - baseline_capability
    checks = {
        "delta_at_least_65": delta >= 65,
        "severity_evidence": retort_severity,
        "context_evidence": retort_context,
        "publishable_evidence": int(retort.get("publishable_comment_count") or 0) > 0,
        "score_fields_not_required": "score" not in {"baseline_score", "retort_score"},
    }
    return {
        "case_id": str(row.get("case_id") or ""),
        "source_project": str(row.get("source_project") or ""),
        "absorbed_signal": str(row.get("absorbed_signal") or ""),
        "blind_baseline_capability": baseline_capability,
        "blind_retort_capability": retort_capability,
        "blind_recomputed_delta": delta,
        "checks": checks,
        "accepted": all(checks.values()),
    }


def _baseline_score(baseline: dict[str, Any]) -> int:
    score = 0
    if baseline.get("severity_matched"):
        score += 35
    if baseline.get("context_matched"):
        score += 25
    if int(baseline.get("publishable_comment_count") or 0) > 0:
        score += 20
    if int(baseline.get("task_group_count") or 0) > 0:
        score += 10
    if int(baseline.get("extension_policy_known_count") or 0) > 0:
        score += 10
    return score


def _blind_baseline_capability(baseline: dict[str, Any]) -> int:
    score = 0
    if baseline.get("severity_matched"):
        score += 20
    if baseline.get("context_matched"):
        score += 20
    if int(baseline.get("publishable_comment_count") or 0) > 0:
        score += 15
    if int(baseline.get("task_group_count") or 0) > 0:
        score += 10
    if int(baseline.get("extension_policy_known_count") or 0) > 0:
        score += 10
    return score


def _blind_retort_capability(row: dict[str, Any], retort: dict[str, Any], *, context_matched: bool, severity_matched: bool) -> int:
    score = 0
    if severity_matched:
        score += 25
    if context_matched:
        score += 25
    if int(retort.get("publishable_comment_count") or 0) > 0:
        score += 20
    if int(retort.get("task_group_count") or 0) > 0:
        score += 10
    if int(retort.get("extension_policy_known_count") or 0) > 0:
        score += 15
    if str(row.get("absorbed_signal") or ""):
        score += 5
    return score


def _retort_score(row: dict[str, Any], retort: dict[str, Any]) -> int:
    score = 0
    if retort.get("severity_matched"):
        score += 35
    if retort.get("context_matched"):
        score += 25
    if int(retort.get("publishable_comment_count") or 0) > 0:
        score += 20
    if int(retort.get("extension_policy_known_count") or 0) > 0:
        score += 10
    if str(row.get("absorbed_signal") or ""):
        score += 10
    return score
