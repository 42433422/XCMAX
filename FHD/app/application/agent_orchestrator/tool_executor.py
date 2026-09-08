from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_spec import validate_tool_call, validate_tool_result

_SQL_TENANT_SCOPED_TOOL_IDS = frozenset({"business_db", "inventory"})


class AgentToolExecutor:
    def execute(
        self,
        step: AgentStep,
        *,
        runtime_context: dict[str, Any],
    ) -> dict[str, Any]:
        from app.application.facades.tools_facade import execute_registered_workflow_tool

        params = dict(step.params or {})
        validation = validate_tool_call(step.tool_id, step.action, params)
        if not validation.ok:
            return {
                "success": False,
                "error_code": validation.error_code,
                "message": validation.message,
                "tool_id": validation.tool_id,
                "action": validation.action,
            }
        params["_runtime_context"] = dict(runtime_context or {})
        action = validation.action or step.action
        runtime_tenant_raw = params["_runtime_context"].get("tenant_id")
        runtime_tenant_id: int | None = None
        if step.tool_id in _SQL_TENANT_SCOPED_TOOL_IDS and runtime_tenant_raw not in (None, ""):
            try:
                if isinstance(runtime_tenant_raw, bool) or not str(runtime_tenant_raw).isdigit():
                    raise ValueError
                runtime_tenant_id = int(runtime_tenant_raw)
                if runtime_tenant_id <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                return {
                    "success": False,
                    "error_code": "invalid_tenant_context",
                    "message": "任务租户上下文无效，已拒绝执行工具",
                    "tool_id": validation.tool_id,
                    "action": action,
                }

        from app.infrastructure.auth.agent_mod_scope import (
            AgentModAuthorizationError,
            agent_mod_execution_scope,
        )
        from app.infrastructure.tenant_scope import tenant_scope

        try:
            # Durable/background Agent runs execute outside the originating HTTP
            # request. Restore the authenticated integer tenant recorded in
            # runtime_context so repository/raw-SQL boundaries keep their fail-closed
            # isolation. Dataset/document tools deliberately keep their own opaque
            # string tenant keys and must not be coerced here.
            with agent_mod_execution_scope(params["_runtime_context"].get("_mod_authorization")), (
                tenant_scope(runtime_tenant_id) if runtime_tenant_id is not None else nullcontext()
            ):
                result = execute_registered_workflow_tool(step.tool_id, action, params)
        except AgentModAuthorizationError as exc:
            return {"success": False, "error_code": "mod_authorization_invalid",
                    "message": str(exc), "tool_id": validation.tool_id, "action": action}
        if not isinstance(result, dict):
            return {
                "success": False,
                "error_code": "tool_result_not_object",
                "message": "工具返回值必须是 object",
                "tool_id": validation.tool_id,
                "action": action,
                "raw_result_type": type(result).__name__,
            }

        output_validation = validate_tool_result(validation.tool_id, action, result)
        if not output_validation.ok:
            return {
                "success": False,
                "error_code": output_validation.error_code,
                "message": output_validation.message,
                "tool_id": output_validation.tool_id,
                "action": output_validation.action,
                "raw_success": result.get("success"),
                "raw_message": result.get("message") or result.get("error"),
                "raw_error_code": result.get("error_code"),
                "output_keys": sorted(str(key) for key in result.keys()),
            }
        return result
