from __future__ import annotations

from typing import Any

from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_spec import validate_tool_call, validate_tool_result


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
