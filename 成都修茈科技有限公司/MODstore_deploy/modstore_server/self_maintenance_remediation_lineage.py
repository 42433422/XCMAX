"""Exact remediation selection and origin lineage for unattended loop retries."""

from __future__ import annotations

from typing import Any

_QA_ONLY_REASONS = frozenset(
    {
        "changed_files_match_forbidden_globs",
        "changed_files_outside_dynamic_low_risk_scope",
        "changed_files_outside_low_risk_globs",
        "missing_report_only_evidence",
        "max_retries_exceeded",
        "missing_structured_qa_result",
        "invalid_qa_verdict",
        "qa_blocking_findings_not_list",
        "qa_tested_commands_not_list",
        "qa_target_branch_available_not_bool",
        "structured_qa_executor_unavailable",
        "structured_qa_focused_command_not_passed",
        "structured_qa_target_branch_unavailable",
    }
)
_REVIEW_PROTOCOL_PREFIXES = (
    "blocking_findings_not_",
    "dimension_fail_without_",
    "dimension_fail_severity_",
    "dimension_findings_not_list_",
    "invalid_dimension_status_",
    "missing_dimension_",
    "tested_commands_not_",
    "target_branch_available_not_",
)
_REVIEW_ONLY_REASONS = frozenset(
    {
        "missing_structured_review_object",
        "missing_structured_review_result",
        "invalid_max_severity",
        "invalid_risk_class",
        "missing_dimensions",
    }
)
_CODE_REASONS = frozenset(
    {
        "para_merge_conflict",
        "para_merge_task_failed",
        "retort_scope_too_large",
        "structured_qa_blocking_findings",
        "structured_qa_black_not_passed",
        "structured_qa_isort_not_passed",
        "structured_qa_new_errors",
        "structured_qa_new_failures",
        "structured_qa_source_governance_not_passed",
        "structured_qa_verdict_not_pass",
    }
)


def _is_review_protocol_retry_reason(normalized: str) -> bool:
    if normalized in _REVIEW_ONLY_REASONS:
        return True
    return any(normalized.startswith(prefix) for prefix in _REVIEW_PROTOCOL_PREFIXES)


def normalize_automated_remediation_reason(
    memory: dict[str, Any],
    item: dict[str, Any],
) -> str:
    """Map legacy stored reasons to the executable hold token schedulers should use."""

    reason = str(item.get("reason") or "").strip()
    if reason != "structured_qa_verdict_not_pass":
        return reason
    branch = str(item.get("branch") or "").strip()
    if not branch:
        return reason
    decision = (
        memory.get("last_policy_decision")
        if isinstance(memory.get("last_policy_decision"), dict)
        else {}
    )
    if str(decision.get("reason") or "").strip() != "structured_qa_verdict_not_pass":
        return reason
    structured_gate = (
        decision.get("structured_gate") if isinstance(decision.get("structured_gate"), dict) else {}
    )
    qa = structured_gate.get("qa") if isinstance(structured_gate.get("qa"), dict) else {}
    if qa.get("target_branch_available") is not False:
        return reason
    blocking = qa.get("blocking_findings")
    if isinstance(blocking, list) and any(
        "target_branch_unavailable" in str(finding) and branch in str(finding)
        for finding in blocking
    ):
        return "structured_qa_target_branch_unavailable"
    return reason


def automated_remediation_resume_plan(reason: str) -> tuple[list[str], bool] | None:
    """Map durable hold reasons to downstream steps and branch pinning."""
    normalized = str(reason or "").strip()
    if normalized in _QA_ONLY_REASONS:
        return (["qa"], False)
    if _is_review_protocol_retry_reason(normalized):
        return (["review"], False)
    if normalized.startswith("structured_review_"):
        return (["code"], False)
    if normalized in _CODE_REASONS or normalized.startswith("structured_qa_new_"):
        return (["code"], True)
    return None


def resume_candidate_from_context(
    memory: dict[str, Any],
    remediation_context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Resolve the exact scheduler-selected repair instead of another backlog item."""
    if not isinstance(remediation_context, dict):
        return None
    run_id = str(remediation_context.get("run_id") or "").strip()
    branch = str(remediation_context.get("branch") or "").strip()
    para_task_id = str(remediation_context.get("task_id") or "").strip()
    if not run_id or not branch or not para_task_id:
        return None
    open_items = memory.get("open_items")
    if not isinstance(open_items, list):
        return None
    matched_item: dict[str, Any] | None = None
    for item in reversed(open_items):
        if not isinstance(item, dict) or item.get("escalated"):
            continue
        item_task_id = str(item.get("task_id") or item.get("para_task_id") or "").strip()
        if (
            str(item.get("run_id") or "").strip() == run_id
            and str(item.get("branch") or "").strip() == branch
            and item_task_id == para_task_id
        ):
            matched_item = item
            break
    if matched_item is None:
        return None

    reason = normalize_automated_remediation_reason(memory, matched_item)
    if not reason:
        reason = str(remediation_context.get("reason") or "").strip()
    raw_steps = remediation_context.get("steps")
    failed_steps = (
        [str(step) for step in raw_steps if str(step) in {"code", "review", "qa"}]
        if isinstance(raw_steps, list)
        else []
    )
    continue_existing_code_task = False
    candidate_reason = "resume_failed_review_or_qa"
    if not failed_steps:
        if reason == "para_ai_review_rejected":
            failed_steps = ["code"]
            candidate_reason = "resume_para_ai_review_rejection"
        elif reason in {
            "auto_merge_safety_score_v2_too_low",
            "auto_merge_safety_score_v3_too_low",
            "risk_score_v3_below_threshold_or_blocked",
        }:
            failed_steps = ["code"]
            continue_existing_code_task = True
            candidate_reason = "resume_safety_score_remediation"
        else:
            resume_plan = automated_remediation_resume_plan(reason)
            if resume_plan is None:
                return None
            failed_steps, continue_existing_code_task = resume_plan
            candidate_reason = "resume_automated_remediation_candidate"

    candidate: dict[str, Any] = {
        "branch": branch,
        "failed_run_id": run_id,
        "failed_steps": list(failed_steps),
        "para_task_id": para_task_id,
        "reason": candidate_reason,
    }
    if continue_existing_code_task:
        if reason.startswith("para_merge_"):
            from modstore_server.self_maintenance_para_merge_remediation import (
                para_merge_resume_pins_rejected_branch,
            )

            if para_merge_resume_pins_rejected_branch(matched_item):
                candidate["continue_existing_code_task"] = True
        elif not matched_item.get("resume_from_clean_baseline"):
            candidate["continue_existing_code_task"] = True
    if reason == "para_ai_review_rejected":
        candidate["rejected_branch"] = branch
        candidate["review_feedback"] = str(
            matched_item.get("review_feedback") or matched_item.get("detail") or ""
        )[:4000]
    elif reason.startswith("para_merge_") or reason == "retort_scope_too_large":
        candidate["remediation_feedback"] = str(matched_item.get("detail") or "")[:4000]
        candidate["remediation_reason"] = reason
    for key in ("origin_run_id", "origin_triggered_by", "origin_reason"):
        value = str(remediation_context.get(key) or "").strip()
        if value:
            candidate[key] = value
    return candidate


def remediation_lineage_fields(
    remediation_context: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(remediation_context, dict):
        return {}
    fields: dict[str, Any] = {}
    parent_run_id = str(remediation_context.get("run_id") or "").strip()
    if parent_run_id:
        fields["parent_run_id"] = parent_run_id
    for key in ("origin_run_id", "origin_triggered_by", "origin_reason"):
        value = str(remediation_context.get(key) or "").strip()
        if value:
            fields[key] = value
    origin = str(fields.get("origin_triggered_by") or "")
    if origin == "incident_event":
        fields["event"] = "incident_remediation"
    elif origin == "proactive_signal":
        fields["event"] = "proactive_evolution_remediation"
    return fields


def unavailable_context_record(
    *,
    created_at: str,
    force: bool,
    gate: dict[str, Any],
    remediation_context: dict[str, Any],
    run_id: str,
    triggered_by: str,
) -> dict[str, Any]:
    return {
        "created_at": created_at,
        "force": force,
        "gate": gate,
        "phase": "skip",
        "reason": "selected remediation context is no longer executable",
        "run_id": run_id,
        "status": "skipped_remediation_context_unavailable",
        "triggered_by": triggered_by,
        **remediation_lineage_fields(remediation_context),
    }


__all__ = [
    "automated_remediation_resume_plan",
    "normalize_automated_remediation_reason",
    "remediation_lineage_fields",
    "resume_candidate_from_context",
    "unavailable_context_record",
]
