"""Pure completion decisions from durable business and model-usage receipts."""

from __future__ import annotations

import copy
from typing import Any, Literal

from app.domain.task_lifecycle.agent_runtime_contract import goal_report_coverage
from app.domain.task_lifecycle.results import execution_result_outcome_unknown

ClassifiedRunStatus = Literal["blocked", "waiting_user", "running", "failed", "completed"]
WAITING_STATES = frozenset({"waiting_user", "waiting_approval", "pending_approval", "waiting_auth"})
ACTIVE_STATES = frozenset({"queued", "planning", "running", "retrying", "submitted", "accepted"})


def base_runtime_result(run_id: str) -> dict[str, Any]:
    return {
        "handler": "agent",
        "runtime": "codex",
        "run_id": run_id,
        "ok": False,
        "business_completed": False,
        "verified_operations": False,
        "runtime_completed": False,
        "output": "",
        "rounds": 0,
        "tool_calls": [],
        "trajectory": [],
        "session_messages": [],
        "run_events": [],
        "retryable": False,
        "legacy_fallback_allowed": False,
    }


def withhold_runtime_output(result: dict[str, Any], *, status: str, error: str) -> None:
    """Keep reviewed evidence, but retract an apparent success rejected by the host."""
    result.update(
        ok=False,
        business_completed=False,
        reply_completed=False,
        exit_status=status,
        execution_state=status,
        error=error,
        output="本轮结果未通过核验，未发布正文。",
        session_messages=[
            message for message in result.get("session_messages", []) if message["role"] == "user"
        ],
    )


def receipt_state(row: dict[str, Any]) -> str:
    receipt = row.get("receipt") or {}
    if execution_result_outcome_unknown(receipt) or row.get("state") in {"claimed", "unknown"}:
        return "unknown"
    return str(receipt.get("status") or row.get("state") or "unknown")


def model_unsettled(metadata: dict[str, Any]) -> bool:
    return bool(metadata.get("model_reconciliation_required")) or any(
        isinstance(request, dict) and request.get("state") in {"reserved", "unknown"}
        for request in (metadata.get("model_requests") or {}).values()
    )


def classify_runtime_result(
    result: dict[str, Any],
    rows: list[dict[str, Any]],
    metadata: dict[str, Any],
    completion_mode: str,
    runtime_status: str,
) -> ClassifiedRunStatus:
    """Return the parent state using durable receipts, not model wording."""
    result.update(
        ok=False, business_completed=False, verified_operations=False, reply_completed=False
    )
    result["business_receipts"] = copy.deepcopy(rows)
    result["tool_calls"] = [
        {
            "tool": f"{row.get('tool_id', '')}.{row.get('action', '')}",
            "action_id": row.get("call_id"),
            "args": row.get("params") or {},
            "run_id": row.get("child_run_id"),
            "task_id": row.get("child_task_id"),
            "success": receipt_state(row) == "completed"
            and (row.get("receipt") or {}).get("success") is True,
            "verified": (row.get("receipt") or {}).get("verified") is True,
            "execution_state": receipt_state(row),
        }
        for row in rows
    ]
    states = {receipt_state(row) for row in rows}
    if "unknown" in states or model_unsettled(metadata):
        result.update(
            exit_status="unknown",
            execution_state="unknown",
            reconciliation_required=True,
            error="执行或模型计量结果尚未确定，请核对原任务回执",
            output="执行或模型计量结果尚未确定，请核对原任务回执。",
        )
        return "blocked"
    if states & WAITING_STATES:
        waiting = [row.get("receipt") or {} for row in rows if receipt_state(row) in WAITING_STATES]
        clarification = next(
            (
                receipt["clarification"]
                for receipt in waiting
                if receipt.get("needs_user_input") is True
                and isinstance(receipt.get("clarification"), dict)
            ),
            None,
        )
        result.update(
            exit_status="waiting_user",
            execution_state="waiting_user",
            pending_approval=any(
                receipt.get("pending_approval", not receipt.get("needs_user_input"))
                for receipt in waiting
            ),
            output="业务任务正在等待审批或授权，尚未完成。",
        )
        if clarification is not None:
            question = str(clarification.get("question") or "请补充原任务信息")
            result.update(
                needs_user_input=True,
                clarification=copy.deepcopy(clarification),
                clarification_question=question,
                output=question,
            )
        return "waiting_user"
    if states & ACTIVE_STATES:
        result.update(
            exit_status="running", execution_state="running", output="业务任务仍在执行，尚未完成。"
        )
        return "running"
    if metadata.get("waiting_input"):
        question = str((metadata.get("waiting_input") or {}).get("question") or "请补充任务信息")
        result.update(
            exit_status="waiting_user",
            execution_state="waiting_user",
            needs_user_input=True,
            clarification_question=question,
            output=question,
        )
        return "waiting_user"
    verified_rows = [
        row
        for row in rows
        if receipt_state(row) == "completed"
        and (row.get("receipt") or {}).get("success") is True
        and (row.get("receipt") or {}).get("verified") is True
    ]
    report = metadata.get("goal_verification")
    if not isinstance(report, dict):
        report = {}
    reviewed_output = str(result.get("goal_response", result.get("output")) or "")
    coverage = goal_report_coverage(
        metadata.get("goal_contract"),
        rows,
        reviewed_output,
        metadata.get("goal_answers"),
        report,
    )
    result["goal_coverage"] = coverage
    result["verified_operations"] = bool(verified_rows) and all(
        (row.get("receipt") or {}).get("success") is not True or row in verified_rows
        for row in rows
    )
    mode = str(coverage["mode"])
    if runtime_status != "completed" and (
        not coverage["completed"] or mode == "reply" or runtime_status in {"cancelled", "paused"}
    ):
        result.update(
            exit_status=runtime_status or "failed",
            execution_state="failed",
            runtime_status=runtime_status,
            runtime_completed=False,
            error=result.get("error") or "本轮运行尚未完成，未确认任务完成",
            output="本轮运行尚未完成，未确认任务完成。",
        )
        return "failed"
    if not coverage["completed"]:
        feedback = str((report or {}).get("feedback") or "原始目标仍需逐项核对。")
        result.update(
            exit_status="goal_verification_required",
            execution_state="blocked",
            error="已执行动作不等于整体目标完成，原任务目标仍需核对",
            output="本轮未通过完整性核验，原任务与回执已保留，请核对后重试。",
            goal_response=reviewed_output,
            verification_feedback=feedback,
            retryable=isinstance(report, dict)
            and report.get("status") in {"needs_work", "unavailable"},
        )
        return "blocked"
    if mode == "reply" and not reviewed_output.strip():
        result.update(
            exit_status="empty_reply",
            execution_state="failed",
            error="模型轮次没有返回可交付的回复",
            output="本轮未返回可交付的回复。",
            runtime_status=runtime_status,
            runtime_completed=True,
        )
        return "failed"
    result["goal_response"] = reviewed_output
    if mode == "business" and (runtime_status != "completed" or not reviewed_output.strip()):
        result.update(
            output=f"已按原任务回执逐项核验全部 {coverage['required']} 项目标，业务任务已完成。",
            runtime_error=result.pop("error", ""),
            runtime_error_code=result.pop("error_code", ""),
        )
    result.update(
        ok=True,
        exit_status="completed" if mode == "business" else "reply_completed",
        execution_state="completed",
        business_completed=mode == "business",
        reply_completed=mode == "reply",
        runtime_status=runtime_status,
        runtime_completed=runtime_status == "completed",
    )
    return "completed"
