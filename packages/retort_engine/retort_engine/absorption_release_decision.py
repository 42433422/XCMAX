from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_absorption_release_decision(project: str | Path, *, output: str | Path = "") -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    quality = _read_json(root / "docs" / "retort_quality_gate_bundle.json")
    continuity = _read_json(root / "docs" / "retort_absorption_continuity_probe.json")
    long_run = _read_json(root / "docs" / "retort_pr_long_run_review.json")
    holdout = _read_json(root / "docs" / "retort_pr_holdout_blind_eval.json")
    failure_rollback = _read_json(root / "docs" / "retort_pr_failure_rollback_replay.json")
    recovery = _read_json(root / "docs" / "retort_production_recovery_drill.json")
    patch = _read_json(root / "docs" / "retort_employee_patch_closure.json")
    benchmark = _read_json(root / "docs" / "retort_review_quality_benchmark.json")
    decisions = [
        _decision(
            "run_absorption",
            "absorption_depth",
            quality.get("summary", {}).get("all_gates_passed") is True and continuity.get("status") == "ready",
            ["quality_gate_bundle", "absorption_continuity_probe"],
        ),
        _decision(
            "dispatch_employee_patch",
            "employee_execution",
            patch.get("status") == "ready" and patch.get("summary", {}).get("all_expected_outcomes_verified") is True,
            ["employee_patch_closure"],
        ),
        _decision(
            "publish_or_degrade_review",
            "product_operability",
            long_run.get("status") == "ready" and recovery.get("status") == "ready",
            ["pr_long_run_review", "production_recovery_drill"],
        ),
        _decision(
            "claim_absorbed_quality_gain",
            "feedback_loop_closure",
            benchmark.get("status") == "ready" and int(benchmark.get("summary", {}).get("post_absorption_score_delta") or 0) > 0,
            ["review_quality_benchmark"],
        ),
        _decision(
            "accept_blind_holdout_quality",
            "blind_external_validation",
            holdout.get("status") == "ready" and int(holdout.get("summary", {}).get("accepted_pr_count") or 0) >= int(holdout.get("summary", {}).get("target_pr_count") or 20),
            ["pr_holdout_blind_eval"],
        ),
        _decision(
            "allow_failure_rollback_replay",
            "failure_recovery_validation",
            failure_rollback.get("status") == "ready" and bool(failure_rollback.get("summary", {}).get("all_failures_rolled_back")),
            ["pr_failure_rollback_replay"],
        ),
    ]
    ready = [item for item in decisions if item["ready"]]
    blockers = [item for item in decisions if not item["ready"]]
    summary = {
        "decision_count": len(decisions),
        "ready_decision_count": len(ready),
        "blocking_decision_count": len(blockers),
        "core_decision_path_count": len({item["dimension"] for item in decisions}),
        "all_core_decisions_ready": len(blockers) == 0,
        "quality_gate_all_passed": quality.get("summary", {}).get("all_gates_passed") is True,
        "long_run_ready": long_run.get("status") == "ready",
        "recovery_ready": recovery.get("status") == "ready",
        "employee_patch_ready": patch.get("status") == "ready",
        "holdout_blind_eval_ready": holdout.get("status") == "ready",
        "failure_rollback_ready": failure_rollback.get("status") == "ready",
    }
    result = {
        "status": "ready" if summary["all_core_decisions_ready"] else "blocked",
        "project": str(root),
        "summary": summary,
        "decisions": decisions,
        "evidence": {
            "style": "core_product_decision_gate",
            "source_reports": [
                "retort_quality_gate_bundle.json",
                "retort_absorption_continuity_probe.json",
                "retort_pr_long_run_review.json",
                "retort_pr_holdout_blind_eval.json",
                "retort_pr_failure_rollback_replay.json",
                "retort_production_recovery_drill.json",
                "retort_employee_patch_closure.json",
                "retort_review_quality_benchmark.json",
            ],
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _decision(name: str, dimension: str, ready: bool, evidence: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "dimension": dimension,
        "ready": ready,
        "evidence": evidence,
        "action": "allow" if ready else "block",
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
