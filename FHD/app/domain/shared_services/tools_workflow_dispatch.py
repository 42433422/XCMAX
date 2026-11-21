"""工作流工具统一分发：路由注册表与 execute_registered_workflow_tool。"""

from __future__ import annotations

from collections.abc import Callable

from app.domain.shared_services.tools_workflow_business_db import _registered_router_business_db
from app.domain.shared_services.tools_workflow_elt import _registered_router_elt_import
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
    import contextvars

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(contextvars.copy_context().run, asyncio.run, value).result()


def _image_adapter(runtime_context):
    from app.db import HostSessionLocal
    from app.db.models.user import Session
    from app.domain.shared_services.conversation.modstore_adapter import ModstorePlatformAdapter
    from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError, _bound_actor
    from app.utils.time import utc_now_naive

    actor = _bound_actor(runtime_context)
    if runtime_context.get("local_user_id") not in (None, actor.id, str(actor.id)):
        raise AgentModAuthorizationError("当前会话账号不匹配")
    # Runtime session_id identifies a chat, not an authenticated login. Resolve
    # credentials only from the live, sealed actor's actual login session.
    with HostSessionLocal() as db:
        row = db.get(Session, runtime_context["_actor_authorization"]["session_row_id"])
        if row is None or row.user_id != actor.id or row.expires_at <= utc_now_naive():
            raise AgentModAuthorizationError("登录会话已失效")
        return ModstorePlatformAdapter.from_session(row.session_id)


async def _generate_image_and_close(adapter, body):
    import logging

    from app.utils.operational_errors import INFRA_TRANSIENT

    try:
        return await adapter.generate_image(body)
    finally:
        try:
            await adapter.close()
        except INFRA_TRANSIENT as exc:
            # A close failure must not discard an already confirmed paid receipt.
            logging.getLogger(__name__).warning("Image client close failed: %s", type(exc).__name__)


def _registered_router_image_generate(action, params, runtime_context, profile, user_message):
    import hashlib
    import re

    from fastapi import HTTPException

    from app.application.market_llm.multimodal import safe_image_result_urls
    from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError
    from app.utils.operational_errors import RECOVERABLE_ERRORS

    if action != "generate":
        return {"success": False, "message": "不支持的生图操作"}
    prompt = params.get("prompt", user_message)
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 4000:
        return {"success": False, "message": "请提供不超过 4000 字的图片描述"}
    prompt = prompt.strip()
    request_id = params.get("client_request_id")
    if request_id is None:
        key = str(runtime_context.get("idempotency_key") or "").strip()
        if not key:
            return {
                "success": False,
                "message": "生图任务缺少可恢复的请求键，请重新提交任务",
            }
        request_id = "agent-image-" + hashlib.sha256(key.encode()).hexdigest()
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{8,128}", request_id):
        return {"success": False, "message": "生图请求键格式无效"}
    receipt = {"client_request_id": request_id}
    try:
        adapter = _image_adapter(runtime_context)
    except AgentModAuthorizationError:
        return {
            "success": False,
            "message": "生图需要当前账号的有效登录授权",
            **receipt,
        }
    if not adapter.auth_token:
        return {
            "success": False,
            "message": "当前账号未绑定市场模型服务授权，无法生图",
            **receipt,
        }
    unknown = {
        "success": False,
        "message": "生图结果与计费状态待核对，请保留原请求键，勿重复提交新任务",
        "outcome": "unknown",
        "retryable": False,
        "reconciliation_required": True,
        **receipt,
    }
    try:
        data = _run_awaitable(_generate_image_and_close(adapter, {"prompt": prompt, **receipt}))
    except HTTPException as exc:
        remote_id = exc.detail.get("request_id") if isinstance(exc.detail, dict) else None
        if isinstance(remote_id, str) and remote_id:
            receipt["request_id"] = remote_id
        if exc.status_code in {400, 401, 402, 403, 404, 413, 422, 429}:
            return {
                "success": False,
                "message": "生图请求被拒绝",
                "status_code": exc.status_code,
                **receipt,
            }
        return {**unknown, **receipt}
    except RECOVERABLE_ERRORS:
        return unknown
    receipt.update(
        {
            key: data[key]
            for key in (
                "provider",
                "model",
                "billed",
                "charge_amount",
                "usage",
                "usage_details",
                "request_id",
                "operation",
                "key_source",
                "pricing",
                "hold_no",
            )
            if key in data
        }
    )
    images = safe_image_result_urls(data.get("images"))
    if not images:
        return {
            **unknown,
            **receipt,
            "message": "已收到生图回执但图片无法安全显示，请核对原请求",
        }
    return {"success": True, "images": images, **receipt}


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
