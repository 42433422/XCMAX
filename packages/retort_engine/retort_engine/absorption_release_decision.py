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
    external_matrix = _read_json(root / "docs" / "retort_external_advantage_matrix.json")
    external_repeat = _read_json(root / "docs" / "retort_external_advantage_repeat.json")
    heterogeneous_replay = _read_json(root / "docs" / "retort_heterogeneous_absorption_replay.json")
    cross_domain_replay = _read_json(root / "docs" / "retort_cross_domain_absorption_replay.json")
    external_merge_landing = _read_json(root / "docs" / "retort_external_merge_landing.json")
    operator_journey = _read_json(root / "docs" / "retort_operator_journey_replay.json")
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
            "prove_external_advantage_matrix",
            "comparative_analysis_depth",
            external_matrix.get("status") == "ready" and int(external_matrix.get("summary", {}).get("score_delta") or 0) > 0,
            ["external_advantage_matrix"],
        ),
        _decision(
            "prove_repeatable_external_advantage",
            "comparative_analysis_depth",
            external_repeat.get("status") == "ready"
            and external_repeat.get("summary", {}).get("stable_case_set") is True
            and external_repeat.get("summary", {}).get("stable_score_delta") is True,
            ["external_advantage_repeat"],
        ),
        _decision(
            "prove_heterogeneous_absorption",
            "cross_language_absorption",
            heterogeneous_replay.get("status") == "ready"
            and heterogeneous_replay.get("summary", {}).get("all_before_failed_after_passed") is True
            and heterogeneous_replay.get("summary", {}).get("cross_language_absorption_verified") is True,
            ["heterogeneous_absorption_replay"],
        ),
        _decision(
            "prove_non_pr_cross_domain_absorption",
            "cross_domain_absorption",
            cross_domain_replay.get("status") == "ready"
            and cross_domain_replay.get("summary", {}).get("all_before_failed_after_passed") is True
            and cross_domain_replay.get("summary", {}).get("all_output_assertions_passed") is True
            and int(cross_domain_replay.get("summary", {}).get("non_pr_domain_count") or 0) >= 4,
            ["cross_domain_absorption_replay"],
        ),
        _decision(
            "prove_external_merge_landing",
            "branch_absorption_workflow",
            external_merge_landing.get("status") == "ready"
            and external_merge_landing.get("summary", {}).get("all_branch_diff_merge_tests_passed") is True
            and int(external_merge_landing.get("summary", {}).get("merge_commit_count") or 0) >= 2,
            ["external_merge_landing"],
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
        _decision(
            "replay_operator_absorption_journey",
            "product_operability",
            operator_journey.get("status") == "ready" and bool(operator_journey.get("summary", {}).get("cross_domain_live_probe_ready")),
            ["operator_journey_replay"],
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
        "external_advantage_matrix_ready": external_matrix.get("status") == "ready",
        "external_advantage_matrix_delta": external_matrix.get("summary", {}).get("score_delta", ""),
        "external_advantage_repeat_ready": external_repeat.get("status") == "ready",
        "external_advantage_repeat_total_cases": external_repeat.get("summary", {}).get("total_case_evaluation_count", ""),
        "heterogeneous_absorption_ready": heterogeneous_replay.get("status") == "ready",
        "heterogeneous_absorption_languages": heterogeneous_replay.get("summary", {}).get("language_family_count", ""),
        "heterogeneous_absorption_before_after": heterogeneous_replay.get("summary", {}).get("all_before_failed_after_passed", ""),
        "cross_domain_absorption_ready": cross_domain_replay.get("status") == "ready",
        "cross_domain_absorption_domains": cross_domain_replay.get("summary", {}).get("non_pr_domain_count", ""),
        "cross_domain_absorption_direct_modules": cross_domain_replay.get("summary", {}).get("direct_module_count", ""),
        "cross_domain_absorption_output_assertions": cross_domain_replay.get("summary", {}).get("all_output_assertions_passed", ""),
        "external_merge_landing_ready": external_merge_landing.get("status") == "ready",
        "external_merge_landing_merge_commits": external_merge_landing.get("summary", {}).get("merge_commit_count", ""),
        "external_merge_landing_post_merge_tests": external_merge_landing.get("summary", {}).get("post_merge_test_passed_count", ""),
        "failure_rollback_ready": failure_rollback.get("status") == "ready",
        "operator_journey_ready": operator_journey.get("status") == "ready",
        "operator_journey_cross_domain_ready": bool(operator_journey.get("summary", {}).get("cross_domain_live_probe_ready")),
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
                "retort_external_advantage_matrix.json",
                "retort_external_advantage_repeat.json",
                "retort_heterogeneous_absorption_replay.json",
                "retort_cross_domain_absorption_replay.json",
                "retort_external_merge_landing.json",
                "retort_operator_journey_replay.json",
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
