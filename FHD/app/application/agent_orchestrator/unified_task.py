"""Canonical server-backed task creation and lifecycle capabilities."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.tool_spec import validate_tool_call
from app.application.workflow.types import PlanGraph, WorkflowNode


class UnifiedTaskError(ValueError):
    """A safe validation or idempotency failure for the public task API."""


class UnifiedTaskConflictError(UnifiedTaskError):
    """The public task id is already bound to different task content."""


@dataclass(frozen=True)
class UnifiedTaskResult:
    run: AgentRun
    deduplicated: bool = False


def task_capabilities(run: AgentRun) -> dict[str, bool]:
    status = str(run.status or "")
    retryable = status in {"failed", "cancelled", "blocked"} and not bool(
        run.metadata.get("non_retryable")
    )
    return {
        "pause": status in {"queued", "planning", "running", "retrying", "waiting_user"},
        "cancel": status
        in {"queued", "planning", "running", "retrying", "waiting_user", "paused", "blocked"},
        "retry": retryable,
        "approve": status == "waiting_user",
        "resume": status == "paused",
        "evidence": True,
    }


def _request_fingerprint(tool_id: str, action: str, params: dict[str, Any]) -> str:
    payload = json.dumps(
        {"tool_id": tool_id, "action": action, "params": params},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def create_unified_task(
    *,
    orchestrator: AgentOrchestrator,
    user_id: str,
    task_id: str,
    title: str,
    message: str,
    tool_id: str,
    action: str,
    params: dict[str, Any],
    runtime_context: dict[str, Any] | None = None,
) -> UnifiedTaskResult:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id or len(normalized_task_id) > 160:
        raise UnifiedTaskError("task_id 不能为空且长度不能超过 160")
    if not isinstance(params, dict):
        raise UnifiedTaskError("params 必须是对象")

    validation = validate_tool_call(tool_id, action, params)
    spec = validation.spec
    if not validation.ok or spec is None:
        raise UnifiedTaskError(validation.message or "任务工具未注册")

    fingerprint = _request_fingerprint(spec.tool_id, spec.action, params)
    existing = orchestrator.list_task_runs(user_id=user_id, task_id=normalized_task_id)
    if existing:
        previous = existing[-1]
        previous_fingerprint = str(previous.metadata.get("task_request_fingerprint") or "")
        if not previous_fingerprint and not previous.tool_calls and previous.steps:
            first_step = previous.steps[0]
            previous_fingerprint = _request_fingerprint(
                first_step.tool_id,
                first_step.action,
                first_step.params,
            )
        if previous_fingerprint != fingerprint:
            raise UnifiedTaskConflictError("task_id 已绑定到不同的任务内容")
        return UnifiedTaskResult(run=previous, deduplicated=True)

    normalized_title = str(title or message or f"任务 {normalized_task_id[-8:]}").strip()[:80]
    normalized_message = str(message or normalized_title).strip()[:2000]
    context = dict(runtime_context or {})
    context.update(
        {
            "task_id": normalized_task_id,
            "task_title": normalized_title,
            "task_attempt": 1,
            "task_model_version": 1,
        }
    )
    node_id = f"task_{uuid.uuid4().hex}"
    plan = PlanGraph(
        plan_id=f"plan_{uuid.uuid4().hex}",
        intent=f"task:{spec.tool_id}.{spec.action}",
        todo_steps=[normalized_title],
        nodes=[
            WorkflowNode(
                node_id=node_id,
                tool_id=spec.tool_id,
                action=spec.action,
                params=dict(params),
                risk=spec.risk,
                idempotent=spec.idempotent,
                description=normalized_title,
            )
        ],
        risk_level=spec.risk,
        metadata={
            "source": "unified_task_api",
            "task_model_version": 1,
        },
    )
    run = orchestrator.start_task_from_plan(
        user_id=user_id,
        message=normalized_message,
        plan=plan,
        runtime_context=context,
    )
    run.metadata["task_request_fingerprint"] = fingerprint
    run.metadata["task_request"] = {
        "tool_id": spec.tool_id,
        "action": spec.action,
        "risk": spec.risk,
        "idempotent": spec.idempotent,
    }
    run = orchestrator.save_run(run)
    return UnifiedTaskResult(run=run)


__all__ = [
    "UnifiedTaskConflictError",
    "UnifiedTaskError",
    "UnifiedTaskResult",
    "create_unified_task",
    "task_capabilities",
]
