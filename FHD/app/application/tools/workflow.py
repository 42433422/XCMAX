"""Stable workflow-tool application facade.

The public import path is intentionally retained while implementations are
split by responsibility: registry schemas, read-only Excel analysis, dispatch,
and write-side import use cases. Private exports remain temporarily available
for compatibility and focused regression tests.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from app.application.tools.workflow_dispatcher import execute_workflow_tool_impl
from app.application.tools.workflow_excel_analysis import (
    _parse_excel_header_row_1based,
    _read_excel_dataframe,
    run_natural_language_pandas,
)
from app.application.tools.workflow_excel_analysis import (
    handle_excel_analysis as _handle_excel_analysis_impl,
)
from app.application.tools.workflow_excel_paths import resolve_safe_excel_path
from app.application.tools.workflow_import_customers import _import_customers_preview_or_execute
from app.application.tools.workflow_import_mapping import (
    _excel_cell_as_clean_str,
    _excel_cell_as_float,
    _infer_product_field_mapping,
    _looks_like_contract_or_footer_line,
)
from app.application.tools.workflow_import_orders import _import_orders_preview_or_execute
from app.application.tools.workflow_import_products import _import_products_preview_or_execute
from app.application.tools.workflow_import_service import handle_import_excel_to_database
from app.application.tools.workflow_registry import _base_registry
from app.infrastructure.auth.db_token import configured_db_write_token  # noqa: F401
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_workflow_tool_registry_cache: list[dict[str, Any]] | None = None
_workflow_tool_registry_bulk_token_present: bool | None = None
_workflow_registry_cache_ver: int | None = None
_WORKFLOW_REG_VER = 2


def handle_excel_analysis(
    args: dict[str, Any], workspace_root: str | None = None
) -> dict[str, Any]:
    return _handle_excel_analysis_impl(
        args,
        workspace_root=workspace_root,
        resolve_path=resolve_safe_excel_path,
        read_dataframe=_read_excel_dataframe,
        query_runner=run_natural_language_pandas,
    )


def _handle_import_excel_to_database(
    args: dict[str, Any],
    workspace_root: str | None = None,
    db_write_token: str | None = None,
) -> str:
    return handle_import_excel_to_database(
        args,
        workspace_root=workspace_root,
        db_write_token=db_write_token,
        resolve_path=resolve_safe_excel_path,
        read_dataframe=_read_excel_dataframe,
        parse_header_row=_parse_excel_header_row_1based,
        import_products=_import_products_preview_or_execute,
        import_customers=_import_customers_preview_or_execute,
        import_orders=_import_orders_preview_or_execute,
    )


def invalidate_workflow_tool_registry() -> None:
    """Invalidate host and employee-pack tool registries."""
    global _WORKFLOW_REG_VER, _workflow_tool_registry_cache
    _WORKFLOW_REG_VER += 1
    _workflow_tool_registry_cache = None
    try:
        from app.mod_sdk.employee_tool_registry import invalidate_employee_tool_cache

        invalidate_employee_tool_cache()
    except RECOVERABLE_ERRORS:
        logger.debug("employee tool cache invalidate skipped", exc_info=True)


def get_workflow_tool_registry() -> list[dict[str, Any]]:
    global _workflow_tool_registry_cache
    global _workflow_tool_registry_bulk_token_present
    global _workflow_registry_cache_ver
    bulk_on = True
    if (
        _workflow_tool_registry_cache is not None
        and _workflow_tool_registry_bulk_token_present == bulk_on
        and _workflow_registry_cache_ver == _WORKFLOW_REG_VER
    ):
        return _workflow_tool_registry_cache
    reg = _base_registry()
    try:
        from app.mod_sdk.employee_tool_registry import build_employee_pack_tool_definitions

        emp_tools = build_employee_pack_tool_definitions()
        if emp_tools:
            reg = reg + emp_tools
    except RECOVERABLE_ERRORS:
        logger.debug("employee pack tools merge skipped", exc_info=True)
    if bulk_on:
        reg.append(
            {
                "type": "function",
                "function": {
                    "name": "products_bulk_import",
                    "description": "批量导入产品数据到数据库。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "Excel 文件路径"},
                            "sheet_name": {"type": "string", "description": "工作表名称"},
                            "mapping": {"type": "object", "description": "列名映射配置"},
                        },
                        "required": ["file_path"],
                    },
                },
            }
        )
    _workflow_tool_registry_cache = reg
    _workflow_tool_registry_bulk_token_present = bulk_on
    _workflow_registry_cache_ver = _WORKFLOW_REG_VER
    return reg


def execute_workflow_tool(
    name: str,
    args: dict[str, Any] | str,
    workspace_root: str | None = None,
    *,
    db_write_token: str | None = None,
) -> str:
    return execute_workflow_tool_impl(
        name,
        args,
        workspace_root,
        db_write_token=db_write_token,
        resolve_path=resolve_safe_excel_path,
        read_dataframe=_read_excel_dataframe,
        parse_header_row=_parse_excel_header_row_1based,
        analyze_excel=handle_excel_analysis,
        import_excel=_handle_import_excel_to_database,
        pandas_module=pd,
    )


__all__ = [
    "_base_registry",
    "_excel_cell_as_clean_str",
    "_excel_cell_as_float",
    "_handle_import_excel_to_database",
    "_import_customers_preview_or_execute",
    "_import_orders_preview_or_execute",
    "_import_products_preview_or_execute",
    "_infer_product_field_mapping",
    "_looks_like_contract_or_footer_line",
    "_parse_excel_header_row_1based",
    "_read_excel_dataframe",
    "resolve_safe_excel_path",
    "run_natural_language_pandas",
    "handle_excel_analysis",
    "get_workflow_tool_registry",
    "invalidate_workflow_tool_registry",
    "execute_workflow_tool",
]
