from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_spec import validate_tool_call, validate_tool_result

_SQL_TENANT_SCOPED_TOOL_IDS = frozenset(
    {
        "business_db",
        "normal_slot_dispatch",
        "customers",
        "products",
        "materials",
        "inventory",
        "purchase",
        "sales",
        "reports",
        "finance",
        "mrp",
        "suppliers",
        "shipment_records",
        "shipment_orders",
        "excel_import",
        "unit_products_import",
        "employee",
        "wechat",
    }
)


class AgentToolExecutor:
    def execute(
        self,
        step: AgentStep,
        *,
        runtime_context: dict[str, Any],
    ) -> dict[str, Any]:
        from app.application.agent_orchestrator.task_mod_scope import (
            TaskModScopeError,
            task_mod_execution_scope,
        )

        try:
            with task_mod_execution_scope(runtime_context):
                return self._execute_scoped(step, runtime_context=runtime_context)
        except TaskModScopeError as exc:
            return {
                "success": False,
                "error_code": "task_mod_scope_denied",
                "message": str(exc),
                "tool_id": step.tool_id,
                "action": step.action,
            }

    def _execute_scoped(
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
        if step.tool_id == "wechat" and runtime_tenant_raw in (None, ""):
            return {
                "success": False,
                "error_code": "invalid_tenant_context",
                "message": "微信后台任务缺少租户上下文",
            }
        if step.tool_id in _SQL_TENANT_SCOPED_TOOL_IDS and runtime_tenant_raw not in (None, ""):
            try:
                if isinstance(runtime_tenant_raw, bool) or not isinstance(
                    runtime_tenant_raw, (str, int)
                ):
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

        if step.tool_id in {"memory_v2", "employee", "wechat"}:
            from app.application.agent_orchestrator.execution_identity import execution_actor_scope
            from app.infrastructure.tenant_scope import tenant_scope

            actor = str(
                runtime_context.get("local_user_id")
                or runtime_context.get("actor_id")
                or runtime_context.get("user_id")
                or ""
            )
            with (
                execution_actor_scope(actor),
                tenant_scope(runtime_tenant_id) if runtime_tenant_id is not None else nullcontext(),
            ):
                result = execute_registered_workflow_tool(step.tool_id, action, params)
        elif step.tool_id == "software":
            from app.application.aiopen.software_control import screen_actor_scope

            with screen_actor_scope(runtime_context):
                result = execute_registered_workflow_tool(step.tool_id, action, params)
        elif runtime_tenant_id is None:
            result = execute_registered_workflow_tool(step.tool_id, action, params)
        else:
            # Durable/background Agent runs execute outside the originating HTTP
            # request. Restore the authenticated integer tenant recorded in
            # runtime_context so repository/raw-SQL boundaries keep their fail-closed
            # isolation. Dataset/document tools deliberately keep their own opaque
            # string tenant keys and must not be coerced here.
            from app.infrastructure.tenant_scope import tenant_scope

            with tenant_scope(runtime_tenant_id):
                result = execute_registered_workflow_tool(step.tool_id, action, params)
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
