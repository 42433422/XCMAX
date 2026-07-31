"""Extracted helpers for an existing public module."""

from __future__ import annotations

from app.utils.mixin_module_sync import sync_module_functions


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
            return _registered_router_customers(
                "query", read_params, runtime_context, profile, user_message
            )
        if entity == "products":
            return _registered_router_products(
                "query", read_params, runtime_context, profile, user_message
            )
        if entity == "materials":
            return _registered_router_materials(
                "query", read_params, runtime_context, profile, user_message
            )
        if entity == "shipment_records":
            return _registered_router_shipment_records(
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
            return _registered_router_customers(
                router_action, payload, runtime_context, profile, user_message
            )
        return {"success": False, "message": "customers 仅支持 create/ensure_exists/upsert。"}

    if entity == "products":
        product_payload = dict(payload)
        if operation in ("update", "delete") and not (
            product_payload.get("id") or product_payload.get("product_id")
        ):
            return {
                "success": False,
                "message": f"products {operation} 需要 id。",
            }
        if operation == "create":
            labeled = re.search(
                r"新增产品\s*[：:]\s*(?P<name>.+?)\s+型号\s*[：:]\s*"
                r"(?P<model>[A-Za-z0-9][A-Za-z0-9._*\-/]*)",
                str(user_message or ""),
                flags=re.IGNORECASE,
            )
            if labeled:
                product_name = labeled.group("name").strip(" ，,。")
                model_number = labeled.group("model").strip()
                product_payload.setdefault("product_name", product_name)
                product_payload.setdefault("name", product_name)
                product_payload.setdefault("model_number", model_number)
                product_payload["name_or_model"] = str(
                    product_payload.get("product_name") or product_name
                ).strip()
        if operation == "create":
            return _registered_router_products(
                "create", product_payload, runtime_context, profile, user_message
            )
        if operation in ("update", "delete"):
            return _registered_router_products(
                operation, product_payload, runtime_context, profile, user_message
            )
        return {
            "success": False,
            "message": "products 支持 create/update/delete；查询请用 read。",
        }

    if entity == "materials":
        if operation in ("create", "update", "delete", "batch_delete"):
            return _registered_router_materials(
                operation, payload, runtime_context, profile, user_message
            )
        return {"success": False, "message": "materials 支持 create/update/delete/batch_delete。"}

    if entity == "shipment_records":
        if operation in ("update", "delete"):
            return _registered_router_shipment_records(
                operation, payload, runtime_context, profile, user_message
            )
        return {
            "success": False,
            "message": "shipment_records 支持 update/delete；生成发货单请用 shipment_generate。",
        }

    return {"success": False, "message": f"不支持的 entity: {entity}"}


sync_module_functions(
    target=globals(),
    source_module="app.services.tools_workflow_registered",
    function_names=("_registered_router_business_db",),
)
