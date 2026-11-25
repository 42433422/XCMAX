"""Shared public response and ownership helpers for Agent API routers."""

from __future__ import annotations

import copy
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import replace
from typing import Any, TypeVar, cast

from fastapi.responses import JSONResponse

from app.application.agent_orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.approval_grant import issue_approval_grant
from app.application.agent_orchestrator.run_lifecycle import requires_retry_reconciliation
from app.application.agent_orchestrator.run_models import AgentRun, utc_now_iso
from app.application.agent_orchestrator.task_dispatcher import notify_agent_task_dispatcher
from app.application.agent_orchestrator.task_execution_models import AgentTaskExecution
from app.application.agent_orchestrator.task_execution_repository import (
    get_task_execution_repository,
)
from app.application.agent_orchestrator.task_models import (
    AgentTask,
    attention_for_status,
    mod_id_of_run,
    tenant_id_of_run,
)
from app.application.agent_orchestrator.task_progress import fallback_task_progress_snapshot
from app.application.agent_orchestrator.unified_task import (
    run_owned_by as run_owned_by,
)
from app.application.agent_orchestrator.unified_task import (
    scoped_tasks as scoped_tasks,
)
from app.application.agent_orchestrator.unified_task import task_capabilities
from app.application.agent_orchestrator.unified_task import (
    task_scope_matches as task_scope_matches,
)
from app.domain.task_lifecycle.adapters import canonical_execution_state
from app.infrastructure.auth.agent_principal import AgentPrincipal
from app.infrastructure.codex.binding import (
    CodexBindingError,
    CodexBindingStore,
    canonical_digest,
)
from app.utils.json_safe import json_safe

logger = logging.getLogger(__name__)

PUBLIC_AGENT_ERROR = "Agent 执行失败，详细信息已记录"
PUBLIC_AGENT_SERVICE_ERROR = "Agent 服务暂时不可用，请稍后重试"
PUBLIC_APPROVAL_ERROR = "approval_grant 无效、过期或与当前步骤不匹配"
_CODEX_CONTROL_MESSAGES = {
    "reconciliation_required": "原任务执行结果尚需核对，暂不能恢复或重试",
    "owner_changed": "任务身份或授权已变化，请确认当前账号与原任务的业务范围",
    "identity_override": "续跑不能修改原任务的运行范围，请从原任务继续操作",
    "run_inactive": "终态任务不能恢复；重新执行业务请提交新任务",
}
_INTERNAL_ERROR_KEYS = frozenset({"error", "exception", "stack_trace", "traceback"})
_CODEX_PUBLIC_CONTROL_CODES = {
    "binding_conflict": "binding_conflict",
    "binding_missing": "binding_missing",
    "budget_exceeded": "budget_exceeded",
    "call_conflict": "call_conflict",
    "call_in_progress": "call_in_progress",
    "call_limit": "call_limit",
    "call_missing": "call_missing",
    "conversation_changed": "conversation_changed",
    "durable_storage_required": "durable_storage_required",
    "evidence_mismatch": "evidence_mismatch",
    "goal_changed": "goal_changed",
    "goal_mismatch": "goal_mismatch",
    "goal_required": "goal_required",
    "identity_override": "identity_override",
    "input_not_requested": "input_not_requested",
    "invalid_call": "invalid_call",
    "invalid_config": "invalid_config",
    "invalid_cost": "invalid_cost",
    "invalid_request": "invalid_request",
    "invalid_thread": "invalid_thread",
    "invalid_ttl": "invalid_ttl",
    "owner_changed": "owner_changed",
    "reconciliation_required": "reconciliation_required",
    "resume_context_missing": "resume_context_missing",
    "run_inactive": "run_inactive",
    "runtime_budget_exhausted": "runtime_budget_exhausted",
    "runtime_changed": "runtime_changed",
    "scope_conflict": "scope_conflict",
    "token_expired": "token_expired",
    "token_invalid": "token_invalid",
    "waiting_user": "waiting_user",
}
_TaskResult = TypeVar("_TaskResult", AgentRun, AgentTask)


def project_execution_failure(
    result: _TaskResult, execution: AgentTaskExecution | None
) -> _TaskResult:
    """Expose a stopped lease without rewriting business receipts or stored state."""
    if execution is None or result.status not in {"queued", "planning", "running", "retrying"}:
        return result
    state = canonical_execution_state(execution.state)
    if state not in {"failed", "unknown"}:
        return result
    code = "needs_verification" if state == "unknown" else execution.last_error_code
    uncertain = state == "unknown" or code == "needs_verification"
    status = (
        "unknown" if state == "unknown" else "blocked" if code == "needs_verification" else "failed"
    )
    metadata = dict(result.metadata)
    if uncertain or code == "retries_exhausted":
        metadata["non_retryable"] = True
    if uncertain:
        recovery = metadata.get("recovery")
        metadata["recovery"] = {
            **(recovery if isinstance(recovery, dict) else {}),
            "state": "manual_reconciliation_required",
            "error_code": code or "needs_verification",
        }
    updated_at = execution.finished_at or execution.updated_at or result.updated_at
    changes: dict[str, Any] = {
        "status": status,
        "metadata": metadata,
        "updated_at": updated_at,
    }
    if isinstance(result, AgentTask):
        progress = result.to_dict()["progress"]
        stage = fallback_task_progress_snapshot(
            status=status, attempt=result.attempt, updated_at=updated_at
        )["stage"]
        metadata["progress"] = {
            **progress,
            "status": status,
            "stage": "执行结果待人工核对" if uncertain else stage,
            "updated_at": updated_at,
        }
        changes["attention_state"] = attention_for_status(status)
    return replace(result, **changes)


def without_runtime_identity(raw: dict[str, Any]) -> dict[str, Any]:
    """Discard caller identity fields before resolving any server principal."""
    context = dict(raw)
    for key in (
        "workspace_root",
        "node_outputs",
        "active_skills",
        "tenant_id",
        "user_id",
        "actor_id",
        "local_user_id",
        "authenticated_local_user_id",
        "_mod_authorization",
        "_actor_authorization",
        "_credential_authorization",
        "_tool_approval_scope",
        "_bulk_preview_scope",
        "_bulk_preview_scopes",
        "mutation_policy",
        "service_source",
        "template_base_dir",
        "route_module",
        "mod_id",
        "active_mod_id",
        "authenticated_username",
        "authenticated_display_name",
        "_dataset_access_context_trusted",
        "dataset_access_context",
    ):
        context.pop(key, None)
    return context


def authenticated_runtime_context(raw: dict[str, Any], principal: AgentPrincipal) -> dict[str, Any]:
    from app.infrastructure.workspace import workspace_root

    context = without_runtime_identity(raw)
    context["workspace_root"] = str(workspace_root())
    if context.get("source") == "admin_employee_workspace":
        if not principal.is_admin:
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail="员工管理工作空间仅限管理员")
        # This surface reports the actual host workspace, never a caller-supplied
        # display path masquerading as an isolated checkout or cloud machine.
        for key in ("worktree_path", "cwd", "workspace_path", "workspace_isolation"):
            context.pop(key, None)
        context["workspace_path"] = context["workspace_root"]
        context["workspace_isolation"] = "host_workspace"
    context.update(user_id=principal.user_id, actor_id=principal.user_id)
    if principal.tenant_id:
        context["tenant_id"] = principal.tenant_id
    if principal.mod_authorization:
        context["_mod_authorization"] = dict(principal.mod_authorization)
        context["mod_id"] = str(principal.mod_authorization["mod_id"])
    if principal.actor_authorization:
        context["_actor_authorization"] = dict(principal.actor_authorization)
    return context


def request_runtime_context(request: Any, raw: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.infrastructure.auth.agent_principal import require_agent_principal

    return authenticated_runtime_context(
        dict(raw or {}), require_agent_principal(request, x_user_id=None)
    )


def success(data: Any, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"success": True, "data": json_safe(data)}
    payload.update(extra)
    return payload


def redact_internal_errors(value: Any) -> Any:
    """Remove persisted exception details before crossing the public API boundary."""
    if isinstance(value, dict):
        return {
            key: (
                PUBLIC_AGENT_ERROR
                if str(key).lower() in _INTERNAL_ERROR_KEYS and child
                else redact_internal_errors(child)
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [redact_internal_errors(item) for item in value]
    if isinstance(value, tuple):
        return [redact_internal_errors(item) for item in value]
    return value


def public_run_dict(run: Any, *, read_run: Callable[[str], Any] | None = None) -> dict[str, Any]:
    # to_dict shares metadata with the stored run: redact only the recursive copy.
    data = cast("dict[str, Any]", redact_internal_errors(run.to_dict()))
    metadata = data.get("metadata") or {}
    if (
        metadata.get("runtime_type") == "codex"
        or (metadata.get("runtime_context") or {}).get("source") == "codex_runtime"
    ):
        from app.application.agent_runtime.gateway import public_runtime_result

        data = public_runtime_result(data)
    if isinstance(data.get("metadata"), dict):
        data["metadata"].pop("_tool_approval_grants", None)
        context = data["metadata"].get("runtime_context")
        if isinstance(context, dict):
            for key in ("_actor_authorization", "_mod_authorization", "_credential_authorization"):
                context.pop(key, None)
        if data["metadata"].get("child_results"):
            from app.application.agent_orchestrator.run_audit_scope import project_child_results
            from app.application.agent_orchestrator.run_repository import get_agent_run_repository

            data["metadata"]["child_results"] = redact_internal_errors(
                project_child_results(
                    run, read_run or (lambda run_id: get_agent_run_repository().get(run_id))
                )
            )
    return data


def public_event_dict(event: Any) -> dict[str, Any]:
    data = cast("dict[str, Any]", redact_internal_errors(event.to_dict()))
    if event.event_type.startswith("runtime."):
        from app.application.agent_runtime.gateway import public_runtime_result

        return cast("dict[str, Any]", public_runtime_result(data))
    return data


def internal_error_response(operation: str) -> JSONResponse:
    logger.exception("%s failed", operation)
    return JSONResponse(
        {"success": False, "message": PUBLIC_AGENT_SERVICE_ERROR},
        status_code=500,
    )


def run_response(
    run: Any, *, principal: AgentPrincipal, read_run: Callable[[str], Any] | None = None
) -> dict[str, Any]:
    if run_owned_by(run, principal):
        from app.application.agent_orchestrator.run_repository import get_agent_run_repository
        from app.infrastructure.codex.receipt_projection import refresh_codex_receipts

        parent = run if run.metadata.get("runtime_type") == "codex" else None
        context = run.metadata.get("runtime_context") or {}
        if (
            parent is None
            and context.get("source") == "codex_runtime"
            and context.get("parent_run_id")
        ):
            parent = get_agent_run_repository().get(str(context["parent_run_id"]))
        if parent is not None and run_owned_by(parent, principal):
            refreshed = refresh_codex_receipts(parent)
            if parent.run_id == run.run_id:
                run = refreshed
    execution = get_task_execution_repository().get(run.run_id)
    run = project_execution_failure(run, execution)
    approval = issue_approval_grant(run, principal_id=principal.user_id)
    extra: dict[str, Any] = {"capabilities": task_capabilities(run)}
    if approval:
        extra["approval"] = approval
    if execution is not None:
        extra["execution"] = execution.to_dict()
    return success(public_run_dict(run, read_run=read_run), **extra)


def run_reference_response(run: Any) -> dict[str, Any]:
    task_context = run.metadata.get("task_context")
    task_id = str(task_context.get("task_id") or "") if isinstance(task_context, dict) else ""
    return success({"run_id": str(run.run_id), "status": str(run.status), "task_id": task_id})


def owned_run(
    orchestrator: AgentOrchestrator,
    run_id: str,
    principal: AgentPrincipal,
) -> tuple[Any | None, JSONResponse | None]:
    run = orchestrator.get_run(run_id)
    if run is None:
        return None, JSONResponse(
            {"success": False, "message": "agent run 不存在"}, status_code=404
        )
    if not run_owned_by(run, principal):
        return None, JSONResponse(
            {"success": False, "message": "无权访问该 agent run"}, status_code=403
        )
    return run, None


def enqueue_run(run: Any, *, requested_by: str) -> None:
    get_task_execution_repository().enqueue(run, requested_by=requested_by)
    notify_agent_task_dispatcher()


def sync_execution_terminal_state(run: Any) -> None:
    state = {
        "paused": "paused",
        "blocked": "blocked",
        "completed": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
    }.get(str(run.status or ""))
    if state:
        get_task_execution_repository().transition(run.run_id, state)


def _children(store: CodexBindingStore, run: Any) -> list[Any]:
    children = {}
    for call in (run.metadata.get("codex_runtime") or {}).get("calls", {}).values():
        child = store.repository.get(str(call.get("child_run_id") or ""))
        if child is None:
            task = store.repository.get_task(
                user_id=run.user_id, task_id=call["child_task_id"], tenant_id=tenant_id_of_run(run)
            )
            child = store.repository.get(task.active_run_id) if task else None
        if child is None:
            continue
        if (
            child.user_id != run.user_id
            or tenant_id_of_run(child) != tenant_id_of_run(run)
            or mod_id_of_run(child) != mod_id_of_run(run)
            or (child.metadata.get("runtime_context") or {}).get("parent_run_id") != run.run_id
        ):
            raise CodexBindingError("owner_changed", "原子任务归属已变化")
        children[child.run_id] = child
    return list(children.values())


def guard_codex_child_control(
    run: Any,
    *,
    action: str,
    principal: Any,
    orchestrator: Any,
    parent_control: tuple[str, int] | None = None,
) -> JSONResponse | None:
    context = run.metadata.get("runtime_context") or {}
    parent_id = str(context.get("parent_run_id") or "")
    if context.get("source") != "codex_runtime" or not parent_id:
        return None
    code = "codex_child_retry_forbidden" if action == "retry" else "codex_parent_control_required"
    message = (
        "请先核对原父任务；不能绕过父任务预算重新执行子任务"
        if action == "retry"
        else "请从原父任务恢复，原子任务授权或预算不能单独重建"
    )
    try:
        if action == "retry":
            raise CodexBindingError(code, message)
        store = CodexBindingStore(orchestrator._repo)
        binding = store.get(parent_id)
        parent, metadata = binding.run, binding.metadata
        store._validate_authority(parent, metadata)
        store._validate_control(parent)
        commands = store.repository.latest_task_control(parent_id)
        managed = (
            parent_control == (parent_id, metadata.get("generation"))
            and commands is not None
            and commands.action == "resume"
            and commands.requested_by == principal.user_id
        )
        held = any(
            call.get("child_run_id") == run.run_id and call.get("reservation_state") == "held"
            for call in metadata.get("calls", {}).values()
        )
        if (
            parent.user_id != run.user_id
            or tenant_id_of_run(parent) != tenant_id_of_run(run)
            or mod_id_of_run(parent) != mod_id_of_run(run)
            or parent.status not in {"queued", "planning", "running", "retrying", "waiting_user"}
            or (
                (metadata.get("revoked") or float(metadata.get("expires_at", 0)) <= time.time())
                and not managed
            )
            or not held
            or requires_retry_reconciliation(parent)
            or metadata.get("model_reconciliation_required")
        ):
            raise CodexBindingError(code, message)
    except CodexBindingError:
        logger.warning(
            "Codex child control denied: action=%s run_id=%s parent_run_id=%s",
            action,
            run.run_id,
            parent_id,
            exc_info=True,
        )
        return JSONResponse(
            {"success": False, "error_code": code, "parent_run_id": parent_id, "message": message},
            status_code=409,
        )
    return None


def control_codex_run(
    run: Any,
    *,
    action: str,
    principal: Any,
    orchestrator: Any,
    body: dict[str, Any] | None = None,
) -> JSONResponse:
    """Called only after the normal route's authenticated ownership check."""
    from app.application.agent_runtime.gateway import run_runtime_task

    store = CodexBindingStore(orchestrator._repo)
    data = body or {}
    try:
        if action in {"pause", "cancel"}:
            # Existing durable control commands fence callbacks immediately;
            # revoke the grant before stopping any already-published child.
            method = orchestrator.pause_run if action == "pause" else orchestrator.cancel_run
            controlled = method(run.run_id, requested_by=principal.user_id)
            store.close(run.run_id, "paused" if action == "pause" else "cancelled")
            for child in _children(store, store.repository.get(run.run_id)):
                method(child.run_id, requested_by=principal.user_id)
            if (controlled.metadata.get("codex_runtime") or {}).get("calls"):
                store.receipt_snapshot(run.run_id)
            return JSONResponse(run_response(store.repository.get(run.run_id), principal=principal))

        binding = store.get(run.run_id)
        context = binding.context
        if principal.actor_authorization != context.get("_actor_authorization") or (
            principal.mod_authorization or None
        ) != (context.get("_mod_authorization") or None):
            raise CodexBindingError("owner_changed", "恢复需要原任务的可信登录与业务范围")
        store._validate_authority(run, binding.metadata)
        if run.status in {"completed", "cancelled", "rejected"}:
            raise CodexBindingError("run_inactive", "终态任务不能恢复；重新执行业务请提交新任务")
        if (
            requires_retry_reconciliation(run)
            or binding.metadata.get("model_reconciliation_required")
            or any(
                call.get("state") in {"reserved", "unknown"}
                for call in (binding.metadata.get("model_requests") or {}).values()
            )
        ):
            raise CodexBindingError("reconciliation_required", "原任务结果尚需核对，不能续跑")
        rows = store.receipt_snapshot(run.run_id)
        if any(row.get("state") in {"unknown", "claimed"} for row in rows):
            raise CodexBindingError("reconciliation_required", "原调用结果尚未确定，不能重放")
        prompt = run.metadata.get("_codex_system_prompt")
        if not isinstance(prompt, str):
            raise CodexBindingError(
                "resume_context_missing", "原任务缺少服务端运行指令，请重新发起任务"
            )
        actions = run.metadata.get("runtime_allowed_actions")
        gate = None
        original_input = copy.deepcopy(run.metadata.get("_codex_input_data"))
        if run.metadata.get("runtime_gate_required"):
            from app.application.employee_runtime.agent import restore_codex_employee_gate

            restored_actions, gate = restore_codex_employee_gate(
                str(context.get("employee_id") or ""),
                context,
                input_data=original_input,
            )
            if sorted(restored_actions) != sorted(actions or []):
                raise CodexBindingError("owner_changed", "原员工能力目录已变化，请重新发起任务")
        raw_context = data.get("runtime_context") or {}
        if not isinstance(raw_context, dict) or set(raw_context) - {"turn_id"}:
            raise CodexBindingError("identity_override", "续跑不能修改原任务的运行范围")
        request_id = (
            data.get("request_id") or raw_context.get("turn_id") or f"control_{uuid.uuid4().hex}"
        )
        if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 160:
            raise CodexBindingError("invalid_request", "续跑请求标识无效")
        context["turn_id"] = request_id
        message = data.get("message")
        if message is not None and (
            not isinstance(message, str) or not message.strip() or len(message) > 16000
        ):
            raise CodexBindingError("invalid_request", "补充信息无效")
        turn_input = original_input
        if "attachment_upload_ids" in data:
            if not binding.metadata.get("waiting_input") or not message:
                raise CodexBindingError("input_not_requested", "只有原任务等待补充时可以提交新附件")
            upload_ids = data["attachment_upload_ids"]
            if (
                not isinstance(upload_ids, list)
                or not 1 <= len(upload_ids) <= 4
                or any(
                    not isinstance(item, str) or not item or len(item) > 80 for item in upload_ids
                )
                or len(set(upload_ids)) != len(upload_ids)
            ):
                raise CodexBindingError("invalid_request", "附件引用格式无效")
            # References are untrusted turn data. The compiler must resolve
            # current ownership, expiry and bytes again before any model request.
            turn_input = {**(original_input or {}), "attachment_upload_ids": upload_ids}
        request_key = canonical_digest({"turn_id": request_id, "owner": run.user_id})
        duplicate = request_key in (run.metadata.get("runtime_requests") or {})
        if not duplicate:
            if (
                binding.metadata.get("coordinator_active")
                and not binding.metadata.get("revoked")
                and float(binding.metadata.get("expires_at", 0)) > time.time()
            ):
                raise CodexBindingError("binding_conflict", "原任务仍有活动执行者")
            command = store.repository.request_task_control(
                run.run_id, "resume", requested_by=principal.user_id
            )
            generation = binding.metadata.get("generation")
            if not isinstance(generation, int) or isinstance(generation, bool):
                raise CodexBindingError("binding_missing", "原运行授权版本无效")

            def resume(parent, metadata):
                if metadata.get("generation") != generation or parent.status in {
                    "completed",
                    "cancelled",
                    "rejected",
                }:
                    raise CodexBindingError("binding_conflict", "原任务状态已变化")
                parent.status = "running"
                parent.error = ""
                parent.metadata["control"] = {
                    "state": "running",
                    "requested_by": principal.user_id,
                    "command_id": command.command_id,
                }
                parent.add_event(
                    "run.resumed", "原 Codex 任务恢复", {"command_id": command.command_id}
                )

            store.update(run.run_id, resume)
            # The parent command is the authority to resume its still-reserved
            # paused child through the original frozen-plan transaction.
            from app.fastapi_routes.domains.agent.agent_routes import _control_agent_run

            for child in _children(store, run):
                if child.status == "paused":
                    response = _control_agent_run(
                        child.run_id,
                        action="resume",
                        principal=principal,
                        parent_control=(run.run_id, generation),
                    )
                    if isinstance(response, JSONResponse) and response.status_code >= 400:
                        store.repository.mark_task_control(
                            command.command_id, "rejected", applied_at=utc_now_iso()
                        )
                        store.update(
                            run.run_id, lambda parent, metadata: setattr(parent, "status", "paused")
                        )
                        return response
            store.repository.mark_task_control(
                command.command_id, "applied", applied_at=utc_now_iso()
            )
        result = run_runtime_task(
            run_id=run.run_id,
            task=message or run.message,
            system_prompt=prompt,
            runtime_context=context,
            input_data=turn_input,
            allowed_actions=actions,
            gate=gate,
            completion_mode=run.metadata.get("runtime_completion_mode", "business"),
            start_queued=True,
            answer_to_waiting_input=bool(message and binding.metadata.get("waiting_input")),
        )
        response = run_response(store.repository.get(run.run_id), principal=principal)
        response["runtime_result"] = result
        code = (
            202
            if result.get("execution_state") in {"queued", "running", "waiting_user"}
            else 200
            if result.get("ok")
            else 409
        )
        return JSONResponse(response, status_code=code)
    except (CodexBindingError, ValueError) as exc:
        logger.warning(
            "Codex run control denied: action=%s run_id=%s", action, run.run_id, exc_info=True
        )
        # Exception attributes can contain internal details; only static public codes cross HTTP.
        raw_error_code = getattr(exc, "code", None)
        error_code = _CODEX_PUBLIC_CONTROL_CODES.get(
            raw_error_code if isinstance(raw_error_code, str) else "", "runtime_control_denied"
        )
        return JSONResponse(
            {
                "success": False,
                "error_code": error_code,
                "message": _CODEX_CONTROL_MESSAGES.get(
                    error_code, "任务操作未完成，请刷新原任务并核对状态、授权和执行结果"
                ),
            },
            status_code=409,
        )


__all__ = [
    "PUBLIC_APPROVAL_ERROR",
    "control_codex_run",
    "guard_codex_child_control",
    "enqueue_run",
    "internal_error_response",
    "owned_run",
    "project_execution_failure",
    "public_event_dict",
    "public_run_dict",
    "run_reference_response",
    "run_response",
    "success",
    "sync_execution_terminal_state",
]
