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
from app.infrastructure.auth.agent_principal import AgentPrincipal


class UnifiedTaskError(ValueError):
    """A safe validation or idempotency failure for the public task API."""


class UnifiedTaskConflictError(UnifiedTaskError):
    """The public task id is already bound to different task content."""


@dataclass(frozen=True)
class UnifiedTaskResult:
    run: AgentRun
    deduplicated: bool = False


def run_owned_by(run: Any, principal: AgentPrincipal) -> bool:
    runtime_context = run.metadata.get("runtime_context") or {}
    binding = runtime_context.get("_mod_authorization") or {}
    requested_binding = principal.mod_authorization or {}
    run_mod = str(binding.get("mod_id") or "")
    requested_mod = str(requested_binding.get("mod_id") or "")
    # Legacy unbound runs still require the authenticated owner and tenant.
    # Platform administration is not a grant to access customer task data.
    same_mod = (not run_mod) or run_mod == requested_mod
    return (
        same_mod
        and run.user_id == principal.user_id
        and tenant_id_of_run(run) == principal.tenant_id
    )


RunScopeMap = dict[str, list[tuple[str, str, str]]]


def task_scope_matches(
    orchestrator: AgentOrchestrator,
    task: Any,
    principal: AgentPrincipal,
    scopes: RunScopeMap | None = None,
) -> bool:
    if task.user_id != principal.user_id or task.tenant_id != principal.tenant_id:
        return False
    if scopes is None:
        runs = [
            run
            for run in orchestrator.list_task_runs(user_id=task.user_id, task_id=task.task_id)
            if tenant_id_of_run(run) == task.tenant_id
        ]
        return all(run_owned_by(run, principal) for run in runs)
    matching_scopes = [
        scope for scope in scopes.get(task.task_id, ()) if scope[1] == task.tenant_id
    ]
    # Historical task rows without run records remain readable by their owner
    # and tenant; they contain no authenticated Mod binding to override.
    requested_mod = str((principal.mod_authorization or {}).get("mod_id") or "")
    return all(
        (not run_mod or run_mod == requested_mod)
        and run_user == principal.user_id
        and run_tenant == principal.tenant_id
        for run_user, run_tenant, run_mod in matching_scopes
    )


def scoped_tasks(
    orchestrator: AgentOrchestrator,
    *,
    principal: AgentPrincipal,
    limit: int,
    include_archived: bool = False,
) -> list[Any]:
    result: list[Any] = []
    scopes = (
        orchestrator.list_run_scopes(user_id=principal.user_id)
        if hasattr(orchestrator, "list_run_scopes")
        else None
    )
    offset = 0
    while len(result) < limit:
        page = orchestrator.list_tasks(
            user_id=principal.user_id,
            tenant_id=principal.tenant_id,
            limit=100,
            offset=offset,
            include_archived=include_archived,
        )
        result.extend(
            task for task in page if task_scope_matches(orchestrator, task, principal, scopes)
        )
        if len(page) < 100:
            break
        offset += len(page)
    return result[:limit]


def task_capabilities(run: AgentRun) -> dict[str, bool]:
    from app.application.agent_orchestrator.run_lifecycle import safe_continuation_error

    status = str(run.status or "")
    if run.metadata.get("runtime_type") == "xiaox":
        from app.application.agent_orchestrator.run_lifecycle import requires_retry_reconciliation

        safe = not requires_retry_reconciliation(run) and not (
            run.metadata.get("xiaox_runtime") or {}
        ).get("model_reconciliation_required")
        approval = (
            safe
            and status == "waiting_user"
            and any(
                call.get("state") == "waiting_user"
                and (call.get("receipt") or {}).get("pending_approval") is True
                for call in (run.metadata.get("xiaox_runtime") or {}).get("calls", {}).values()
            )
        )
        return {
            "pause": status in {"queued", "planning", "running", "retrying", "waiting_user"},
            "cancel": status
            in {"queued", "planning", "running", "retrying", "waiting_user", "paused", "blocked"},
            "retry": safe and status in {"failed", "blocked"},
            "approve": approval,
            "resume": safe and not approval and status in {"paused", "waiting_user"},
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
    previous_scope = dict(previous_context)
    if not isinstance(scope.get("_actor_authorization"), dict):
        scope["user_id"] = user_id
    if not isinstance(previous_scope.get("_actor_authorization"), dict):
        previous_scope["user_id"] = run.user_id
    if (
        run.user_id != user_id
        or tenant_id_of_run(run) != tenant_id
        or run.metadata.get("execution_authorization_scope") != authorization_scope_hash(scope)
        or run.metadata.get("execution_authorization_scope")
        != authorization_scope_hash(previous_scope)
        or any(
            actor_tool_denial(step.tool_id, step.action, scope, step.params) is not None
            for step in run.steps
        )
        or previous_binding.get("mod_id", "") != requested_binding.get("mod_id", "")
        or str(previous_context.get("mod_id") or "")
        != str((runtime_context or {}).get("mod_id") or "")
    ):
        raise UnifiedTaskConflictError("task_id 已绑定到不同的账号或 Mod 范围")


def owned_task_receipt_ids(
    orchestrator: AgentOrchestrator,
    *,
    task_id: str,
    runtime_context: dict[str, Any],
) -> dict[str, str]:
    """Read original correlation IDs after a conflict, never its business payload."""
    from app.infrastructure.auth.agent_mod_scope import _bound_actor
    from app.utils.operational_errors import RECOVERABLE_ERRORS

    try:
        actor = _bound_actor(runtime_context)
        tenant_id = str(runtime_context.get("tenant_id") or "")
        task = orchestrator.get_task(user_id=str(actor.id), task_id=task_id, tenant_id=tenant_id)
        if task is None:
            return {}
        run = orchestrator.get_run(task.active_run_id)
        if run is None:
            return {}
        principal = AgentPrincipal(
            user_id=str(actor.id),
            tenant_id=tenant_id,
            mod_authorization=runtime_context.get("_mod_authorization"),
        )
        original = run.metadata.get("runtime_context") or {}
        original_mod = str((original.get("_mod_authorization") or {}).get("mod_id") or "")
        current_mod = str((runtime_context.get("_mod_authorization") or {}).get("mod_id") or "")
        if (
            not run_owned_by(run, principal)
            or original_mod != current_mod
            or (run.metadata.get("task_context") or {}).get("task_id") != task_id
        ):
            return {}
        ids = {"task_id": task.task_id, "run_id": run.run_id, "agent_run_id": run.run_id}
        request_id = str(
            original.get("idempotency_key")
            or original.get("turn_id")
            or original.get("call_id")
            or ""
        )
        if request_id:
            ids["request_id"] = request_id
        return ids
    except RECOVERABLE_ERRORS:
        return {}


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
    context = dict(runtime_context or {})
    user_id = str(context.get("user_id") or run.user_id)
    expected_task = str(context.get("task_id") or "")
    if (
        not expected_task
        or (run.metadata.get("task_context") or {}).get("task_id") != expected_task
    ):
        raise UnifiedTaskConflictError("任务候选缺少原始任务身份")
    if "execution_authorization_scope" not in run.metadata:
        from app.application.agent_orchestrator.approval_grant import authorization_scope_hash
        from app.application.agent_orchestrator.tool_permission import actor_tool_denial
        from app.infrastructure.auth.agent_mod_scope import validate_actor_context

        if (
            run.user_id != str(context.get("user_id") or "")
            or tenant_id_of_run(run) != str(context.get("tenant_id") or "")
            or validate_actor_context(context) is not None
            or actor_tool_denial(tool_id, action, context, params) is not None
            or not isinstance(run.metadata.get("runtime_context"), dict)
            or authorization_scope_hash(run.metadata["runtime_context"])
            != authorization_scope_hash(context)
        ):
            raise UnifiedTaskConflictError("首次任务登记缺少匹配的可信执行授权")
        run.metadata["execution_authorization_scope"] = authorization_scope_hash(context)
    _assert_reused_run_scope(
        run, user_id=user_id, tenant_id=str(context.get("tenant_id") or ""), runtime_context=context
    )
    fingerprint = _request_fingerprint(tool_id, action, params)
    run.metadata["task_request_fingerprint"] = fingerprint
    run.metadata["task_request"] = {
        "tool_id": tool_id,
        "action": action,
        "risk": risk,
        "idempotent": idempotent,
    }
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
    approval_preview: str = "",
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
                description=approval_preview or normalized_title,
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
    "owned_task_receipt_ids",
    "publish_task_run",
    "run_owned_by",
    "scoped_tasks",
    "task_capabilities",
    "task_scope_matches",
]
