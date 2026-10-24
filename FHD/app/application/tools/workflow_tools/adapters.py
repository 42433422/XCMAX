"""Late-bound host integrations for the workflow composition root."""

from __future__ import annotations

import importlib
import json
from typing import Literal, Protocol

import pandas as pd

from app.application.tools.workflow_tools.contracts import (
    CustomerWriter,
    JsonTool,
    Payload,
    ProductWriter,
    ShipmentWriter,
    ToolCall,
)


def employee_tools() -> list[Payload]:
    from app.mod_sdk.employee_tool_registry import build_employee_pack_tool_definitions

    return build_employee_pack_tool_definitions()


def invalidate_employee_tools() -> None:
    from app.mod_sdk.employee_tool_registry import invalidate_employee_tool_cache

    invalidate_employee_tool_cache()


def employee(call: ToolCall) -> str | None:
    from app.mod_sdk.employee_tool_registry import execute_employee_tool, is_employee_tool

    if is_employee_tool(call.name):
        return execute_employee_tool(call.name, call.args, call.workspace_root)
    return None


def native(call: ToolCall) -> str | None:
    from app.mod_sdk.planner_native_tools import try_execute_native_planner_tool

    result, _mod = try_execute_native_planner_tool(
        call.name, call.args, call.workspace_root, db_write_token=call.db_write_token
    )
    return result


def legacy_employee(call: ToolCall) -> str | None:
    from app.application.employee_pack_runner import try_execute_employee_planner_tool

    return try_execute_employee_planner_tool(
        call.name, call.args, call.workspace_root, db_write_token=call.db_write_token
    )


def template(call: ToolCall) -> str:
    from app.services.tools_workflow_registered import execute_registered_workflow_tool

    action = str(call.args.get("action") or "view").strip() or "view"
    return json.dumps(
        execute_registered_workflow_tool(call.name, action, call.args), ensure_ascii=False
    )


def crud_tools() -> dict[str, JsonTool]:
    from app.application.tools.customer_crud_tools import (
        delete_customer,
        list_customers,
        update_customer,
    )
    from app.application.tools.rbac_tools import (
        assign_role,
        create_role,
        delete_role,
        list_roles,
        update_role,
    )
    from app.application.tools.report_config_tools import configure_report, list_report_configs
    from app.application.tools.shipment_crud_tools import delete_order, list_orders, update_order

    return {
        "delete_order": delete_order,
        "update_order": update_order,
        "list_orders": list_orders,
        "update_customer": update_customer,
        "delete_customer": delete_customer,
        "list_customers": list_customers,
        "configure_report": configure_report,
        "list_report_configs": list_report_configs,
        "create_role": create_role,
        "update_role": update_role,
        "delete_role": delete_role,
        "assign_role": assign_role,
        "list_roles": list_roles,
    }


class PandasTranslator(Protocol):
    def translate(self, natural_language: str, df: pd.DataFrame) -> str | None: ...


def translate_pandas(natural_language: str, df: pd.DataFrame) -> str | None:
    legacy = importlib.import_module("app.legacy.excel_text_to_pandas")
    translator: PandasTranslator = legacy.ExcelTextToPandas()
    return translator.translate(natural_language, df)


def customer_hint(path: str, sheet: str | None) -> str:
    from app.application.template_grid_core import _extract_customer_hint_from_excel

    return _extract_customer_hint_from_excel(path, sheet)


def inline_customer_hints(text: str) -> list[str]:
    from app.application.template_grid_core import _extract_inline_customer_hits_from_cell

    return _extract_inline_customer_hits_from_cell(text)


def detected_header(analysis: Payload, sheet: str | None) -> int | None:
    from app.domain.context.session_context import detected_excel_header_row_1based

    return detected_excel_header_row_1based(analysis, preferred_sheet_name=sheet)


def customer_writer() -> CustomerWriter:
    from app.bootstrap import get_customer_app_service

    return get_customer_app_service()


def product_writer() -> ProductWriter:
    from app.bootstrap import get_products_service

    return get_products_service()


def shipment_writer() -> ShipmentWriter:
    from app.bootstrap import get_shipment_app_service

    return get_shipment_app_service()


def find_customer(unit_name: str) -> Payload | None:
    from app.services.unified_query_service import find_purchase_unit

    return find_purchase_unit(unit_name=unit_name)


def bulk_import(args: Payload) -> Payload:
    from app.application.excel_imports import run_bulk_import

    return run_bulk_import(args)


def ingest_vector(*, file_path: str, index_name: str | None, index_id: str | None) -> Payload:
    from app.application import get_excel_vector_ingest_app_service

    return get_excel_vector_ingest_app_service().ingest_excel(
        file_path=file_path, index_name=index_name, index_id=index_id
    )


def generate_document(request: str, output_format: Literal["docx", "xlsx"]) -> tuple[bytes, str]:
    from app.services.kitten_ai_document.generate import generate_office_file

    return generate_office_file(request, output_format)


def store_document(content: bytes, name: str, mime: str) -> str:
    from app.services.kitten_ai_document.pickup import store_document_pickup

    return store_document_pickup(content, name, mime)
