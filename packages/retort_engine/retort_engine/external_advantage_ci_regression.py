from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from retort_engine.external_advantage_matrix import build_external_advantage_matrix


def build_external_advantage_ci_regression(
    project: str | Path,
    *,
    min_cases: int = 6,
    min_blind_delta: int = 80,
    output: str | Path = "",
) -> dict[str, Any]:
    """Build the CI-grade regression proof for absorbed external advantages."""
    root = Path(project).expanduser().resolve()
    started = time.monotonic()
    matrix = build_external_advantage_matrix(root, min_cases=min_cases)
    summary = matrix.get("summary") if isinstance(matrix.get("summary"), dict) else {}
    rows = [row for row in matrix.get("matrix") or [] if isinstance(row, dict)]
    regression_cases = [_case_regression(row, min_blind_delta=min_blind_delta) for row in rows]
    passed_cases = [case for case in regression_cases if case["passed"]]
    source_projects = sorted({str(row.get("source_project") or "") for row in rows if row.get("source_project")})
    result_summary = {
        "case_count": len(regression_cases),
        "min_case_count": min_cases,
        "passed_case_count": len(passed_cases),
        "source_project_count": len(source_projects),
        "source_projects": source_projects,
        "matrix_status": matrix.get("status", ""),
        "matrix_ready_cases": summary.get("ready_case_count", 0),
        "matrix_case_count": summary.get("case_count", 0),
        "matrix_score_delta": summary.get("score_delta", 0),
        "blind_third_party_minimum_delta": summary.get("blind_third_party_minimum_delta", 0),
        "blind_delta_floor": min_blind_delta,
        "blind_delta_floor_met": int(summary.get("blind_third_party_minimum_delta") or 0) >= min_blind_delta,
        "blind_score_fields_consumed": summary.get("blind_third_party_score_fields_consumed", True),
        "all_direct_review_regressions_verified": summary.get("all_delta_regressions_verified") is True,
        "all_cases_have_ci_acceptance": bool(regression_cases) and len(passed_cases) == len(regression_cases),
        "ci_command": "retort external-advantage-ci-regression --project <project>",
        "duration_sec": round(time.monotonic() - started, 3),
    }
    ready = (
        matrix.get("status") == "ready"
        and result_summary["case_count"] >= min_cases
        and result_summary["passed_case_count"] == result_summary["case_count"]
        and result_summary["source_project_count"] >= min_cases
        and result_summary["blind_delta_floor_met"]
        and result_summary["blind_score_fields_consumed"] is False
        and result_summary["all_direct_review_regressions_verified"]
    )
    result = {
        "status": "ready" if ready else "needs_ci_regression_evidence",
        "project": str(root),
        "summary": result_summary,
        "cases": regression_cases,
        "evidence": {
            "style": "ci_replayed_external_advantage_delta_gate",
            "source": "retort_engine.external_advantage_matrix.build_external_advantage_matrix",
            "review_runtime": "retort_engine.pr_review.review_diff",
            "blind_adjudicator": "retort_engine.external_advantage_adjudicator.blind_third_party_adjudicate_external_advantages",
            "ci_gate": "all_cases_direct_replay_and_blind_delta_at_or_above_80",
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _case_regression(row: dict[str, Any], *, min_blind_delta: int) -> dict[str, Any]:
    retort = row.get("retort") if isinstance(row.get("retort"), dict) else {}
    checks = {
        "ready": row.get("ready") is True,
        "positive_behavior_delta": int(row.get("behavior_delta") or 0) > 0,
        "direct_context_matched": retort.get("context_matched") is True,
        "direct_severity_matched": retort.get("severity_matched") is True,
        "publishable_comment": int(retort.get("publishable_comment_count") or 0) > 0,
        "task_group_materialized": int(retort.get("task_group_count") or 0) > 0,
        "extension_policy_applied": int(retort.get("extension_policy_known_count") or 0) > 0,
    }
    return {
        "case_id": str(row.get("case_id") or ""),
        "source_project": str(row.get("source_project") or ""),
        "absorbed_signal": str(row.get("absorbed_signal") or ""),
        "behavior_delta": int(row.get("behavior_delta") or 0),
        "minimum_blind_delta_required": min_blind_delta,
        "checks": checks,
        "passed": all(checks.values()),
    }
