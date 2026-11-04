"""Compose the public workflow tools with explicit execution dependencies."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from typing import Any

import pandas as pd

from app.application.tools.registered_capabilities import (
    ERP_CAPABILITY_TOOL_NAME,
    execute_registered_capability,
    extend_workflow_tool_registry,
)
from app.application.tools.safe_dataframe_query import safe_filter_dataframe
from app.application.tools.workflow_business_db import (
    business_db_tool_specs,
    try_execute_business_db_tool,
)
from app.application.tools.workflow_excel_paths import (
    _parse_excel_header_row_1based as _parse_excel_header_row_1based,
)
from app.application.tools.workflow_excel_paths import (
    resolve_safe_excel_path as resolve_safe_excel_path,
)
from app.application.tools.workflow_tools import adapters
from app.application.tools.workflow_tools.catalog_business import business_tool_specs
from app.application.tools.workflow_tools.catalog_excel import excel_tool_specs
from app.application.tools.workflow_tools.contracts import (
    ExcelIO,
    ImportServices,
    JsonTool,
    Payload,
    ToolCall,
    ToolHandler,
)
from app.application.tools.workflow_tools.dispatch import WorkflowToolDispatcher, parse_arguments
from app.application.tools.workflow_tools.documents import generate_office_document
from app.application.tools.workflow_tools.excel_analysis import (
    ExcelAnalysis,
    natural_language_query,
)
from app.application.tools.workflow_tools.excel_analysis import (
    read_excel_dataframe as _read_excel_dataframe,
)
from app.application.tools.workflow_tools.excel_operations import WorkbookOperations
from app.application.tools.workflow_tools.import_execution import ImportExecutor
from app.application.tools.workflow_tools.import_input import (
    ExcelImport,
    ImportHandlers,
    ImportHints,
)
from app.application.tools.workflow_tools.import_mapping import (
    CLAUSE_SUBSTRINGS as _CLAUSE_SUBSTRINGS,
)
from app.application.tools.workflow_tools.import_mapping import (
    ProductMapper,
    customer_records,
    looks_like_contract_or_footer_line,
    order_columns,
)
from app.application.tools.workflow_tools.import_mapping import (
    excel_cell_as_clean_str as _excel_cell_as_clean_str,
)
from app.application.tools.workflow_tools.import_mapping import (
    excel_cell_as_float as _excel_cell_as_float,
)
from app.application.tools.workflow_tools.import_mapping import (
    infer_product_field_mapping as _infer_product_field_mapping,
)
from app.application.tools.workflow_tools.registry import compose_registry
from app.infrastructure.auth.db_token import configured_db_write_token as configured_db_write_token
from app.infrastructure.excel.schema_service import ExcelSchemaUnderstandingService
from app.infrastructure.excel.text_to_pandas import _safe_exec_pandas
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# These process-local cache attributes remain available to existing integrations.
_workflow_tool_registry_cache: list[Payload] | None = None
_workflow_tool_registry_bulk_token_present: bool | None = None
_workflow_registry_cache_ver: int | None = None
_WORKFLOW_REG_VER = 3
_NEW_TOOL_DISPATCH_CACHE: dict[str, JsonTool] | None = None


def _base_registry() -> list[Payload]:
    return excel_tool_specs() + business_tool_specs() + business_db_tool_specs()


def get_workflow_tool_registry() -> list[Payload]:
    global \
        _workflow_tool_registry_cache, \
        _workflow_tool_registry_bulk_token_present, \
        _workflow_registry_cache_ver
    if (
        _workflow_tool_registry_cache is not None
        and _workflow_tool_registry_bulk_token_present is True
        and _workflow_registry_cache_ver == _WORKFLOW_REG_VER
    ):
        return _workflow_tool_registry_cache
    registry = compose_registry(
        _base_registry(), extend_workflow_tool_registry, adapters.employee_tools, logger
    )
    _workflow_tool_registry_cache = registry
    _workflow_tool_registry_bulk_token_present = True
    _workflow_registry_cache_ver = _WORKFLOW_REG_VER
    return registry


def invalidate_workflow_tool_registry() -> None:
    global _WORKFLOW_REG_VER, _workflow_tool_registry_cache
    _WORKFLOW_REG_VER += 1
    _workflow_tool_registry_cache = None
    try:
        adapters.invalidate_employee_tools()
    except RECOVERABLE_ERRORS:
        logger.debug("employee tool cache invalidate skipped", exc_info=True)


def _resolve_new_tool_dispatch(name: str) -> JsonTool | None:
    global _NEW_TOOL_DISPATCH_CACHE
    if _NEW_TOOL_DISPATCH_CACHE is None:
        try:
            _NEW_TOOL_DISPATCH_CACHE = adapters.crud_tools()
        except RECOVERABLE_ERRORS:
            logger.debug("new tool dispatch init failed", exc_info=True)
            _NEW_TOOL_DISPATCH_CACHE = {}
    return _NEW_TOOL_DISPATCH_CACHE.get(name)


def _excel_io() -> ExcelIO:
    return ExcelIO(resolve_safe_excel_path, _read_excel_dataframe, _parse_excel_header_row_1based)


def run_natural_language_pandas(df: pd.DataFrame, natural_language: str, **kwargs: Any) -> Payload:
    return natural_language_query(
        df, natural_language, adapters.translate_pandas, _safe_exec_pandas
    )


def handle_excel_analysis(args: Payload, workspace_root: str | None = None) -> Payload:
    return ExcelAnalysis(
        _excel_io(),
        run_natural_language_pandas,
        safe_filter_dataframe,
        adapters.customer_hint,
        logger,
    ).analyze(args, workspace_root)


def _looks_like_contract_or_footer_line(name: str | None) -> bool:
    return looks_like_contract_or_footer_line(name, _CLAUSE_SUBSTRINGS)


def _import_executor() -> ImportExecutor:
    return ImportExecutor(
        ImportServices(
            adapters.customer_writer,
            adapters.product_writer,
            adapters.shipment_writer,
            adapters.find_customer,
        )
    )


def _import_products_preview_or_execute(
    df: pd.DataFrame,
    columns: list[str],
    unit_name: str,
    confirm: bool,
    row_count: int,
    *,
    read_meta: Payload | None = None,
    price_column_hint: str | None = None,
) -> str:
    rows = ProductMapper(
        _infer_product_field_mapping,
        _excel_cell_as_clean_str,
        _excel_cell_as_float,
        _looks_like_contract_or_footer_line,
    ).map(df, columns, unit_name, price_column_hint)
    return json.dumps(
        _import_executor().products(rows, unit_name, confirm, read_meta), ensure_ascii=False
    )


def _import_customers_preview_or_execute(
    df: pd.DataFrame,
    columns: list[str],
    confirm: bool,
    row_count: int,
) -> str:
    return json.dumps(
        _import_executor().customers(customer_records(df, columns), confirm), ensure_ascii=False
    )


def _import_orders_preview_or_execute(
    df: pd.DataFrame,
    columns: list[str],
    unit_name: str,
    confirm: bool,
    row_count: int,
) -> str:
    result = _import_executor().orders(
        df, columns, order_columns(columns), unit_name, confirm, row_count
    )
    return json.dumps(result, ensure_ascii=False)


def _handle_import_excel_to_database(
    args: Payload,
    workspace_root: str | None = None,
    db_write_token: str | None = None,
) -> str:
    importer = ExcelImport(
        _excel_io(),
        ImportHints(
            adapters.customer_hint, adapters.inline_customer_hints, adapters.detected_header
        ),
        ImportHandlers(
            _import_products_preview_or_execute,
            _import_customers_preview_or_execute,
            _import_orders_preview_or_execute,
        ),
        lambda: str(os.environ.get("FHD_DB_WRITE_TOKEN") or "").strip(),
        logger,
    )
    return importer.execute(args, workspace_root, db_write_token)


def _json_tool(
    handler: Callable[[ToolCall], Payload], *, failure: Payload | None = None
) -> ToolHandler:
    def execute(call: ToolCall) -> str:
        try:
            return json.dumps(handler(call), ensure_ascii=False)
        except RECOVERABLE_ERRORS:
            if failure is None:
                raise
            return json.dumps(failure, ensure_ascii=False)

    return execute


def execute_workflow_tool(
    name: str,
    args: Payload | str,
    workspace_root: str | None = None,
    *,
    db_write_token: str | None = None,
    runtime_context: Payload | None = None,
) -> str:
    workbooks = WorkbookOperations(
        _excel_io(),
        lambda path: pd.read_excel(path),
        ExcelSchemaUnderstandingService,
        adapters.ingest_vector,
    )
    builtins: dict[str, ToolHandler] = {
        "excel_analysis": _json_tool(
            lambda call: handle_excel_analysis(call.args, workspace_root=call.workspace_root)
        ),
        "excel_chart_recommend": _json_tool(
            lambda call: {
                "suggestions": [
                    {"chart_type": "bar", "title": "分类对比"},
                    {"chart_type": "line", "title": "趋势分析"},
                ]
            }
        ),
        "excel_join_compare": _json_tool(
            lambda call: workbooks.join_compare(call.args, call.workspace_root),
            failure={"success": False, "error": "excel_tool_failed"},
        ),
        "excel_prophet": _json_tool(
            lambda call: workbooks.forecast(call.args, call.workspace_root),
            failure={"action": "forecast", "future_forecast": [], "error": "forecast_failed"},
        ),
        "excel_schema_understand": _json_tool(
            lambda call: workbooks.schema(call.args, call.workspace_root),
            failure={
                "success": False,
                "error": "read_excel_failed",
                "message": "读取 Excel 文件失败，请检查文件后重试",
            },
        ),
        "products_bulk_import": _json_tool(lambda call: adapters.bulk_import(call.args)),
        "excel_vector_index": _json_tool(
            lambda call: workbooks.vector_index(call.args, call.workspace_root)
        ),
        "import_excel_to_database": lambda call: _handle_import_excel_to_database(
            call.args, workspace_root=call.workspace_root, db_write_token=call.db_write_token
        ),
        "generate_office_document": _json_tool(
            lambda call: generate_office_document(
                call.args, adapters.generate_document, adapters.store_document
            ),
            failure={"success": False, "error": "office_document_generation_failed"},
        ),
    }
    dispatcher = WorkflowToolDispatcher(
        ERP_CAPABILITY_TOOL_NAME,
        lambda call: execute_registered_capability(
            call.args, workspace_root=call.workspace_root, runtime_context=call.runtime_context
        ),
        adapters.employee,
        adapters.native,
        adapters.template,
        adapters.legacy_employee,
        builtins,
        try_execute_business_db_tool,
        _resolve_new_tool_dispatch,
        logger,
    )
    return dispatcher.execute(
        ToolCall(name, parse_arguments(args), workspace_root, db_write_token, runtime_context)
    )


__all__ = [
    "resolve_safe_excel_path",
    "run_natural_language_pandas",
    "handle_excel_analysis",
    "get_workflow_tool_registry",
    "execute_workflow_tool",
]
