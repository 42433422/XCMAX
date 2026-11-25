"""Canonical server-backed task creation and lifecycle capabilities."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.task_models import tenant_id_of_run
from app.application.agent_orchestrator.tool_spec import validate_tool_call
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode


class UnifiedTaskError(ValueError):
    """A safe validation or idempotency failure for the public task API."""


class UnifiedTaskConflictError(UnifiedTaskError):
    """The public task id is already bound to different task content."""


@dataclass(frozen=True)
class UnifiedTaskResult:
    run: AgentRun
    deduplicated: bool = False


def task_capabilities(run: AgentRun) -> dict[str, bool]:
    from app.application.agent_orchestrator.run_lifecycle import safe_continuation_error

    status = str(run.status or "")
    if run.metadata.get("runtime_type") == "xiaox":
        from app.application.agent_orchestrator.run_lifecycle import requires_retry_reconciliation

        safe = not requires_retry_reconciliation(run) and not (
            run.metadata.get("xiaox_runtime") or {}
        ).get("model_reconciliation_required")
        return {
            "pause": status in {"queued", "planning", "running", "retrying", "waiting_user"},
            "cancel": status
            in {"queued", "planning", "running", "retrying", "waiting_user", "paused", "blocked"},
            "retry": safe and status in {"failed", "blocked"},
            "approve": False,
            "resume": safe and status in {"paused", "waiting_user"},
            "evidence": True,
        }
    context = run.metadata.get("runtime_context") or {}
    xiaox_child = context.get("source") == "xiaox_runtime" and bool(context.get("parent_run_id"))
    retryable = (
        status in {"failed", "blocked"} and not xiaox_child and not safe_continuation_error(run)
    )
    return {
        "pause": status in {"queued", "planning", "running", "retrying", "waiting_user"},
        "cancel": status
        in {"queued", "planning", "running", "retrying", "waiting_user", "paused", "blocked"},
        "retry": retryable,
        "approve": status == "waiting_user",
        "resume": status == "paused" and not xiaox_child,
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


def _assert_reused_run_scope(
    run: AgentRun,
    *,
    user_id: str,
    tenant_id: str,
    runtime_context: dict[str, Any] | None,
) -> None:
    from app.application.agent_orchestrator.approval_grant import (
        authorization_scope_hash,
    )
    from app.application.agent_orchestrator.tool_permission import actor_tool_denial

    previous_context = run.metadata.get("runtime_context") or {}
    previous_binding = previous_context.get("_mod_authorization") or {}
    requested_binding = (runtime_context or {}).get("_mod_authorization") or {}
    scope = dict(runtime_context or {})
    if not isinstance(scope.get("_actor_authorization"), dict):
        scope["user_id"] = user_id
    if (
        run.user_id != user_id
        or tenant_id_of_run(run) != tenant_id
        or run.metadata.get("execution_authorization_scope") != authorization_scope_hash(scope)
        or any(
            actor_tool_denial(step.tool_id, step.action, scope, step.params) is not None
            for step in run.steps
        )
        or previous_binding.get("mod_id", "") != requested_binding.get("mod_id", "")
        or str(previous_context.get("mod_id") or "")
        != str((runtime_context or {}).get("mod_id") or "")
    ):
        raise UnifiedTaskConflictError("task_id 已绑定到不同的账号或 Mod 范围")


def publish_task_run(
    *,
    orchestrator: AgentOrchestrator,
    run: AgentRun,
    tool_id: str,
    action: str,
    params: dict[str, Any],
    risk: str,
    idempotent: bool,
    runtime_context: dict[str, Any] | None = None,
) -> UnifiedTaskResult:
    """Atomically publish the complete existing task/run before any tool executes."""
    if run.error == "execution_idempotency_conflict":
        raise UnifiedTaskConflictError("原任务的执行身份或授权范围已变化，未发布新任务")
    fingerprint = _request_fingerprint(tool_id, action, params)
    run.metadata["task_request_fingerprint"] = fingerprint
    run.metadata["task_request"] = {
        "tool_id": tool_id,
        "action": action,
        "risk": risk,
        "idempotent": idempotent,
    }
    user_id = run.user_id
    run, created = orchestrator.create_task_run(run)
    if not created:
        _assert_reused_run_scope(
            run,
            user_id=user_id,
            tenant_id=str((runtime_context or {}).get("tenant_id") or ""),
            runtime_context=runtime_context,
        )
        if str(run.metadata.get("task_request_fingerprint") or "") != fingerprint:
            raise UnifiedTaskConflictError("task_id 已绑定到不同的任务内容")
    return UnifiedTaskResult(run=run, deduplicated=not created)


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
    if not normalized_task_id or len(normalized_task_id) > 160 or "/" in normalized_task_id:
        raise UnifiedTaskError("task_id 不能为空、不能含 /，且长度不能超过 160")
    if not isinstance(params, dict):
        raise UnifiedTaskError("params 必须是对象")
    if not str(tool_id or "").strip():
        raise UnifiedTaskError("任务参数无效: tool_id 不能为空")

    validation = validate_tool_call(tool_id, action, params)
    spec = validation.spec
    if not validation.ok or spec is None:
        raise UnifiedTaskError(validation.message or "任务工具未注册")

    fingerprint = _request_fingerprint(spec.tool_id, spec.action, params)
    context = dict(runtime_context or {})
    # Use the same server defaults before both creation and idempotent lookup.
    if not str(context.get("conversation_id") or context.get("session_id") or "").strip():
        context["conversation_id"] = normalized_task_id
    if not str(context.get("workspace_id") or context.get("workspace") or "").strip():
        context["workspace_id"] = normalized_task_id
    tenant_id = str(context.get("tenant_id") or "")
    task = orchestrator.get_task(
        user_id=user_id,
        task_id=normalized_task_id,
        tenant_id=tenant_id,
    )
    if task is not None:
        previous_fingerprint = str(task.metadata.get("task_request_fingerprint") or "")
        if previous_fingerprint != fingerprint:
            raise UnifiedTaskConflictError("task_id 已绑定到不同的任务内容")
        previous = orchestrator.get_run(task.active_run_id)
        if previous is None:
            task_runs = [
                run
                for run in orchestrator.list_task_runs(user_id=user_id, task_id=normalized_task_id)
                if tenant_id_of_run(run) == tenant_id
            ]
            previous = task_runs[-1] if task_runs else None
        if previous is None:
            raise UnifiedTaskError("任务账本缺少执行记录")
        _assert_reused_run_scope(
            previous, user_id=user_id, tenant_id=tenant_id, runtime_context=context
        )
        return UnifiedTaskResult(run=previous, deduplicated=True)

    # Backfill a pre-Task-SSOT AgentRun on first access so old durable tasks keep
    # their idempotency contract after the schema upgrade.
    existing = [
        run
        for run in orchestrator.list_task_runs(user_id=user_id, task_id=normalized_task_id)
        if tenant_id_of_run(run) == tenant_id
    ]
    if existing:
        previous = existing[-1]
        _assert_reused_run_scope(
            previous, user_id=user_id, tenant_id=tenant_id, runtime_context=context
        )
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
        orchestrator.save_run(previous)
        return UnifiedTaskResult(run=previous, deduplicated=True)

    normalized_title = str(title or message or f"任务 {normalized_task_id[-8:]}").strip()[:80]
    normalized_message = str(message or normalized_title).strip()[:2000]
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
    if context.get("enterprise_cognition"):
        from app.application.enterprise_cognition.execution import bind_goal_action_plan

        context = bind_goal_action_plan(plan, context)
    run = orchestrator.start_task_from_plan(
        user_id=user_id,
        message=normalized_message,
        plan=plan,
        runtime_context=context,
        persist=False,
    )
    return publish_task_run(
        orchestrator=orchestrator,
        run=run,
        tool_id=spec.tool_id,
        action=spec.action,
        params=params,
        risk=spec.risk,
        idempotent=spec.idempotent,
        runtime_context=context,
    )


__all__ = [
    "UnifiedTaskConflictError",
    "UnifiedTaskError",
    "UnifiedTaskResult",
    "create_unified_task",
    "publish_task_run",
    "task_capabilities",
]
