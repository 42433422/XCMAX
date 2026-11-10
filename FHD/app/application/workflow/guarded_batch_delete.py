"""Apply a preview-bound bulk delete under a single database write lock."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


def execute_guarded_batch_delete(
    *, tool_id: str, action: str, params: dict[str, Any]
) -> dict[str, Any]:
    from app.db.models import Product
    from app.db.models.purchase_unit import PurchaseUnit
    from app.db.models.shipment import ShipmentRecord
    from app.db.session import get_db
    from app.infrastructure.tenant_scope import current_tenant_id

    context = params.get("_runtime_context") or {}
    preview = context.get("_bulk_preview_scope") or {}
    ids = params.get("ids")
    tenant = current_tenant_id()
    if (
        tool_id not in {"customers", "products"}
        or action != "batch_delete"
        or not isinstance(preview, dict)
        or preview.get("tool") != tool_id
        or not isinstance(ids, list)
        or not ids
        or any(type(i) is not int or i <= 0 for i in ids)
        or not tenant
        or str(tenant) != str(context.get("tenant_id"))
    ):
        return {"success": False, "message": "删除范围未获授权"}
    model = Product if tool_id == "products" else PurchaseUnit
    try:
        with get_db() as db:
            dialect = db.get_bind().dialect.name
            if dialect == "sqlite":
                db.execute(text("BEGIN IMMEDIATE"))
            elif dialect == "postgresql":
                statement = (
                    "LOCK TABLE products IN SHARE ROW EXCLUSIVE MODE"
                    if tool_id == "products"
                    else "LOCK TABLE purchase_units IN SHARE ROW EXCLUSIVE MODE"
                )
                db.execute(text(statement))
                if tool_id == "customers":
                    db.execute(text("LOCK TABLE shipment_records IN SHARE ROW EXCLUSIVE MODE"))
            else:
                return {"success": False, "message": "数据库不支持安全批量删除"}
            rows = list(
                db.query(*model.__table__.columns)
                .filter(model.tenant_id == tenant)
                .order_by(model.id)
            )
            digest = hashlib.sha256()
            for row in rows:
                digest.update(
                    json.dumps(
                        tuple(row), ensure_ascii=False, default=str, separators=(",", ":")
                    ).encode()
                )
                digest.update(b"\n")
            actual = {row.id for row in rows}
            if (
                digest.hexdigest() != preview.get("digest")
                or len(ids) != len(actual)
                or set(ids) != actual
            ):
                return {"success": False, "message": "删除范围已变化，请重新预览"}
            entities = db.query(model).filter(model.tenant_id == tenant, model.id.in_(ids)).all()
            if tool_id == "customers":
                names = [entity.unit_name for entity in entities]
                if (
                    db.query(ShipmentRecord.id)
                    .filter(
                        ShipmentRecord.tenant_id == tenant, ShipmentRecord.purchase_unit.in_(names)
                    )
                    .first()
                ):
                    return {"success": False, "message": "客户存在关联发货记录，未删除"}
            for entity in entities:
                db.delete(entity)
            db.flush()
            deleted = len(entities)
        if tool_id == "products":
            from app.services import get_products_service

            service = get_products_service()
            for product_id in ids:
                service._invalidate_single_product_cache(product_id)
        return {"success": True, "deleted_count": deleted}
    except (SQLAlchemyError, ValueError, TypeError):
        return {"success": False, "message": "删除结果未确认，请核对业务数据"}
