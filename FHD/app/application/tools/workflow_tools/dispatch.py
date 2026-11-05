"""Ordered dispatch with explicit extension and built-in dependencies."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass

from app.application.tools.workflow_tools.contracts import (
    ExtensionHandler,
    JsonTool,
    Payload,
    ToolCall,
    ToolHandler,
)
from app.utils.json_safe import json_safe
from app.utils.operational_errors import RECOVERABLE_ERRORS


def parse_arguments(args: Payload | str) -> Payload:
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except RECOVERABLE_ERRORS:
            return {}
    return args if isinstance(args, dict) else {}


@dataclass(frozen=True)
class WorkflowToolDispatcher:
    capability_name: str
    capability: ToolHandler
    employee: ExtensionHandler
    native: ExtensionHandler
    template: ToolHandler
    legacy_employee: ExtensionHandler
    builtins: Mapping[str, ToolHandler]
    business_db: Callable[[str, Payload], Payload | None]
    resolve_crud: Callable[[str], JsonTool | None]
    logger: logging.Logger

    def execute(self, call: ToolCall) -> str:
        if call.name == self.capability_name:
            return self.capability(call)
        for label, handler in (("employee", self.employee), ("planner native", self.native)):
            result = self._extension(label, handler, call)
            if result is not None:
                return result
        if call.name == "template_preview":
            return self.template(call)
        result = self._extension("legacy employee planner", self.legacy_employee, call)
        if result is not None:
            return result
        builtin = self.builtins.get(call.name)
        if builtin is not None:
            return builtin(call)
        payload = self.business_db(call.name, call.args)
        if payload is not None:
            return json.dumps(payload, ensure_ascii=False, default=json_safe)
        crud = self.resolve_crud(call.name)
        if crud is not None:
            try:
                return json.dumps(crud(call.args), ensure_ascii=False, default=json_safe)
            except RECOVERABLE_ERRORS:
                return json.dumps(
                    {"success": False, "error": "tool_dispatch_failed"}, ensure_ascii=False
                )
        return json.dumps(
            {"success": False, "error": "unknown_tool", "tool": call.name}, ensure_ascii=False
        )

    def _extension(self, label: str, handler: ExtensionHandler, call: ToolCall) -> str | None:
        try:
            return handler(call)
        except RECOVERABLE_ERRORS:
            self.logger.debug("%s tool dispatch skipped", label, exc_info=True)
            return None


def execute_registered_workflow_tool(tool_id: str, action: str, params: dict | None = None) -> dict:
    """Authorize and execute registered tools at the application composition boundary."""
    from app.application.normal_chat_dispatch import resolve_tool_execution_profile
    from app.domain.shared_services.tools_workflow_common import (
        _normalize_business_db_entity,
        _remember_business_db_target,
    )
    from app.domain.shared_services.tools_workflow_dispatch import _REGISTERED_WORKFLOW_ROUTERS

    params = dict(params or {})
    runtime_context = dict(params.pop("_runtime_context", None) or {})
    customer_scope: AbstractContextManager[object] = nullcontext()
    customer_tenant = None
    if tool_id == "customers" and action == "ensure_exists":
        from fastapi import HTTPException

        from app.infrastructure.auth.agent_mod_scope import (
            AgentModAuthorizationError,
            _bound_actor,
            agent_mod_execution_scope,
        )
        from app.infrastructure.auth.business_scope_gate import (
            check_owned_business_permission,
        )

        try:
            actor = _bound_actor(runtime_context)
            customer_tenant = check_owned_business_permission(actor, "customer.edit")
            if str(runtime_context.get("tenant_id")) != str(customer_tenant):
                raise AgentModAuthorizationError("企业范围与登录账号不一致")
            if set(params) - {"unit_name", "customer_name", "name"}:
                raise AgentModAuthorizationError("客户确认操作不接受身份或对象 ID 覆盖")
            for hint in ("service_source", "route_module"):
                runtime_context.pop(hint, None)
            customer_scope = agent_mod_execution_scope(runtime_context.get("_mod_authorization"))
        except (AgentModAuthorizationError, HTTPException):
            return {
                "success": False,
                "error_code": "customer_action_not_authorized",
                "message": "当前登录身份无权在此客户数据范围执行操作",
            }
    profile = resolve_tool_execution_profile(runtime_context)
    user_message = str(runtime_context.get("message") or "").strip()
    router = _REGISTERED_WORKFLOW_ROUTERS.get(tool_id)
    if router is not None:
        from app.infrastructure.tenant_scope import owned_tenant_scope

        with (
            customer_scope,
            owned_tenant_scope(customer_tenant) if customer_tenant is not None else nullcontext(),
        ):
            result = router(action, params, runtime_context, profile, user_message)
        if tool_id == "business_db" and action == "write" and isinstance(result, dict):
            payload = params.get("payload")
            if isinstance(payload, dict):
                result = _remember_business_db_target(
                    runtime_context,
                    _normalize_business_db_entity(params.get("entity"), user_message),
                    str(params.get("operation") or params.get("op") or "create").strip().lower(),
                    result,
                )
        return result
    try:
        from app.mod_sdk.employee_tool_registry import execute_employee_tool, is_employee_tool

        if is_employee_tool(tool_id):
            workspace_root = runtime_context.get("workspace_root")
            raw = execute_employee_tool(
                tool_id,
                {**params, "task": params.get("task") or user_message},
                str(workspace_root) if workspace_root else None,
            )
            import json

            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"success": False, "message": raw}
    except RECOVERABLE_ERRORS:
        logging.getLogger(__name__).debug(
            "employee tool direct dispatch skipped tool=%s", tool_id, exc_info=True
        )
    return {"success": False, "message": f"未注册的工具动作: {tool_id}.{action}"}
