"""Purchase order and shipment ETL target adapters."""

from __future__ import annotations

import hashlib
import json
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
        supplier = (
            db.query(Supplier).filter(Supplier.name == str(data.get("supplier_name"))).first()
        )
        product_query = db.query(Product)
        model = str(data.get("product_model") or "").strip()
        product = (
            product_query.filter(Product.model_number == model).first()
            if model
            else product_query.filter(Product.name == str(data.get("product_name"))).first()
        )
        if not supplier:
            issues.append(issue("ETL_SUPPLIER_NOT_FOUND", "supplier_name", "供应商不存在"))
        if not product:
            issues.append(issue("ETL_PRODUCT_NOT_FOUND", "product_name", "产品不存在"))
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
            supplier = (
                db.query(Supplier).filter(Supplier.name == str(data["supplier_name"])).first()
            )
            if not supplier:
                raise EtlError("ETL_SUPPLIER_NOT_FOUND", "供应商不存在")
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
        product = (
            query.filter(Product.model_number == model).first()
            if model
            else query.filter(Product.name == str(data["product_name"])).first()
        )
        if not product:
            raise EtlError("ETL_PRODUCT_NOT_FOUND", "产品不存在")
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


class ShipmentAdapter(TargetAdapter):
    type = "shipment_records"
    label = "发货记录"
    reversible = True
    fields = (
        TargetField(
            "purchase_unit", "购买单位", required=True, aliases=("购货单位", "客户", "单位")
        ),
        TargetField("external_order_no", "外部单号", aliases=("单号", "订单号")),
        TargetField("source_fingerprint", "源单据指纹", aliases=("源指纹",)),
        TargetField("legacy_note_fingerprint", "兼容单据指纹", aliases=("兼容指纹",)),
        TargetField("product_name", "产品名称", required=True, aliases=("品名", "产品")),
        TargetField("model_number", "型号", aliases=("型号",)),
        TargetField("quantity_kg", "公斤数", type="number", aliases=("重量", "公斤", "kg")),
        TargetField("quantity_tins", "桶数", type="integer", aliases=("桶数", "数量")),
        TargetField("tin_spec", "桶规格", type="number", aliases=("桶规格",)),
        TargetField("unit_price", "单价", type="number", aliases=("单价",)),
        TargetField("amount", "金额", type="number", aliases=("金额", "合计")),
    )
    default_match_keys = ("source_fingerprint", "external_order_no")

    def _fingerprint(self, data: dict[str, Any], context: dict[str, Any]) -> str:
        supplied = str(data.get("source_fingerprint") or "").strip()
        if supplied:
            return supplied
        payload = {
            "file": context.get("file_sha256"),
            "order": data.get("external_order_no"),
            "unit": data.get("purchase_unit"),
            "product": data.get("product_name"),
            "model": data.get("model_number"),
            "kg": data.get("quantity_kg"),
            "tins": data.get("quantity_tins"),
            "row": context.get("source_row"),
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
        ).hexdigest()

    def preview(self, db, data, *, allowed_update_fields, context):
        issues = self.validate(data)
        if data.get("quantity_kg") in (None, "") and data.get("quantity_tins") in (None, ""):
            issues.append(issue("ETL_QUANTITY_REQUIRED", "quantity_kg", "公斤数或桶数至少填写一项"))
        if issues:
            return PreviewDecision("error", issues=issues, reason="validation_failed")
        fingerprint = self._fingerprint(data, context)
        from app.db.models.shipment_etl_fingerprint import ShipmentEtlImportFingerprint

        tenant_key = f"tenant:{tenant_id_for_write()}"
        existing_fp = (
            db.query(ShipmentEtlImportFingerprint)
            .filter(
                ShipmentEtlImportFingerprint.tenant_key == tenant_key,
                ShipmentEtlImportFingerprint.fingerprint == fingerprint,
            )
            .first()
        )
        if existing_fp:
            return PreviewDecision(
                "skip",
                match_ref=str(existing_fp.shipment_id or ""),
                reason="legacy_fingerprint_duplicate",
            )
        legacy_note_fingerprint = str(data.get("legacy_note_fingerprint") or "").strip()
        if legacy_note_fingerprint:
            legacy_note_match = (
                db.query(ShipmentEtlImportFingerprint)
                .filter(
                    ShipmentEtlImportFingerprint.tenant_key == tenant_key,
                    ShipmentEtlImportFingerprint.fingerprint == legacy_note_fingerprint,
                )
                .first()
            )
            if legacy_note_match:
                return PreviewDecision(
                    "skip",
                    match_ref=str(legacy_note_match.shipment_id or ""),
                    reason="legacy_note_fingerprint_duplicate",
                )
        order_no = str(data.get("external_order_no") or "").strip()
        legacy_query = db.query(ShipmentEtlImportFingerprint).filter(
            ShipmentEtlImportFingerprint.tenant_key == tenant_key,
            or_(
                ShipmentEtlImportFingerprint.source_kind.is_(None),
                ShipmentEtlImportFingerprint.source_kind != "general_etl",
            ),
        )
        if order_no:
            legacy_query = legacy_query.filter(
                ShipmentEtlImportFingerprint.order_number == order_no
            )
        else:
            legacy_query = legacy_query.filter(
                ShipmentEtlImportFingerprint.file_name == str(context.get("file_name") or ""),
                ShipmentEtlImportFingerprint.unit_name == str(data.get("purchase_unit") or ""),
            )
        legacy_match = legacy_query.first()
        if legacy_match:
            return PreviewDecision(
                "skip",
                match_ref=str(legacy_match.shipment_id or ""),
                reason="legacy_source_duplicate",
            )
        if order_no:
            existing = (
                db.query(ShipmentRecord)
                .filter(
                    or_(
                        ShipmentRecord.parsed_data.contains(
                            f'"external_order_no": "{order_no}"',
                            autoescape=True,
                        ),
                        ShipmentRecord.raw_text.contains(
                            f"external_order_number={order_no}",
                            autoescape=True,
                        ),
                    )
                )
                .first()
            )
            if existing:
                return PreviewDecision(
                    "skip", match_ref=str(existing.id), reason="external_order_duplicate"
                )
        return PreviewDecision(
            "new",
            after={**json_safe(data), "_fingerprint": fingerprint},
            reason="new_shipment",
        )

    def execute_row(self, db, data, *, action, match_ref, allowed_update_fields, context):
        fingerprint = self._fingerprint(data, context)
        current = self.preview(
            db,
            data,
            allowed_update_fields=allowed_update_fields,
            context=context,
        )
        if current.action != "new":
            raise EtlError(
                "ETL_MATCH_CHANGED",
                "发货记录在预演后已存在，请重新预演",
                status_code=409,
            )
        parsed = {
            "external_order_no": data.get("external_order_no"),
            "etl_run_id": context.get("run_id"),
            "etl_fingerprint": fingerprint,
        }
        quantity_kg = float(decimal_or_zero(data.get("quantity_kg")))
        quantity_tins = int(decimal_or_zero(data.get("quantity_tins")))
        obj = ShipmentRecord(
            tenant_id=tenant_id_for_write(),
            purchase_unit=str(data["purchase_unit"]),
            product_name=str(data["product_name"]),
            model_number=optional_text(data.get("model_number")),
            quantity_kg=quantity_kg,
            quantity_tins=quantity_tins,
            tin_spec=float(decimal_or_zero(data.get("tin_spec"))) or None,
            unit_price=decimal_or_zero(data.get("unit_price")),
            amount=decimal_or_zero(data.get("amount")),
            status="pending",
            raw_text=json.dumps(json_safe(data), ensure_ascii=False),
            parsed_data=json.dumps(parsed, ensure_ascii=False),
        )
        db.add(obj)
        db.flush()
        from app.db.models.shipment_etl_fingerprint import ShipmentEtlImportFingerprint

        db.add(
            ShipmentEtlImportFingerprint(
                tenant_key=f"tenant:{tenant_id_for_write()}",
                fingerprint=fingerprint,
                shipment_id=obj.id,
                unit_name=obj.purchase_unit,
                order_number=optional_text(data.get("external_order_no")),
                file_name=str(context.get("file_name") or ""),
                source_kind="general_etl",
                meta_json=json.dumps({"run_id": context.get("run_id")}),
            )
        )
        legacy_note_fingerprint = str(data.get("legacy_note_fingerprint") or "").strip()
        if legacy_note_fingerprint:
            tenant_key = f"tenant:{tenant_id_for_write()}"
            legacy_exists = (
                db.query(ShipmentEtlImportFingerprint)
                .filter(
                    ShipmentEtlImportFingerprint.tenant_key == tenant_key,
                    ShipmentEtlImportFingerprint.fingerprint == legacy_note_fingerprint,
                )
                .first()
            )
            if not legacy_exists:
                db.add(
                    ShipmentEtlImportFingerprint(
                        tenant_key=tenant_key,
                        fingerprint=legacy_note_fingerprint,
                        shipment_id=obj.id,
                        unit_name=obj.purchase_unit,
                        order_number=optional_text(data.get("external_order_no")),
                        file_name=str(context.get("file_name") or ""),
                        source_kind="general_etl_legacy_note",
                        meta_json=json.dumps({"run_id": context.get("run_id")}),
                    )
                )
        return {"match_ref": str(obj.id), "after": obj.to_dict()}

    def rollback_row(self, db, *, match_ref, before, after, context):
        if not match_ref:
            return
        obj = db.get(ShipmentRecord, int(match_ref))
        if obj:
            assert_snapshot_unchanged(obj, after, "发货记录")
            db.delete(obj)
        from app.db.models.shipment_etl_fingerprint import ShipmentEtlImportFingerprint

        db.query(ShipmentEtlImportFingerprint).filter(
            ShipmentEtlImportFingerprint.shipment_id == int(match_ref)
        ).delete(synchronize_session=False)
