from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BASE_CONTEXT_WEIGHTS = {
    "security": 35,
    "runtime": 25,
    "tests": 30,
    "ci_config": 25,
    "config": 15,
    "frontend": 10,
    "docs": 10,
    "other": 0,
}


def build_review_calibration_policy(project: str | Path | None = None) -> dict[str, Any]:
    root = Path(project).expanduser().resolve() if project else Path(__file__).resolve().parents[1]
    docs = root / "docs"
    holdout = _read_json(docs / "retort_pr_holdout_blind_eval.json")
    adjudication = _read_json(docs / "retort_review_adjudication_calibration.json")
    rollback = _read_json(docs / "retort_pr_failure_rollback_replay.json")
    holdout_summary = holdout.get("summary") if isinstance(holdout.get("summary"), dict) else {}
    adjudication_summary = adjudication.get("summary") if isinstance(adjudication.get("summary"), dict) else {}
    rollback_summary = rollback.get("summary") if isinstance(rollback.get("summary"), dict) else {}
    holdout_ready = holdout.get("status") == "ready" and bool(holdout_summary.get("blind_against_prior_reports"))
    adjudication_ready = adjudication.get("status") == "ready" and float(adjudication_summary.get("pass_rate") or 0.0) >= 0.95
    rollback_ready = rollback.get("status") == "ready" and bool(rollback_summary.get("all_failures_rolled_back"))
    enabled = holdout_ready and adjudication_ready and rollback_ready
    weights = dict(BASE_CONTEXT_WEIGHTS) if enabled else {context: 0 for context in BASE_CONTEXT_WEIGHTS}
    if enabled and int(rollback_summary.get("rollback_verified_count") or 0) >= 3:
        weights["ci_config"] += 15
        weights["config"] += 10
    if enabled and int(holdout_summary.get("distinct_extension_count") or 0) >= 8:
        weights["runtime"] += 10
        weights["tests"] += 10
    return {
        "enabled": enabled,
        "weights": weights,
        "summary": {
            "holdout_ready": holdout_ready,
            "adjudication_ready": adjudication_ready,
            "rollback_ready": rollback_ready,
            "holdout_reviewed_pr_count": int(holdout_summary.get("reviewed_pr_count") or 0),
            "holdout_distinct_repo_count": int(holdout_summary.get("distinct_repo_count") or 0),
            "adjudication_pass_rate": float(adjudication_summary.get("pass_rate") or 0.0),
            "rollback_verified_count": int(rollback_summary.get("rollback_verified_count") or 0),
        },
        "evidence": {
            "source_reports": [
                "retort_pr_holdout_blind_eval.json",
                "retort_review_adjudication_calibration.json",
                "retort_pr_failure_rollback_replay.json",
            ],
            "behavior": "calibration_reports_directly_adjust_review_rank_score_and_publish_order",
        },
    }


def calibration_context_rank_weight(review_context: str) -> int:
    policy = build_review_calibration_policy()
    weights = policy.get("weights") if isinstance(policy.get("weights"), dict) else {}
    return int(weights.get(str(review_context or "other"), 0) or 0)


def calibration_context_rank_weights() -> dict[str, int]:
    policy = build_review_calibration_policy()
    weights = policy.get("weights") if isinstance(policy.get("weights"), dict) else {}
    return {context: int(weights.get(context, 0) or 0) for context in BASE_CONTEXT_WEIGHTS}


def calibration_summary() -> dict[str, Any]:
    policy = build_review_calibration_policy()
    weights = policy.get("weights") if isinstance(policy.get("weights"), dict) else {}
    return {
        "enabled": bool(policy.get("enabled")),
        "weighted_context_count": sum(1 for value in weights.values() if int(value or 0) > 0),
        "max_context_weight": max([int(value or 0) for value in weights.values()] or [0]),
        **(policy.get("summary") if isinstance(policy.get("summary"), dict) else {}),
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
