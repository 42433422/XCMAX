"""Misc workflow routers."""

from __future__ import annotations

import logging
from typing import Any

from app.services.tools_workflow_registered._facade import facade_attr
from app.services.tools_workflow_registered.business import (
    _registered_router_customers as _default_router_customers,
)
from app.services.tools_workflow_registered.business import (
    _registered_router_materials as _default_router_materials,
)
from app.services.tools_workflow_registered.business import (
    _registered_router_products as _default_router_products,
)
from app.services.tools_workflow_registered.business import (
    _registered_router_shipment_records as _default_router_shipment_records,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

def _registered_router_wechat(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    from app.application import get_wechat_contact_app_service

    svc = get_wechat_contact_app_service()
    if action == "view":
        return {"success": True, "redirect": "/console?view=wechat-contacts"}
    if action in ("list", "query"):
        return {
            "success": True,
            "data": svc.get_contacts(
                contact_type=str(params.get("type") or "all"),
                keyword=str(params.get("keyword") or "").strip() or None,
                limit=int(params.get("limit") or 100),
            ),
        }
    if action in ("refresh_contact_cache", "refresh_messages_cache"):
        from app.services.wechat_contact_cache_import import (
            ensure_decrypted_wechat_dbs as _ensure_decrypted_db,
        )

        return _ensure_decrypted_db()


def _registered_router_print(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if action == "workflow_label_dispatch":
        from app.application.print_app_service import get_print_application_service

        model_number = str(params.get("model_number") or "").strip()
        if not model_number:
            return {"success": False, "message": "model_number 不能为空"}
        quantity = max(1, min(100, int(params.get("quantity") or 1)))
        product_name = model_number
        specification: str | None = None
        unit = "个"
        try:
            from app.application import get_product_app_service

            products = get_product_app_service().search_products(keyword=model_number, limit=1)
            if products and isinstance(products, list):
                product = products[0]
                if isinstance(product, dict):
                    product_name = str(
                        product.get("name") or product.get("product_name") or model_number
                    )
                    specification = (
                        str(product.get("specification") or product.get("spec") or "") or None
                    )
                    unit = str(product.get("unit") or "个")
        except RECOVERABLE_ERRORS as lookup_err:
            logger.warning("print.workflow_label_dispatch: 产品查找失败: %s", lookup_err)
        return dict(
            get_print_application_service().print_single_label(
                product_name=product_name,
                model_number=model_number or None,
                specification=specification,
                unit=unit,
                quantity=quantity,
            )
            or {}
        )

    if str(runtime_context.get("service_source") or "") == "fastapi_print_route":
        from app.fastapi_routes import print_routes

        svc = print_routes._svc()
    else:
        from app.services import get_printer_service

        svc = get_printer_service()
    if action == "view":
        return {"success": True, "redirect": "/console?view=print"}
    if action in ("list", "query"):
        return svc.get_printers()
    if action == "print_label":
        return svc.print_label(
            str(params.get("file_path") or "").strip(),
            params.get("printer_name"),
            int(params.get("copies") or 1),
        )
    if action == "print_document":
        return svc.print_document(
            str(params.get("file_path") or "").strip(),
            params.get("printer_name"),
            bool(params.get("use_automation", False)),
        )
    if action == "test":
        return svc.test_printer(str(params.get("printer_name") or "").strip())
    if action == "save_printer_selection":
        document_printer = params.get("document_printer")
        label_printer = params.get("label_printer")
        printers_result = dict(svc.get_printers() or {})
        printers = printers_result.get("printers", [])
        if not isinstance(printers, list):
            printers = []
        available_names = {
            (printer.get("name") or "").strip() for printer in printers if isinstance(printer, dict)
        }

        def is_valid(name: Any) -> bool:
            if name is None:
                return True
            value = str(name).strip()
            return value == "" or value in available_names

        if not is_valid(document_printer):
            return {"success": False, "message": "发货单打印机不在当前可用打印机列表中"}
        if not is_valid(label_printer):
            return {"success": False, "message": "标签打印机不在当前可用打印机列表中"}
        result = dict(
            svc.save_printer_selection(
                document_printer=(
                    str(document_printer).strip() if document_printer is not None else None
                ),
                label_printer=str(label_printer).strip() if label_printer is not None else None,
            )
            or {}
        )
        result.update(dict(svc.classify_printers(printers) or {}))
        return result
    return {"success": False, "message": f"未注册的 print 动作: {action}"}


def _registered_router_printer_list(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    from app.services import get_system_service

    svc = get_system_service()
    if action == "view":
        return {"success": True, "redirect": "/console?view=printer-list"}
    if action in ("list", "query"):
        return svc.get_printer_config()
    if action == "set_default":
        return svc.set_default_printer(str(params.get("printer_name") or "").strip())


def _registered_router_settings(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    from app.services import get_system_service

    svc = get_system_service()
    if action == "view":
        return {"success": True, "redirect": "/console?view=settings"}
    if action in ("query", "get_system_info"):
        return {"success": True, "data": svc.get_system_info()}
    if action == "get_startup_config":
        return {"success": True, "data": svc.get_startup_config()}
    if action == "enable_startup":
        return svc.enable_startup()
    if action == "disable_startup":
        return svc.disable_startup()


def _registered_router_employee(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    from app.mod_sdk.employee_tool_registry import build_employee_tools_status

    if action in ("list", "query"):
        status = build_employee_tools_status()
        return {
            "success": True,
            "message": f"已发现 {status.get('registered_tool_count', 0)} 个可调用员工",
            "data": status,
        }

    if action != "execute":
        return {"success": False, "message": f"未注册的 employee 动作: {action}"}

    employee_id = str(
        params.get("employee_id")
        or params.get("pack_id")
        or params.get("tool_name")
        or params.get("id")
        or ""
    ).strip()
    status = build_employee_tools_status()
    installed = status.get("employee_pack_tools") or []

    if not employee_id and user_message:
        for item in installed:
            if not isinstance(item, dict):
                continue
            candidate = str(item.get("pack_id") or item.get("tool_name") or "").strip()
            if candidate and candidate in user_message:
                employee_id = candidate
                break

    if not employee_id:
        return {
            "success": False,
            "message": "缺少 employee_id，请先用 employee.list 查看可用员工，或明确指定员工包 ID。",
            "data": {
                "available_employee_ids": [
                    str(x.get("pack_id") or "")
                    for x in installed
                    if isinstance(x, dict) and x.get("pack_id")
                ][:80],
            },
        }

    task = str(
        params.get("task")
        or params.get("user_request")
        or params.get("message")
        or user_message
        or ""
    ).strip()
    if not task:
        return {"success": False, "message": "缺少 task：请说明要让员工执行什么任务。"}

    input_data = params.get("input") if isinstance(params.get("input"), dict) else {}
    payload = dict(input_data)
    for key, value in params.items():
        if key in {"employee_id", "pack_id", "tool_name", "id", "task", "user_request", "input"}:
            continue
        payload.setdefault(key, value)
    payload.setdefault("source", "workflow_tool.employee")
    payload.setdefault("user_message", user_message)

    workspace_root = (
        str(params.get("workspace_root") or runtime_context.get("workspace_root") or "").strip()
        or None
    )
    raw_user_id = params.get("user_id") or runtime_context.get("user_id") or 0
    try:
        numeric_user_id = int(raw_user_id)
    except (TypeError, ValueError):
        numeric_user_id = 0

    from app.application.employee_runtime.executor import execute_employee_task_local

    result = execute_employee_task_local(
        employee_id,
        task,
        payload,
        user_id=numeric_user_id,
        workspace_root=workspace_root,
        session_id=str(runtime_context.get("session_id") or params.get("session_id") or "") or None,
    )
    ok = bool(result.get("success")) and not bool(result.get("blocked_by_risk_gate"))
    return {
        "success": ok,
        "message": "员工执行完成" if ok else str(result.get("error") or "员工执行失败"),
        "employee_id": employee_id,
        "data": result,
    }


_BUSINESS_DB_ENTITY_ALIASES = {
    "customer": "customers",
    "customers": "customers",
    "purchase_unit": "customers",
    "purchase_units": "customers",
    "客户": "customers",
    "单位": "customers",
    "购买单位": "customers",
    "product": "products",
    "products": "products",
    "产品": "products",
    "物料": "materials",
    "原材料": "materials",
    "material": "materials",
    "materials": "materials",
    "shipment": "shipment_records",
    "shipments": "shipment_records",
    "shipment_record": "shipment_records",
    "shipment_records": "shipment_records",
    "出货": "shipment_records",
    "发货": "shipment_records",
    "发货单": "shipment_records",
}


def _normalize_business_db_entity(raw: Any, user_message: str = "") -> str:
    text = str(raw or "").strip()
    if text:
        lowered = text.lower()
        if lowered in _BUSINESS_DB_ENTITY_ALIASES:
            return _BUSINESS_DB_ENTITY_ALIASES[lowered]
        if text in _BUSINESS_DB_ENTITY_ALIASES:
            return _BUSINESS_DB_ENTITY_ALIASES[text]
    msg = str(user_message or "")
    for token, entity in _BUSINESS_DB_ENTITY_ALIASES.items():
        if token and token in msg:
            return entity
    return ""


def _registered_router_business_db(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    entity = _normalize_business_db_entity(params.get("entity"), user_message)
    if not entity:
        return {
            "success": False,
            "message": "缺少或不支持的 entity；允许 customers/products/materials/shipment_records。",
            "allowed_entities": ["customers", "products", "materials", "shipment_records"],
        }

    if any(k in params for k in ("sql", "raw_sql", "query_sql")):
        return {
            "success": False,
            "message": "business_db 不接受任意 SQL，请使用 entity/operation/payload。",
        }

    if action in ("read", "query", "list"):
        read_params = dict(params)
        read_params.setdefault("keyword", params.get("keyword") or params.get("query") or "")
        if entity == "customers":
            return facade_attr("_registered_router_customers", _default_router_customers)(
                "query", read_params, runtime_context, profile, user_message
            )
        if entity == "products":
            return facade_attr("_registered_router_products", _default_router_products)(
                "query", read_params, runtime_context, profile, user_message
            )
        if entity == "materials":
            return facade_attr("_registered_router_materials", _default_router_materials)(
                "query", read_params, runtime_context, profile, user_message
            )
        if entity == "shipment_records":
            return facade_attr("_registered_router_shipment_records", _default_router_shipment_records)(
                "query", read_params, runtime_context, profile, user_message
            )

    if action != "write":
        return {"success": False, "message": f"未注册的 business_db 动作: {action}"}

    operation = str(params.get("operation") or params.get("op") or "create").strip().lower()
    payload = params.get("payload")
    if not isinstance(payload, dict):
        return {"success": False, "message": "business_db.write 需要 dict payload。"}

    if entity == "customers":
        if operation in ("create", "ensure_exists", "upsert"):
            router_action = (
                "ensure_exists" if operation in ("ensure_exists", "upsert") else "create"
            )
            return facade_attr("_registered_router_customers", _default_router_customers)(
                router_action, payload, runtime_context, profile, user_message
            )
        return {"success": False, "message": "customers 仅支持 create/ensure_exists/upsert。"}

    if entity == "products":
        if operation == "create":
            return facade_attr("_registered_router_products", _default_router_products)(
                "create", payload, runtime_context, profile, user_message
            )
        return {"success": False, "message": "products 当前仅支持 create；查询请用 read。"}

    if entity == "materials":
        if operation in ("create", "update", "delete", "batch_delete"):
            return facade_attr("_registered_router_materials", _default_router_materials)(
                operation, payload, runtime_context, profile, user_message
            )
        return {"success": False, "message": "materials 支持 create/update/delete/batch_delete。"}

    if entity == "shipment_records":
        if operation in ("update", "delete"):
            return facade_attr(
                "_registered_router_shipment_records", _default_router_shipment_records
            )(
                operation, payload, runtime_context, profile, user_message
            )
        return {
            "success": False,
            "message": "shipment_records 支持 update/delete；生成发货单请用 shipment_generate。",
        }

    return {"success": False, "message": f"不支持的 entity: {entity}"}


