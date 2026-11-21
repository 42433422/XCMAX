"""Late-bound host integrations for the workflow composition root."""

from __future__ import annotations

from typing import Literal

from app.application.tools.workflow_tools.contracts import (
    ToolCall,
)


def invalidate_employee_tools() -> None:
    from app.mod_sdk.employee_tool_registry import invalidate_employee_tool_cache

    invalidate_employee_tool_cache()


def employee(call: ToolCall) -> str | None:
    from app.mod_sdk.employee_tool_registry import (
        execute_employee_tool,
        is_employee_tool,
    )

    if is_employee_tool(call.name):
        return execute_employee_tool(
            call.name,
            call.args,
            call.workspace_root,
            runtime_context=call.runtime_context,
        )
    return None


def native(call: ToolCall) -> str | None:
    from app.mod_sdk.planner_native_tools import try_execute_native_planner_tool

    result, _mod = try_execute_native_planner_tool(
        call.name,
        call.args,
        call.workspace_root,
        db_write_token=call.db_write_token,
        runtime_context=call.runtime_context,
    )
    return result


def legacy_employee(call: ToolCall) -> str | None:
    from app.domain.app_pure.employee_pack_runner import (
        try_execute_employee_planner_tool,
    )

    return try_execute_employee_planner_tool(
        call.name,
        call.args,
        call.workspace_root,
        db_write_token=call.db_write_token,
        runtime_context=call.runtime_context,
    )


def template(call: ToolCall) -> str:
    from app.application.tools.registered_capabilities import (
        execute_registered_capability,
    )

    action = str(call.args.get("action") or "view").strip() or "view"
    return execute_registered_capability(
        {"tool_id": call.name, "action": action, "params": call.args},
        workspace_root=call.workspace_root,
        runtime_context=call.runtime_context,
    )


def customer_hint(path: str, sheet: str | None) -> str:
    from app.application.template_grid_core import _extract_customer_hint_from_excel

    return _extract_customer_hint_from_excel(path, sheet)


def generate_document(request: str, output_format: Literal["docx", "xlsx"]) -> tuple[bytes, str]:
    from app.domain.shared_services.kitten_ai_document.generate import (
        generate_office_file,
    )

    return generate_office_file(request, output_format)


def store_document(content: bytes, name: str, mime: str) -> str:
    from app.domain.shared_services.kitten_ai_document.pickup import (
        store_document_pickup,
    )

    return store_document_pickup(content, name, mime)
