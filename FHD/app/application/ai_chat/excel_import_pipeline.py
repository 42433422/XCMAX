"""Composed Excel-import application service for AI chat."""

from __future__ import annotations

from typing import Any, Callable

from app.application.ai_chat.compatibility import FacadeCompatibilityProxy
from app.application.ai_chat.excel_import_column_inference import ExcelImportColumnInferer
from app.application.ai_chat.excel_import_context import ExcelImportContextResolver
from app.application.ai_chat.excel_import_intent import ExcelImportIntentMatcher
from app.application.ai_chat.excel_import_price_resolution import ExcelImportPriceResolver
from app.application.ai_chat.excel_import_record_extractor import ExcelImportRecordExtractor
from app.application.ai_chat.excel_import_trace import ExcelImportTraceService


class AIChatExcelImportService:
    """Owns Excel-import collaborators without making the chat host inherit them."""

    def __init__(
        self,
        *,
        ai_service: Any,
        merge_tool_runtime_context: Callable[..., dict[str, Any]],
        is_number_text: Callable[[str], bool],
        row_values_look_like_table_headers: Callable[[list[str]], bool],
        resolve_unit_price_column: Callable[..., tuple[str, str | None]],
        format_agent_run_response: Callable[..., dict[str, Any]],
        pending_workflows: dict[str, dict[str, Any]],
        facade_type: type[Any],
    ) -> None:
        context = ExcelImportContextResolver()
        columns = ExcelImportColumnInferer(
            ai_service=ai_service,
            is_number_text=is_number_text,
        )
        prices = ExcelImportPriceResolver()
        compat_context = FacadeCompatibilityProxy(facade_type, context)
        compat_columns = FacadeCompatibilityProxy(facade_type, columns)
        records = ExcelImportRecordExtractor(
            context_resolver=compat_context,
            column_inferer=compat_columns,
            price_resolver=prices,
            resolve_unit_price_column=resolve_unit_price_column,
            is_number_text=is_number_text,
            row_values_look_like_table_headers=row_values_look_like_table_headers,
        )
        trace = ExcelImportTraceService(
            merge_tool_runtime_context=merge_tool_runtime_context,
            format_agent_run_response=format_agent_run_response,
            pending_workflows=pending_workflows,
        )
        self._components = (
            context,
            columns,
            prices,
            records,
            ExcelImportIntentMatcher(),
            trace,
        )

    def __getattr__(self, name: str) -> Any:
        for component in self._components:
            try:
                return object.__getattribute__(component, name)
            except AttributeError:
                continue
        raise AttributeError(name)


# Temporary import compatibility for extensions that imported the former class
# name. The public chat service no longer inherits this type.
AIChatExcelImportMixin = AIChatExcelImportService

__all__ = ["AIChatExcelImportService"]
