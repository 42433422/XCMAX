"""Compose the public workflow tools with explicit execution dependencies."""

from __future__ import annotations

import json
import logging
from collections.abc import Collection

from app.application.tools.registered_capabilities import (
    ERP_CAPABILITY_TOOL_NAME,
    build_registered_capability_tool_definition,
    execute_registered_capability,
)
from app.application.tools.safe_dataframe_query import safe_filter_dataframe
from app.application.tools.workflow_excel_paths import (
    _parse_excel_header_row_1based as _parse_excel_header_row_1based,
)
from app.application.tools.workflow_excel_paths import (
    resolve_safe_excel_path as resolve_safe_excel_path,
)
from app.application.tools.workflow_tools import adapters
from app.application.tools.workflow_tools.contracts import (
    ExcelIO,
    Payload,
    ToolCall,
    ToolHandler,
)
from app.application.tools.workflow_tools.dispatch import (
    WorkflowToolDispatcher,
    parse_arguments,
)
from app.application.tools.workflow_tools.excel_analysis import (
    ExcelAnalysis,
)
from app.application.tools.workflow_tools.excel_analysis import (
    read_excel_dataframe as _read_excel_dataframe,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def get_workflow_tool_registry(
    runtime_context: Payload | None = None,
    *,
    allowed_tools: Collection[str] | None = None,
    read_only: bool = False,
    exclude_tools: Collection[str] = (),
) -> list[Payload]:
    """Project current account contracts without caching another actor's grants."""
    definition = build_registered_capability_tool_definition(
        dict(runtime_context or {}),
        allowed_tools=allowed_tools,
        read_only=read_only,
        exclude_tools=exclude_tools,
    )
    return [definition] if definition["function"]["parameters"]["anyOf"] else []


def invalidate_workflow_tool_registry() -> None:
    try:
        from app.application.agent_orchestrator.tool_spec import (
            invalidate_tool_specs_cache,
        )

        invalidate_tool_specs_cache()
    except RECOVERABLE_ERRORS:
        pass
    try:
        adapters.invalidate_employee_tools()
    except RECOVERABLE_ERRORS:
        logger.debug("employee tool cache invalidate skipped", exc_info=True)


def _excel_io() -> ExcelIO:
    return ExcelIO(resolve_safe_excel_path, _read_excel_dataframe, _parse_excel_header_row_1based)


def handle_excel_analysis(args: Payload, workspace_root: str | None = None) -> Payload:
    return ExcelAnalysis(
        _excel_io(),
        safe_filter_dataframe,
        adapters.customer_hint,
        logger,
    ).analyze(args, workspace_root)


def _execute_registered_handoff(call: ToolCall) -> Payload:
    from app.application.employee_runtime.handoff_commit import (
        commit_registered_handoff,
    )

    return commit_registered_handoff(call.args, call.workspace_root, call.runtime_context)


def execute_workflow_tool(
    name: str,
    args: Payload | str,
    workspace_root: str | None = None,
    *,
    db_write_token: str | None = None,
    runtime_context: Payload | None = None,
) -> str:
    builtins: dict[str, ToolHandler] = {
        "handoff_commit": lambda call: json.dumps(
            _execute_registered_handoff(call), ensure_ascii=False
        ),
    }
    dispatcher = WorkflowToolDispatcher(
        ERP_CAPABILITY_TOOL_NAME,
        lambda call: execute_registered_capability(
            call.args,
            workspace_root=call.workspace_root,
            runtime_context=call.runtime_context,
        ),
        adapters.employee,
        adapters.native,
        adapters.template,
        adapters.legacy_employee,
        builtins,
        logger,
    )
    return dispatcher.execute(
        ToolCall(name, parse_arguments(args), workspace_root, db_write_token, runtime_context)
    )


__all__ = [
    "resolve_safe_excel_path",
    "handle_excel_analysis",
    "get_workflow_tool_registry",
    "execute_workflow_tool",
]
