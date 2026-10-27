"""Apply approval outcomes only to the precisely matching actor, task and pending tool call."""

from __future__ import annotations

from typing import Any

from app.application.workflow.workflow_types import WorkflowRunResult

from .run_models import AgentRun
from .run_repository import AgentRunRepository
from .trace_artifacts import _append_artifacts_to_final_output, _extract_artifacts
from .trace_payloads import _resolved_user_id
from .trace_recording import TraceRecorder


def resolve_legacy_approval(
    request_id: str,
    context: dict[str, Any],
    result: WorkflowRunResult | None = None,
    *,
    repository: AgentRunRepository,
    recording: TraceRecorder,
    run_before_restore: AgentRun | None = None,
) -> str:
    """记录已执行审批的真实结果；仅更新同账号/租户/Mod且精确匹配审批的观察任务。"""
    from app.application.agent_orchestrator.unified_task import (
        UnifiedTaskConflictError,
        _assert_reused_run_scope,
    )

    run_id = str(context.get("agent_run_id") or "")
    if not run_id:
        return ""
    repo = repository
    run = repo.get(run_id) or run_before_restore
    if (
        run is None
        or run.run_id != run_id
        or run.intent not in {"legacy_chat_adapter", "legacy_tool_chain"}
        or run.status != "waiting_user"
    ):
        return ""
    try:
        _assert_reused_run_scope(
            run,
            user_id=_resolved_user_id(runtime_context=context, user_id=None),
            tenant_id=str(context.get("tenant_id") or ""),
            runtime_context=context,
        )
    except UnifiedTaskConflictError:
        return ""
    original = run.metadata.get("runtime_context") or {}
    if any(
        str(original.get(key) or "") != str(context.get(key) or "")
        for key in (
            "task_id",
            "session_id",
            "conversation_id",
            "turn_id",
        )
    ):
        return ""
    calls = [
        call
        for call in run.tool_calls
        if call.output.get("pending_approval") is True
        and request_id in (call.output.get("approval") or {}).get("approval_request_ids", [])
    ]
    if len(calls) != 1:
        return ""
    call = calls[0]
    nodes = [
        node
        for node in (result.node_results if result else [])
        if node.tool_id == call.params.get("tool_id", call.tool_id)
        and node.action == call.params.get("action", call.action)
    ]
    if result and len(nodes) != 1:
        return ""
    success = bool(result and result.success and nodes[0].success)
    outputs = [dict(getattr(node, "output", {}) or {}) for node in nodes]
    output = {
        "success": success,
        "pending_approval": False,
        "message": "审批业务执行完成" if success else "审批业务失败或已拒绝",
        "data": outputs[0].get("data", outputs[0]) if outputs else {},
    }
    run.add_event(
        "approval.resolved",
        output["message"],
        {"approval_request_id": request_id, "previous_output": call.output, "success": success},
    )
    call.output, call.status, call.error = (
        output,
        "completed" if success else "failed",
        "" if success else output["message"],
    )
    for step in run.steps:
        if step.step_id == call.step_id:
            step.output, step.status = output, call.status
    run.final_output.setdefault("node_outputs", {})[call.node_id] = output
    run.final_output["chat_payload"] = output
    run.final_output["tool_calls"] = [item.to_dict() for item in run.tool_calls]
    run.final_output.pop("business_result", None)
    remaining = any(item.output.get("pending_approval") is True for item in run.tool_calls)
    run.status = (
        "waiting_user"
        if remaining
        else ("completed" if success else ("failed" if result else "cancelled"))
    )
    run.error = "" if success or remaining else output["message"]
    if not remaining:
        run.add_event(f"run.{run.status}", output["message"], {"approval_request_id": request_id})
    if result:
        for node in nodes:
            recording.append_artifacts(
                run, _extract_artifacts(dict(getattr(node, "output", {}) or {}))
            )
    _append_artifacts_to_final_output(run)
    repo.save(run)
    return run.run_id
