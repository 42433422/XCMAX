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
    """Admit a stable AIOPEN goal through the fixed Codex durable task gateway."""
    from app.application.agent_runtime.chat import _INSTRUCTIONS
    from app.application.agent_runtime.gateway import run_runtime_task

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
    context.update(task_id=task_id, turn_id=task_id, client_request_id=key)
    context.setdefault("workspace_id", task_id)
    result = run_runtime_task(
        task=message,
        system_prompt=_INSTRUCTIONS,
        runtime_context=context,
        completion_mode="auto",
        start_queued=True,
        _task_id=task_id,
    )
    state = str(result.get("execution_state") or result.get("exit_status") or "failed")
    run_id = str(result.get("run_id") or "")
    response = {
        "success": result.get("ok") is True and state == "completed",
        "task_id": task_id,
        "run_id": run_id,
        "agent_run_id": run_id,
        "request_id": key,
        "execution_state": state,
        "deduplicated": result.get("deduplicated") is True,
        "retryable": False,
        "pending_approval": result.get("pending_approval") is True or state == "waiting_approval",
        "message": str(
            result.get("error")
            or result.get("output")
            or "请按原任务 ID 查看进度并在统一审批入口处理。"
        ),
        "result": result,
    }
    if error_code := result.get("error_code"):
        response["error_code"] = (
            "task_idempotency_conflict" if error_code == "request_conflict" else str(error_code)
        )
    return response
