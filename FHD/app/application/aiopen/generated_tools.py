"""AIOPEN transport projection of the canonical capability/task execution chain."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.infrastructure.aiopen.principal_context import current_execution_context
from app.infrastructure.auth.agent_mod_scope import validate_actor_context

from .catalog_builder import find_operation, get_catalog


def required_scope(app: Any, tool: str, args: dict[str, Any]) -> str:
    if tool != "operation_call":
        return ""
    entry = find_operation(get_catalog(app), str(args.get("operation_id") or ""))
    return str((entry or {}).get("scope") or "")


def _context(args: dict[str, Any]) -> dict[str, Any]:
    context = current_execution_context()
    key = str(args.get("request_id") or args.get("idempotency_key") or "").strip()
    header_key = str(context.get("idempotency_key") or "").strip()
    if key and header_key and key != header_key:
        raise ValueError("request_id 与 Idempotency-Key 不一致")
    if key or header_key:
        key = key or header_key
        if len(key) > 160 or "/" in key:
            raise ValueError("request_id 长度不得超过 160 且不能包含 /")
        context["idempotency_key"] = key
    context["source"] = "aiopen"
    return context


def operation_call(app: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Execute exactly one authoritative ToolSpec through the existing task API."""
    from app.application.tools.registered_capabilities import execute_registered_capability

    try:
        context = _context(args)
    except ValueError as error:
        return {"success": False, "code": "INVALID_ARGUMENT", "message": str(error)}
    if denial := validate_actor_context(context):
        return denial
    operation_id = str(args.get("operation_id") or "").strip()
    entry = find_operation(get_catalog(app, context), operation_id)
    if entry is None or entry.get("kind") != "capability":
        return {
            "success": False,
            "code": "OPERATION_NOT_FOUND",
            "message": "请选择当前账号可用的 capability，HTTP 资源描述不能作为执行契约。",
        }
    params = args.get("params", {})
    if not isinstance(params, dict) or args.get("body"):
        return {
            "success": False,
            "code": "INVALID_ARGUMENT",
            "message": "业务参数必须放在 params 对象中",
        }
    result: dict[str, Any] = json.loads(
        execute_registered_capability(
            {"tool_id": entry["tool_id"], "action": entry["action"], "params": params},
            runtime_context=context,
        )
    )
    result["operation_id"] = operation_id
    result["request_id"] = str(context.get("idempotency_key") or "")
    return result


def execute_message(args: dict[str, Any]) -> dict[str, Any]:
    """Plan and publish a chat goal using the same durable task admission and grants."""
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.unified_task import (
        UnifiedTaskConflictError,
        UnifiedTaskResult,
        _assert_reused_run_scope,
        _request_fingerprint,
        publish_task_run,
    )
    from app.application.workflow import LLMWorkflowPlanner
    from app.services.tools_execution.registry import get_workflow_tool_registry

    try:
        context = _context(args)
    except ValueError as error:
        return {"success": False, "code": "INVALID_ARGUMENT", "message": str(error)}
    if denial := validate_actor_context(context):
        return denial
    message = str(args.get("message") or "").strip()
    key = str(context.get("idempotency_key") or "")
    if not message or not key:
        return {
            "success": False,
            "code": "INVALID_ARGUMENT",
            "message": "chat 需要 message 和稳定 request_id",
        }
    identity = [str(context.get("tenant_id") or ""), str(context["user_id"]), "aiopen.chat", key]
    task_id = "task_goal_" + hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:40]
    context.update(task_id=task_id, conversation_id=task_id, workspace_id=task_id)
    orchestrator = AgentOrchestrator()
    params = {"message": message}
    try:
        task = orchestrator.get_task(
            user_id=context["user_id"], task_id=task_id, tenant_id=context.get("tenant_id", "")
        )
        if task is not None:
            run = orchestrator.get_run(task.active_run_id)
            if run is None or task.metadata.get("task_request_fingerprint") != _request_fingerprint(
                "aiopen", "chat", params
            ):
                raise UnifiedTaskConflictError("原请求内容不一致或回执尚未确认")
            _assert_reused_run_scope(
                run,
                user_id=context["user_id"],
                tenant_id=context.get("tenant_id", ""),
                runtime_context=context,
            )
            publication = UnifiedTaskResult(run=run, deduplicated=True)
        else:
            from app.infrastructure.llm.model_admission import model_rate_limit_scope

            with model_rate_limit_scope(context):
                plan = LLMWorkflowPlanner().plan(
                    context["user_id"], message, get_workflow_tool_registry(context), context
                )
            run = orchestrator.start_task_from_plan(
                user_id=context["user_id"],
                message=message,
                plan=plan,
                runtime_context=context,
                persist=False,
            )
            publication = publish_task_run(
                orchestrator=orchestrator,
                run=run,
                tool_id="aiopen",
                action="chat",
                params=params,
                risk=plan.risk_level,
                idempotent=False,
                runtime_context=context,
            )
        run = publication.run
    except UnifiedTaskConflictError:
        return {
            "success": False,
            "error_code": "task_idempotency_conflict",
            "task_id": task_id,
            "request_id": key,
        }
    if not publication.deduplicated and run.status == "queued":
        from app.application.agent_orchestrator.task_dispatcher import notify_agent_task_dispatcher

        notify_agent_task_dispatcher()
    from app.domain.task_lifecycle.results import execution_result_pending_state

    pending = execution_result_pending_state(run.final_output)
    return {
        "success": run.status == "completed" and not pending,
        "task_id": task_id,
        "run_id": run.run_id,
        "agent_run_id": run.run_id,
        "request_id": key,
        "execution_state": pending or run.status,
        "deduplicated": publication.deduplicated,
        "retryable": False,
        "pending_approval": run.status == "waiting_user",
        "message": "请按原任务 ID 查看进度并在统一审批入口处理。",
        "result": run.final_output,
    }
