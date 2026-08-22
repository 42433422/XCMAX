# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.services.tools_workflow_registered")


def _business_db_update_fields(payload: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    nested = payload.get("changes")
    if not isinstance(nested, dict):
        nested = payload.get("fields")
    if isinstance(nested, dict):
        return {k: v for k, v in nested.items() if k not in _facade()._BUSINESS_DB_CONTROL_FIELDS}
    selector_field = str(payload.get("_selector_field") or "")
    return {
        key: value
        for key, value in payload.items()
        if key not in _facade()._BUSINESS_DB_CONTROL_FIELDS
        and key not in {"id", "customer_id", "record_id", "order_number"}
        and (key != selector_field)
    }


def _registered_router_business_db(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    entity = _facade()._normalize_business_db_entity(params.get("entity"), user_message)
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
            return _facade()._registered_router_customers(
                "query", read_params, runtime_context, profile, user_message
            )
        if entity == "products":
            return _facade()._registered_router_products(
                "query", read_params, runtime_context, "admin", user_message
            )
        if entity == "materials":
            return _facade()._registered_router_materials(
                "query", read_params, runtime_context, profile, user_message
            )
        if entity == "shipment_records":
            return _facade()._registered_router_shipment_records(
                "query", read_params, runtime_context, profile, user_message
            )
    if action != "write":
        return {"success": False, "message": f"未注册的 business_db 动作: {action}"}
    operation = str(params.get("operation") or params.get("op") or "create").strip().lower()
    payload = params.get("payload")
    if not isinstance(payload, dict):
        return {"success": False, "message": "business_db.write 需要 dict payload。"}
    if _facade()._business_db_payload_contains_key(payload, {"sql", "raw_sql", "query_sql"}):
        return {
            "success": False,
            "message": "business_db 不接受任意 SQL，请使用 entity/operation/payload。",
        }
    if _facade()._business_db_payload_contains_key(payload, {"tenant_id"}):
        return {"success": False, "message": "tenant_id 只能来自当前登录会话，拒绝跨租户目标。"}
    try:
        from app.infrastructure.tenant_scope import tenant_id_for_write

        tenant_id_for_write()
    except _facade().RECOVERABLE_ERRORS as exc:
        return {"success": False, "message": f"缺少有效租户上下文，拒绝写入：{exc}"}
    # Preserve both historical patch seams: direct callers patch this extracted
    # function's globals, while integration callers patch the public facade.
    prepare_target = globals().get(
        "prepare_business_db_write_target", _facade().prepare_business_db_write_target
    )
    prepared = prepare_target(entity, operation, payload)
    if not prepared.get("success"):
        return dict(prepared)
    payload = dict(prepared.get("payload") or {})

    def verified(result: dict) -> dict:
        from app.application.business_db_write_verification import verify_business_db_write

        return verify_business_db_write(
            entity=entity,
            operation=operation,
            payload=payload,
            result=result,
        )

    if entity == "customers":
        if operation in ("create", "ensure_exists", "upsert"):
            return verified(
                _facade()._registered_router_customers(
                    operation, payload, runtime_context, profile, user_message
                )
            )
        if operation == "update":
            fields = _facade()._business_db_update_fields(payload)
            if not fields:
                return {"success": False, "message": "customers.update 缺少 changes/fields。"}
            return verified(
                _facade()._registered_router_customers(
                    "update",
                    {"id": payload["id"], **fields},
                    runtime_context,
                    profile,
                    user_message,
                )
            )
        if operation == "delete":
            return verified(
                _facade()._registered_router_customers(
                    "delete",
                    {"id": payload["id"], "force": False},
                    runtime_context,
                    profile,
                    user_message,
                )
            )
        return {
            "success": False,
            "message": "customers 支持 create/ensure_exists/upsert/update/delete。",
        }
    if entity == "products":
        if operation == "create":
            return verified(
                _facade()._registered_router_products(
                    "create", payload, runtime_context, profile, user_message
                )
            )
        if operation == "update":
            fields = _facade()._business_db_update_fields(payload)
            if not fields:
                return {"success": False, "message": "products.update 缺少 changes/fields。"}
            return verified(
                _facade()._registered_router_products(
                    "update",
                    {"id": payload["id"], **fields},
                    runtime_context,
                    profile,
                    user_message,
                )
            )
        if operation == "delete":
            return verified(
                _facade()._registered_router_products(
                    "delete", {"id": payload["id"]}, runtime_context, profile, user_message
                )
            )
        return {"success": False, "message": "products 支持 create/update/delete；查询请用 read。"}
    if entity == "materials":
        if operation == "create":
            return verified(
                _facade()._registered_router_materials(
                    "create", payload, runtime_context, profile, user_message
                )
            )
        if operation == "update":
            fields = _facade()._business_db_update_fields(payload)
            if not fields:
                return {"success": False, "message": "materials.update 缺少 changes/fields。"}
            return verified(
                _facade()._registered_router_materials(
                    "update",
                    {"id": payload["id"], **fields},
                    runtime_context,
                    profile,
                    user_message,
                )
            )
        if operation == "delete":
            result = _facade()._registered_router_materials(
                "delete", {"id": payload["id"]}, runtime_context, profile, user_message
            )
            if result.get("success"):
                from app.db.models.material import Material
                from app.db.session import get_db
                from app.infrastructure.tenant_scope import tenant_id_for_write

                with get_db() as db:
                    deleted = (
                        db.query(Material)
                        .filter(
                            Material.id == int(payload["id"]),
                            Material.tenant_id == tenant_id_for_write(),
                        )
                        .delete(synchronize_session=False)
                    )
                if deleted != 1:
                    return {
                        "success": False,
                        "message": "原材料软删除后物理清理未命中唯一租户记录。",
                    }
            return verified(result)
        return {"success": False, "message": "materials 支持 create/update/delete。"}
    if entity == "shipment_records":
        if operation == "create":
            return verified(
                _facade()._registered_router_shipment_records(
                    "create", payload, runtime_context, profile, user_message
                )
            )
        if operation == "update":
            fields = _facade()._business_db_update_fields(payload)
            if not fields:
                return {
                    "success": False,
                    "message": "shipment_records.update 缺少 changes/fields。",
                }
            return verified(
                _facade()._registered_router_shipment_records(
                    "update",
                    {"id": payload["id"], **fields},
                    runtime_context,
                    profile,
                    user_message,
                )
            )
        if operation == "delete":
            return verified(
                _facade()._registered_router_shipment_records(
                    "delete", {"id": payload["id"]}, runtime_context, profile, user_message
                )
            )
        return {"success": False, "message": "shipment_records 支持 create/update/delete。"}
    return {"success": False, "message": f"不支持的 entity: {entity}"}
