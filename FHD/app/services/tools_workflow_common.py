# mypy: disable-error-code="no-any-return"
"""工作流工具共享层：业务库实体别名、近期写入目标状态与纯 helper（叶子模块，禁止反向依赖路由模块）。"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


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


_BUSINESS_DB_CONTROL_FIELDS = frozenset(
    {"selector", "changes", "fields", "force", "confirm", "_selector_field", "_resolved_target"}
)


_RECENT_BUSINESS_DB_TARGETS: dict[str, dict[str, Any]] = {}


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


def get_recent_business_db_target(user_id: object) -> dict[str, Any] | None:
    target = _RECENT_BUSINESS_DB_TARGETS.get(str(user_id or "").strip())
    return dict(target) if target is not None else None


def _business_db_payload_contains_key(value: Any, forbidden: set[str]) -> bool:
    """Reject forbidden controls even when a model nests them in changes/fields/selector."""
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).strip().lower() in forbidden:
                return True
            if _business_db_payload_contains_key(nested, forbidden):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_business_db_payload_contains_key(item, forbidden) for item in value)
    return False


def _result_record_id(value: Any) -> int | None:
    if not isinstance(value, dict):
        return None
    raw_id = value.get("id") or value.get("product_id") or value.get("record_id")
    if raw_id not in (None, ""):
        try:
            parsed = int(raw_id)
        except (TypeError, ValueError):
            parsed = 0
        if parsed > 0:
            return parsed
    for key in ("data", "raw", "shipment", "result"):
        nested_id = _result_record_id(value.get(key))
        if nested_id:
            return nested_id
    return None


def _business_db_selector(payload: dict[str, Any]) -> dict[str, Any]:
    nested = payload.get("selector")
    selector = dict(nested) if isinstance(nested, dict) else {}
    for key in (
        "id",
        "customer_id",
        "record_id",
        "order_number",
        "customer_name",
        "unit_name",
        "name",
        "product_name",
        "name_or_model",
        "model_number",
        "material_name",
        "material_code",
    ):
        if key not in selector and payload.get(key) not in (None, ""):
            selector[key] = payload.get(key)
    return selector


def _business_db_target_candidates(
    entity: str, selector: dict[str, Any]
) -> tuple[list[dict[str, Any]], str]:
    """Resolve an exact target inside the active tenant scope.

    All involved models inherit TenantScopedMixin, and apply_tenant_filter is repeated here as
    defense in depth.  No fuzzy write target is ever accepted.
    """
    from app.db.session import get_db
    from app.infrastructure.tenant_scope import apply_tenant_filter

    raw_id = (
        selector.get("id")
        or selector.get("customer_id")
        or selector.get("record_id")
        or selector.get("order_number")
    )
    numeric_id = 0
    if raw_id not in (None, ""):
        try:
            numeric_id = int(raw_id)
        except (TypeError, ValueError):
            return ([], "id")
        if numeric_id <= 0:
            return ([], "id")
    with get_db() as db:
        if entity == "customers":
            from app.db.models.purchase_unit import PurchaseUnit

            query = apply_tenant_filter(db.query(PurchaseUnit), PurchaseUnit)
            selector_field = "id"
            if numeric_id:
                query = query.filter(PurchaseUnit.id == numeric_id)
            else:
                value = str(
                    selector.get("customer_name")
                    or selector.get("unit_name")
                    or selector.get("name")
                    or ""
                ).strip()
                if not value:
                    return ([], "")
                selector_field = next(
                    (
                        key
                        for key in ("customer_name", "unit_name", "name")
                        if selector.get(key) not in (None, "")
                    ),
                    "customer_name",
                )
                query = query.filter(PurchaseUnit.unit_name == value)
            rows = query.order_by(PurchaseUnit.id.asc()).limit(21).all()
            return (
                [
                    {"id": row.id, "customer_name": row.unit_name, "name": row.unit_name}
                    for row in rows
                ],
                selector_field,
            )
        if entity == "products":
            from app.db.models.product import Product

            query = apply_tenant_filter(db.query(Product), Product)
            selector_field = "id"
            if numeric_id:
                query = query.filter(Product.id == numeric_id)
            else:
                model_number = str(selector.get("model_number") or "").strip().upper()
                name = str(
                    selector.get("product_name")
                    or selector.get("name")
                    or selector.get("name_or_model")
                    or ""
                ).strip()
                if model_number:
                    selector_field = "model_number"
                    query = query.filter(Product.model_number == model_number)
                elif name:
                    selector_field = next(
                        (
                            key
                            for key in ("product_name", "name", "name_or_model")
                            if selector.get(key) not in (None, "")
                        ),
                        "name",
                    )
                    query = query.filter(Product.name == name)
                else:
                    return ([], "")
            rows = query.order_by(Product.id.asc()).limit(21).all()
            return (
                [
                    {
                        "id": row.id,
                        "name": row.name,
                        "product_name": row.name,
                        "model_number": row.model_number or "",
                    }
                    for row in rows
                ],
                selector_field,
            )
        if entity == "materials":
            from app.db.models.material import Material

            query = apply_tenant_filter(db.query(Material), Material)
            selector_field = "id"
            if numeric_id:
                query = query.filter(Material.id == numeric_id)
            else:
                code = str(selector.get("material_code") or "").strip()
                name = str(selector.get("material_name") or selector.get("name") or "").strip()
                if code:
                    selector_field = "material_code"
                    query = query.filter(Material.material_code == code)
                elif name:
                    selector_field = "material_name" if selector.get("material_name") else "name"
                    query = query.filter(Material.name == name)
                else:
                    return ([], "")
            rows = query.order_by(Material.id.asc()).limit(21).all()
            return (
                [
                    {
                        "id": row.id,
                        "name": row.name,
                        "material_name": row.name,
                        "material_code": row.material_code,
                    }
                    for row in rows
                ],
                selector_field,
            )
        if entity == "shipment_records":
            from app.db.models.shipment import ShipmentRecord

            if not numeric_id:
                return ([], "")
            rows = (
                apply_tenant_filter(db.query(ShipmentRecord), ShipmentRecord)
                .filter(ShipmentRecord.id == numeric_id)
                .order_by(ShipmentRecord.id.asc())
                .limit(2)
                .all()
            )
            return (
                [
                    {
                        "id": row.id,
                        "name": f"{row.purchase_unit} / {row.product_name}",
                        "purchase_unit": row.purchase_unit,
                        "product_name": row.product_name,
                    }
                    for row in rows
                ],
                "id",
            )
    return ([], "")


def prepare_business_db_write_target(
    entity: str, operation: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Resolve update/delete targets without mutating business data.

    The result is shared by the clarification gate and the final dispatcher, so approval previews
    and execution use the same exact, tenant-scoped target.
    """
    normalized = dict(payload or {})
    if operation not in {"update", "delete"}:
        return {"success": True, "payload": normalized}
    if bool(normalized.get("force")):
        return {
            "success": False,
            "reason": "force_not_allowed",
            "message": "智能对话不允许 force 删除；请先处理关联数据。",
        }
    selector = _business_db_selector(normalized)
    candidates, selector_field = _business_db_target_candidates(entity, selector)
    if not selector_field:
        return {
            "success": False,
            "reason": "missing_target",
            "message": "更新或删除必须提供当前租户内的唯一 ID 或受支持的精确自然键。",
            "candidates": [],
        }
    if not candidates:
        return {
            "success": False,
            "reason": "target_not_found",
            "message": "当前租户内未找到目标记录，未执行写入。",
            "candidates": [],
        }
    if len(candidates) > 1:
        return {
            "success": False,
            "reason": "ambiguous_target",
            "message": "精确条件匹配到多条记录，请选择唯一 ID。",
            "candidates": candidates,
        }
    target = candidates[0]
    normalized["id"] = int(target["id"])
    normalized["_selector_field"] = selector_field
    normalized["_resolved_target"] = target
    return {"success": True, "payload": normalized, "target": target}


def _remember_business_db_target(
    runtime_context: dict[str, Any],
    entity: str,
    operation: str,
    payload: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    if not result.get("success") or operation == "delete":
        return result
    target_id = _result_record_id(result) or _result_record_id(payload)
    if not target_id and operation in {"create", "ensure_exists", "upsert"}:
        candidates, _ = _business_db_target_candidates(entity, _business_db_selector(payload))
        if len(candidates) == 1:
            target_id = int(candidates[0]["id"])
    user_id = str(runtime_context.get("user_id") or "").strip()
    if user_id and target_id:
        _RECENT_BUSINESS_DB_TARGETS[user_id] = {"entity": entity, "id": int(target_id)}
    return result


_DEFAULT_PREPARE_BUSINESS_DB_WRITE_TARGET = prepare_business_db_write_target


def _business_db_update_fields(payload: dict[str, Any]) -> dict[str, Any]:
    nested = payload.get("changes")
    if not isinstance(nested, dict):
        nested = payload.get("fields")
    if isinstance(nested, dict):
        return {k: v for k, v in nested.items() if k not in _BUSINESS_DB_CONTROL_FIELDS}
    selector_field = str(payload.get("_selector_field") or "")
    return {
        key: value
        for key, value in payload.items()
        if key not in _BUSINESS_DB_CONTROL_FIELDS
        and key not in {"id", "customer_id", "record_id", "order_number"}
        and (key != selector_field)
    }
