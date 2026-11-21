"""工作流工具统一分发：路由注册表与 execute_registered_workflow_tool。"""

from __future__ import annotations

from collections.abc import Callable

from app.domain.shared_services.tools_workflow_business_db import (
    _registered_router_business_db,
)
from app.domain.shared_services.tools_workflow_elt import (
    _registered_router_elt_import,
)
from app.domain.shared_services.tools_workflow_erp import (
    _registered_router_customers,
    _registered_router_finance,
    _registered_router_inventory,
    _registered_router_purchase,
    _registered_router_reports,
    _registered_router_sales,
)
from app.domain.shared_services.tools_workflow_erp_master import (
    _registered_router_materials,
    _registered_router_products,
)
from app.domain.shared_services.tools_workflow_excel_ocr import (
    _registered_router_excel_analysis,
    _registered_router_excel_vector_index,
    _registered_router_generate_office_document,
    _registered_router_import_excel_to_database,
)
from app.domain.shared_services.tools_workflow_excel_ocr_ops import (
    _registered_router_excel_import,
    _registered_router_ocr,
    _registered_router_unit_products_import,
)
from app.domain.shared_services.tools_workflow_memory_rag import (
    _registered_router_dataset_rag,
    _registered_router_memory_v2,
)
from app.domain.shared_services.tools_workflow_shipments_docs import (
    _registered_router_business_docking_family,
    _registered_router_business_event,
    _registered_router_mrp,
    _registered_router_shipment_orders,
    _registered_router_shipment_records,
    _registered_router_suppliers,
    _registered_router_system_maintenance,
)
from app.domain.shared_services.tools_workflow_shipments_docs_ops import (
    _registered_router_document_template,
    _registered_router_excel_analyzer,
    _registered_router_excel_toolkit,
    _registered_router_label_template_generator,
)
from app.domain.shared_services.tools_workflow_workspace import (
    _registered_router_desktop_automation,
    _registered_router_employee,
    _registered_router_print,
    _registered_router_printer_list,
    _registered_router_settings,
    _registered_router_template_preview,
)


def _registered_router_client_product_issue(action, params, runtime_context, profile, user_message):
    if action != "submit":
        return {"success": False, "message": "不支持的产品问题上报操作"}
    from app.application.client_product_issue_intake import resolve_issue_report_message
    from app.application.registered_client_issue import submit_client_product_issue

    # 与审批前置校验共用同一套取文逻辑：续办请求要从会话前文/计划参数找回问题描述。
    resolved = resolve_issue_report_message(user_message, runtime_context, params)
    return submit_client_product_issue(resolved or user_message, runtime_context)


def _registered_router_conversation_history(action, params, runtime_context, profile, user_message):
    from app.application.tools.conversation_history import read_conversation_history

    return read_conversation_history(action, params, runtime_context)


def _run_awaitable(value):
    """同步工具分发里执行 async 适配器方法；已有事件循环时改用独立线程。"""
    import asyncio
    import concurrent.futures

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, value).result()


def _registered_router_image_generate(action, params, runtime_context, profile, user_message):
    if action != "generate":
        return {"success": False, "message": "不支持的生图操作"}
    prompt = str(params.get("prompt") or "").strip() or str(user_message or "").strip()
    if not prompt:
        return {"success": False, "message": "请描述要生成的图片"}
    from uuid import uuid4

    from app.domain.shared_services.conversation.modstore_adapter import ModstorePlatformAdapter

    session_id = str(runtime_context.get("session_id") or "").strip() or None
    request_id = str(params.get("client_request_id") or f"agent-{uuid4().hex}")
    adapter = ModstorePlatformAdapter.from_session(session_id)
    if not adapter.auth_token:
        return {"success": False, "message": "当前账号未绑定市场模型服务授权，无法生图"}
    # The market adapter distinguishes a confirmed rejection from an unknown
    # paid side effect. Never expose transport exceptions or silently retry an
    # ambiguous image request with a different request key.
    from contextlib import suppress

    import httpx
    from fastapi import HTTPException

    try:
        data = _run_awaitable(
            adapter.generate_image({"prompt": prompt, "client_request_id": request_id})
        )
    except HTTPException as exc:
        if exc.status_code >= 500 or exc.status_code == 409:
            return {
                "success": False,
                "status": "blocked",
                "client_request_id": request_id,
                "message": "生图结果待核对，请保留原请求键",
            }
        return {"success": False, "message": "生图请求被拒绝，请检查授权或参数"}
    except (httpx.HTTPError, OSError, RuntimeError, ValueError):
        return {
            "success": False,
            "status": "blocked",
            "client_request_id": request_id,
            "message": "生图结果待核对，请保留原请求键",
        }
    finally:
        with suppress(httpx.HTTPError, OSError, RuntimeError, ValueError):
            _run_awaitable(adapter.close())
    images = [
        str(url)
        for url in (data.get("images") or [])
        if str(url).startswith("data:image/") or str(url).startswith("https://")
    ]
    if not images:
        return {"success": False, "message": "生图结果没有可显示的图片"}
    return {
        "success": True,
        "images": images,
        "model": str(data.get("model") or ""),
        "billed": bool(data.get("billed")),
        "charge_amount": str(data.get("charge_amount") or ""),
    }

def _registered_router_kellai(action, params, runtime_context, profile, user_message):
    from app.application.tools.kellai import execute_kellai

    return execute_kellai(action, params, runtime_context)

class _WorkflowRouterMap(dict):
    _hidden_keys = {"employee", "business_db"}

    def keys(self):
        return [key for key in super().keys() if key not in self._hidden_keys]

    def get(self, key, default=None):
        """外部 MCP 工具按 ``mcp__<server>`` 前缀动态路由，无需静态注册。"""
        if str(key).startswith("mcp__"):
            from app.application.tools.mcp.registry import call_mcp_tool

            return lambda action, params, runtime_context, profile, user_message: call_mcp_tool(
                str(key), action, params
            )
        return super().get(key, default)


_REGISTERED_WORKFLOW_ROUTERS: dict[str, Callable[..., dict]] = _WorkflowRouterMap(
    {
        "customers": _registered_router_customers,
        "products": _registered_router_products,
        "materials": _registered_router_materials,
        "inventory": _registered_router_inventory,
        "purchase": _registered_router_purchase,
        "sales": _registered_router_sales,
        "reports": _registered_router_reports,
        "finance": _registered_router_finance,
        "mrp": _registered_router_mrp,
        "suppliers": _registered_router_suppliers,
        "shipment_records": _registered_router_shipment_records,
        "shipment_orders": _registered_router_shipment_orders,
        "business_event": _registered_router_business_event,
        "system_maintenance": _registered_router_system_maintenance,
        "business_docking": _registered_router_business_docking_family,
        "template_extract": _registered_router_business_docking_family,
        "excel_analyzer": _registered_router_excel_analyzer,
        "excel_toolkit": _registered_router_excel_toolkit,
        "label_template_generator": _registered_router_label_template_generator,
        "document_template": _registered_router_document_template,
        "template_preview": _registered_router_template_preview,
        "print": _registered_router_print,
        "printer_list": _registered_router_printer_list,
        "settings": _registered_router_settings,
        "desktop_automation": _registered_router_desktop_automation,
        "employee": _registered_router_employee,
        "business_db": _registered_router_business_db,
        "dataset_rag": _registered_router_dataset_rag,
        "memory_v2": _registered_router_memory_v2,
        "conversation_history": _registered_router_conversation_history,
        "kellai": _registered_router_kellai,
        "image_generate": _registered_router_image_generate,
        "excel_analysis": _registered_router_excel_analysis,
        "import_excel_to_database": _registered_router_import_excel_to_database,
        "elt_import": _registered_router_elt_import,
        "generate_office_document": _registered_router_generate_office_document,
        "excel_vector_index": _registered_router_excel_vector_index,
        "ocr": _registered_router_ocr,
        "excel_import": _registered_router_excel_import,
        "client_product_issue": _registered_router_client_product_issue,
        "unit_products_import": _registered_router_unit_products_import,
    }
)


def execute_registered_workflow_tool(tool_id: str, action: str, params: dict | None = None) -> dict:
    """Legacy entry point; authorization and execution belong to the application layer."""
    from app.application.tools.workflow_tools.dispatch import (
        execute_registered_workflow_tool as execute,
    )

    return execute(tool_id, action, params)
