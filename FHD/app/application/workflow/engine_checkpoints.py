"""Checkpoint progress, restoration and read-only replay of completed work."""

from __future__ import annotations

from typing import Any

from .ports import CheckpointStore
from .workflow_types import NodeExecutionResult, PlanGraph, WorkflowRunResult


def save_progress(
    checkpointer: CheckpointStore | None,
    plan: PlanGraph,
    runtime_context: dict[str, Any],
    executed: set[str],
    blocked: set[str],
) -> str | None:
    """若提供了 checkpointer，记录一次 checkpoint；否则返回 None。"""
    if checkpointer is None:
        return None
    checkpoint_id = checkpointer.save_checkpoint(
        plan.plan_id, len(executed), runtime_context, sorted(executed), blocked=sorted(blocked)
    )
    return str(checkpoint_id) if checkpoint_id is not None else None


def restore(
    plan: PlanGraph, checkpoint_id: str, checkpointer: CheckpointStore | None
) -> dict[str, Any] | WorkflowRunResult:
    if checkpointer is None:
        return WorkflowRunResult(
            plan_id=plan.plan_id, success=False, message="resume_run 需要 checkpointer"
        )
    checkpoint = checkpointer.get_checkpoint(plan.plan_id, checkpoint_id)
    if checkpoint is None:
        return WorkflowRunResult(
            plan_id=plan.plan_id, success=False, message=f"checkpoint 不存在: {checkpoint_id}"
        )
    return {
        "runtime_context": checkpoint.get("runtime_context") or {},
        "executed": list(checkpoint.get("executed_nodes") or []),
        "blocked": list(checkpoint.get("blocked") or []),
    }


def replay(
    plan_id: str, checkpoint_id: str | None = None, *, checkpointer: CheckpointStore | None
) -> WorkflowRunResult:
    """只读重放 checkpoint 中已执行节点的输出历史（不真正再执行工具）。

    用于审计/回归：重放结果（node_results + final_context）与原始运行一致。
    未指定 ``checkpoint_id`` 时使用最新 checkpoint。
    """
    if checkpointer is None:
        return WorkflowRunResult(
            plan_id=plan_id, success=False, message="replay_run 需要 checkpointer"
        )
    if checkpoint_id is not None:
        checkpoint = checkpointer.get_checkpoint(plan_id, checkpoint_id)
    else:
        checkpoint = getattr(checkpointer, "latest_checkpoint", lambda p: None)(plan_id)
    if checkpoint is None:
        return WorkflowRunResult(
            plan_id=plan_id, success=False, message="checkpoint 不存在，无法重放"
        )
    rc = checkpoint.get("runtime_context") or {}
    traces = rc.get("workflow_trace") or []
    outputs = rc.get("node_outputs") or {}
    node_results: list[NodeExecutionResult] = []
    for tr in traces:
        node_id = str(tr.get("node_id", ""))
        output = tr.get("output", outputs.get(node_id, {}))
        node_results.append(
            NodeExecutionResult(
                node_id=node_id,
                success=bool(tr.get("success")),
                tool_id=str(tr.get("tool_id", "")),
                action=str(tr.get("action", "")),
                output=output if isinstance(output, dict) else {},
                error=str(tr.get("error", "")),
                retries=int(tr.get("retries", 0)),
                retryable=bool(tr.get("retryable")),
                recovery_hint=str(tr.get("recovery_hint", "")),
                duration_ms=int(tr.get("duration_ms", 0)),
            )
        )
    workflow_status = rc.get("workflow_status") or {}
    success = bool(node_results) and workflow_status.get("state") == "completed"
    return WorkflowRunResult(
        plan_id=plan_id,
        success=success,
        node_results=node_results,
        final_context=dict(rc),
        message="重放自 checkpoint",
    )
