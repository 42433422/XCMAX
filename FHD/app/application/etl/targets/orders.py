"""Purchase order and shipment ETL target adapters."""

from __future__ import annotations

import hashlib
import json
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import or_

from app.application.etl.errors import EtlError
from app.application.etl.targets.base import (
    PreviewDecision,
    TargetAdapter,
    TargetField,
    json_safe,
)
from app.application.etl.targets.helpers import (
    assert_snapshot_unchanged,
    decimal_or_zero,
    issue,
    optional_text,
    parse_date,
)
from app.db.models.product import Product
from app.db.models.purchase import PurchaseOrder, PurchaseOrderItem, Supplier
from app.db.models.shipment import ShipmentRecord
from app.infrastructure.tenant_scope import tenant_id_for_write


def _ranked_names(value: Any, candidates: list[str]) -> list[str]:
    incoming = str(value or "").strip().casefold()
    if not incoming:
        return []
    ranked = sorted(
        (
            (SequenceMatcher(None, incoming, candidate.casefold()).ratio(), candidate)
            for candidate in candidates
            if candidate
        ),
        reverse=True,
    )
    return [candidate for score, candidate in ranked[:3] if score >= 0.45]


def _cached_master_names(db: Any, context: dict[str, Any], model: Any, key: str) -> list[str]:
    cache = context.get("_preview_cache")
    cache_key = f"purchase_order_master_names:{key}"
    if isinstance(cache, dict) and cache_key in cache:
        return list(cache[cache_key])
    names = [
        str(row[0] or "").strip()
        for row in db.query(model.name).filter(model.name.isnot(None)).limit(500).all()
        if str(row[0] or "").strip()
    ]
    if isinstance(cache, dict):
        cache[cache_key] = names
    return names


def _candidate_message(label: str, candidates: list[str]) -> str:
    if not candidates:
        return f"{label}不存在"
    return f"{label}没有唯一匹配；候选：{'、'.join(candidates)}。请确认或先补全主数据"


class PurchaseOrderAdapter(TargetAdapter):
    type = "purchase_orders"
    label = "采购订单"
    reversible = True
    fields = (
        TargetField(
            "external_order_no", "外部订单号", required=True, aliases=("订单号", "采购单号")
        ),
        TargetField(
            "supplier_name",
            "供应商",
            required=True,
            aliases=("供应商", "供应商名称", "供方", "供货商"),
        ),
        TargetField(
            "order_date",
            "订单日期",
            type="date",
            required=True,
            aliases=("日期", "订单日期", "下单日期", "下单日"),
        ),
        TargetField("product_model", "产品型号", aliases=("型号", "产品型号")),
        TargetField("product_name", "产品名称", required=True, aliases=("品名", "产品")),
        TargetField(
            "quantity",
            "数量",
            type="number",
            required=True,
            aliases=("数量", "采购数量"),
        ),
        TargetField("unit", "单位", aliases=("单位", "计量单位")),
        TargetField("unit_price", "单价", type="number", aliases=("单价", "价格")),
    )
    default_match_keys = ("external_order_no",)

    def preview(self, db, data, *, allowed_update_fields, context):
        issues = self.validate(data)
        order = (
            db.query(PurchaseOrder)
            .filter(PurchaseOrder.order_no == str(data.get("external_order_no") or ""))
            .first()
        )
        if order:
            return PreviewDecision(
                "skip",
                match_ref=str(order.id),
                before={"id": order.id, "external_order_no": order.order_no},
                reason="existing_order_v1_no_update",
                issues=issues,
            )
        supplier_matches = (
            db.query(Supplier)
            .filter(Supplier.name == str(data.get("supplier_name")))
            .limit(2)
            .all()
        )
        supplier = supplier_matches[0] if len(supplier_matches) == 1 else None
        product_query = db.query(Product)
        model = str(data.get("product_model") or "").strip()
        product_matches = (
            product_query.filter(Product.model_number == model).limit(2).all()
            if model
            else product_query.filter(Product.name == str(data.get("product_name"))).limit(2).all()
        )
        product = product_matches[0] if len(product_matches) == 1 else None
        if len(supplier_matches) > 1:
            issues.append(
                issue(
                    "ETL_SUPPLIER_MATCH_AMBIGUOUS",
                    "supplier_name",
                    "同名供应商不唯一，请先合并或明确主数据",
                )
            )
        elif not supplier:
            supplier_candidates = _ranked_names(
                data.get("supplier_name"),
                _cached_master_names(db, context, Supplier, "supplier"),
            )
            issues.append(
                issue(
                    (
                        "ETL_SUPPLIER_MATCH_CANDIDATES"
                        if supplier_candidates
                        else "ETL_SUPPLIER_NOT_FOUND"
                    ),
                    "supplier_name",
                    _candidate_message("供应商", supplier_candidates),
                )
            )
        if len(product_matches) > 1:
            issues.append(
                issue(
                    "ETL_PRODUCT_MATCH_AMBIGUOUS",
                    "product_name",
                    "产品主数据匹配到多条记录，请补充型号或整理重复主数据",
                )
            )
        elif not product:
            product_candidates = _ranked_names(
                data.get("product_name"),
                _cached_master_names(db, context, Product, "product"),
            )
            issues.append(
                issue(
                    (
                        "ETL_PRODUCT_MATCH_CANDIDATES"
                        if product_candidates
                        else "ETL_PRODUCT_NOT_FOUND"
                    ),
                    "product_name",
                    _candidate_message("产品", product_candidates),
                )
            )
        if issues:
            return PreviewDecision("error", issues=issues, reason="reference_missing")
        return PreviewDecision(
            "new",
            after={**json_safe(data), "_supplier_id": supplier.id, "_product_id": product.id},
            reason="new_purchase_order",
        )

    def execute_row(self, db, data, *, action, match_ref, allowed_update_fields, context):
        order_no = str(data["external_order_no"])
        order = db.query(PurchaseOrder).filter(PurchaseOrder.order_no == order_no).first()
        created = False
        if not order:
            suppliers = (
                db.query(Supplier)
                .filter(Supplier.name == str(data["supplier_name"]))
                .limit(2)
                .all()
            )
            if len(suppliers) != 1:
                raise EtlError(
                    "ETL_SUPPLIER_MATCH_CHANGED",
                    "执行时供应商已不再是唯一匹配，请重新预演",
                )
            supplier = suppliers[0]
            order = PurchaseOrder(
                tenant_id=tenant_id_for_write(),
                order_no=order_no,
                supplier_id=supplier.id,
                order_date=parse_date(data["order_date"]),
                status="draft",
            )
            db.add(order)
            db.flush()
            created = True
        model = str(data.get("product_model") or "").strip()
        query = db.query(Product)
        products = (
            query.filter(Product.model_number == model).limit(2).all()
            if model
            else query.filter(Product.name == str(data["product_name"])).limit(2).all()
        )
        if len(products) != 1:
            raise EtlError(
                "ETL_PRODUCT_MATCH_CHANGED",
                "执行时产品已不再是唯一匹配，请重新预演",
            )
        product = products[0]
        quantity = decimal_or_zero(data.get("quantity"))
        unit_price = decimal_or_zero(data.get("unit_price"))
        item = PurchaseOrderItem(
            tenant_id=tenant_id_for_write(),
            order_id=order.id,
            product_id=product.id,
            product_name=product.name,
            specification=product.specification,
            quantity=quantity,
            unit=str(data.get("unit") or product.unit or "个"),
            unit_price=unit_price,
            amount=quantity * unit_price,
            status="pending",
        )
        db.add(item)
        db.flush()
        return {
            "match_ref": str(item.id),
            "after": {
                "order_id": order.id,
                "item_id": item.id,
                "order_created": created,
                "order_snapshot": {
                    "order_no": order.order_no,
                    "supplier_id": order.supplier_id,
                    "order_date": order.order_date,
                    "status": order.status,
                },
                "item_snapshot": {
                    "order_id": item.order_id,
                    "product_id": item.product_id,
                    "product_name": item.product_name,
                    "specification": item.specification,
                    "quantity": item.quantity,
                    "unit": item.unit,
                    "unit_price": item.unit_price,
                    "amount": item.amount,
                    "received_quantity": item.received_quantity,
                    "invoiced_quantity": item.invoiced_quantity,
                    "status": item.status,
                    "remark": item.remark,
                },
            },
        }

    def rollback_row(self, db, *, match_ref, before, after, context):
        item = db.get(PurchaseOrderItem, int(match_ref))
        order_id = int(after.get("order_id") or 0)
        if item:
            assert_snapshot_unchanged(
                item,
                after.get("item_snapshot") or {},
                "采购订单明细",
            )
            db.delete(item)
            db.flush()
        if after.get("order_created") and order_id:
            remaining = (
                db.query(PurchaseOrderItem).filter(PurchaseOrderItem.order_id == order_id).count()
            )
            if remaining == 0:
                order = db.get(PurchaseOrder, order_id)
                if order:
                    assert_snapshot_unchanged(
                        order,
                        after.get("order_snapshot") or {},
                        "采购订单",
                    )
                    db.delete(order)


from app.application.etl.targets.shipments import ShipmentAdapter

__all__ = ["PurchaseOrderAdapter", "ShipmentAdapter"]
