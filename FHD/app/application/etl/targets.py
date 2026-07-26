"""ETL 目标适配器及能力描述。"""

from __future__ import annotations

import csv
import hashlib
import ipaddress
import itertools
import json
import os
import socket
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.application.etl.errors import EtlError
from app.application.etl.secrets import read_webhook_secret
from app.application.etl.transforms import neutralize_spreadsheet_formula
from app.db.models.customer import Customer
from app.db.models.product import Product
from app.db.models.purchase import PurchaseOrder, PurchaseOrderItem, Supplier
from app.db.models.shipment import ShipmentRecord
from app.infrastructure.tenant_scope import tenant_id_for_write
from app.utils.path_utils import get_app_data_dir


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


@dataclass(frozen=True, slots=True)
class TargetField:
    key: str
    label: str
    type: str = "string"
    required: bool = False
    aliases: tuple[str, ...] = ()
    updatable: bool = False


@dataclass(slots=True)
class PreviewDecision:
    action: str
    match_ref: str = ""
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    issues: list[dict[str, Any]] | None = None
    reason: str = ""


class TargetAdapter:
    type = ""
    label = ""
    reversible = False
    actions: tuple[str, ...] = ("new", "skip")
    fields: tuple[TargetField, ...] = ()
    default_match_keys: tuple[str, ...] = ()
    allow_dynamic_fields = False

    def capability(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "label": self.label,
            "fields": [asdict(field) for field in self.fields],
            "required_fields": [field.key for field in self.fields if field.required],
            "default_match_keys": list(self.default_match_keys),
            "supported_actions": list(self.actions),
            "reversible": self.reversible,
            "allow_dynamic_fields": self.allow_dynamic_fields,
        }

    def validate(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        for field in self.fields:
            if field.required and data.get(field.key) in (None, ""):
                issues.append(
                    {
                        "code": "ETL_REQUIRED_FIELD_MISSING",
                        "field": field.key,
                        "severity": "error",
                        "message": f"{field.label}不能为空",
                    }
                )
        return issues

    def preview(
        self,
        db: Session,
        data: dict[str, Any],
        *,
        allowed_update_fields: set[str],
        context: dict[str, Any],
    ) -> PreviewDecision:
        issues = self.validate(data)
        if issues:
            return PreviewDecision("error", issues=issues, reason="validation_failed")
        return PreviewDecision("new", after=json_safe(data), reason="no_duplicate")

    def execute_row(
        self,
        db: Session,
        data: dict[str, Any],
        *,
        action: str,
        match_ref: str,
        allowed_update_fields: set[str],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        raise EtlError("ETL_TARGET_NOT_IMPLEMENTED", f"{self.label}暂不可执行")

    def rollback_row(
        self,
        db: Session,
        *,
        match_ref: str,
        before: dict[str, Any],
        after: dict[str, Any],
        context: dict[str, Any],
    ) -> None:
        raise EtlError("ETL_TARGET_NOT_REVERSIBLE", f"{self.label}不可撤销")


class CustomerAdapter(TargetAdapter):
    type = "customers"
    label = "客户"
    reversible = True
    actions = ("new", "update", "skip")
    default_match_keys = ("customer_name",)
    fields = (
        TargetField(
            "customer_name", "客户名称", required=True, aliases=("客户", "单位", "购货单位")
        ),
        TargetField("contact_person", "联系人", aliases=("联系人", "姓名"), updatable=True),
        TargetField("contact_phone", "电话", aliases=("电话", "手机", "联系方式"), updatable=True),
        TargetField("contact_address", "地址", aliases=("地址", "收货地址"), updatable=True),
    )

    def preview(self, db, data, *, allowed_update_fields, context):
        issues = self.validate(data)
        if issues:
            return PreviewDecision("error", issues=issues, reason="validation_failed")
        cache = context.setdefault("_preview_cache", {})
        index = cache.get("customer_by_name")
        if index is None:
            index = {str(item.customer_name): item for item in db.query(Customer).all()}
            cache["customer_by_name"] = index
        customer_name = str(data["customer_name"])
        obj = index.get(customer_name)
        if not obj:
            index[customer_name] = {"_etl_virtual": True, **json_safe(data)}
            return PreviewDecision("new", after=json_safe(data), reason="customer_not_found")
        if isinstance(obj, dict):
            return PreviewDecision(
                "skip",
                before=json_safe(obj),
                after=json_safe(obj),
                reason="duplicate_in_source_file",
            )
        before = _model_values(obj, self.fields)
        updates = {
            key: data.get(key)
            for key in allowed_update_fields
            if key in before
            and data.get(key) not in (None, "")
            and data.get(key) != before.get(key)
        }
        if updates:
            return PreviewDecision(
                "update",
                match_ref=str(obj.id),
                before=before,
                after={**before, **updates},
                reason="confirmed_update_fields_changed",
            )
        return PreviewDecision(
            "skip", match_ref=str(obj.id), before=before, after=before, reason="duplicate_customer"
        )

    def execute_row(self, db, data, *, action, match_ref, allowed_update_fields, context):
        if action == "new":
            existing = (
                db.query(Customer)
                .filter(Customer.customer_name == str(data["customer_name"]))
                .first()
            )
            if existing:
                raise EtlError(
                    "ETL_MATCH_CHANGED",
                    "客户在预演后已存在，请重新预演",
                    status_code=409,
                )
            obj = Customer(
                tenant_id=tenant_id_for_write(),
                customer_name=str(data["customer_name"]),
                contact_person=_optional_text(data.get("contact_person")),
                contact_phone=_optional_text(data.get("contact_phone")),
                contact_address=_optional_text(data.get("contact_address")),
            )
            db.add(obj)
            db.flush()
            return {"match_ref": str(obj.id), "after": _model_values(obj, self.fields)}
        obj = db.get(Customer, int(match_ref))
        if not obj:
            raise EtlError("ETL_MATCH_DISAPPEARED", "预演匹配的客户已不存在", status_code=409)
        if action == "update":
            for key in allowed_update_fields:
                if hasattr(obj, key) and data.get(key) not in (None, ""):
                    setattr(obj, key, data[key])
            db.flush()
        return {"match_ref": str(obj.id), "after": _model_values(obj, self.fields)}

    def rollback_row(self, db, *, match_ref, before, after, context):
        obj = db.get(Customer, int(match_ref))
        if before:
            if not obj:
                raise EtlError("ETL_ROLLBACK_TARGET_MISSING", "客户撤销目标已不存在")
            _assert_rollback_image_matches(obj, before, after, self.fields, "客户")
            for field in self.fields:
                if field.key in before:
                    setattr(obj, field.key, before[field.key])
        elif obj:
            _assert_created_row_unchanged(obj, after, self.fields, "客户")
            db.delete(obj)


class ProductAdapter(TargetAdapter):
    type = "products"
    label = "产品"
    reversible = True
    actions = ("new", "update", "skip")
    default_match_keys = ("unit", "model_number")
    fields = (
        TargetField(
            "unit",
            "购买单位",
            required=True,
            aliases=("单位", "购买单位", "购货单位", "客户"),
        ),
        TargetField("model_number", "型号", aliases=("型号", "产品型号")),
        TargetField("name", "产品名称", required=True, aliases=("品名", "产品", "名称")),
        TargetField(
            "specification", "规格", aliases=("规格", "规格型号"), updatable=True
        ),
        TargetField(
            "price",
            "价格",
            type="number",
            aliases=("价格", "单价", "售价"),
            updatable=True,
        ),
        TargetField("category", "分类", aliases=("分类",), updatable=True),
        TargetField("brand", "品牌", aliases=("品牌",), updatable=True),
        TargetField("description", "描述", aliases=("描述", "备注"), updatable=True),
    )

    def _match(self, db: Session, data: dict[str, Any]) -> Product | None:
        query = db.query(Product).filter(Product.unit == str(data.get("unit") or ""))
        model = str(data.get("model_number") or "").strip()
        if model:
            return query.filter(Product.model_number == model).first()
        return query.filter(Product.name == str(data.get("name") or "")).first()

    def preview(self, db, data, *, allowed_update_fields, context):
        issues = self.validate(data)
        if issues:
            return PreviewDecision("error", issues=issues, reason="validation_failed")
        cache = context.setdefault("_preview_cache", {})
        index = cache.get("product_by_match_key")
        if index is None:
            index = {
                self._match_key(
                    {
                        "unit": item.unit,
                        "model_number": item.model_number,
                        "name": item.name,
                    }
                ): item
                for item in db.query(Product).all()
            }
            cache["product_by_match_key"] = index
        match_key = self._match_key(data)
        obj = index.get(match_key)
        if not obj:
            index[match_key] = {"_etl_virtual": True, **json_safe(data)}
            return PreviewDecision("new", after=json_safe(data), reason="product_not_found")
        if isinstance(obj, dict):
            return PreviewDecision(
                "skip",
                before=json_safe(obj),
                after=json_safe(obj),
                reason="duplicate_in_source_file",
            )
        before = _model_values(obj, self.fields)
        updates = {
            key: data.get(key)
            for key in allowed_update_fields
            if key in before
            and data.get(key) not in (None, "")
            and data.get(key) != before.get(key)
        }
        if updates:
            return PreviewDecision(
                "update",
                match_ref=str(obj.id),
                before=before,
                after={**before, **updates},
                reason="confirmed_update_fields_changed",
            )
        return PreviewDecision(
            "skip", match_ref=str(obj.id), before=before, after=before, reason="duplicate_product"
        )

    def execute_row(self, db, data, *, action, match_ref, allowed_update_fields, context):
        if action == "new":
            if self._match(db, data):
                raise EtlError(
                    "ETL_MATCH_CHANGED",
                    "产品在预演后已存在，请重新预演",
                    status_code=409,
                )
            obj = Product(
                tenant_id=tenant_id_for_write(),
                unit=str(data.get("unit") or ""),
                model_number=_optional_text(data.get("model_number")),
                name=str(data.get("name") or ""),
                specification=_optional_text(data.get("specification")),
                price=_decimal_or_zero(data.get("price")),
                category=_optional_text(data.get("category")),
                brand=_optional_text(data.get("brand")),
                description=_optional_text(data.get("description")),
            )
            db.add(obj)
            db.flush()
            return {"match_ref": str(obj.id), "after": _model_values(obj, self.fields)}
        obj = db.get(Product, int(match_ref))
        if not obj:
            raise EtlError("ETL_MATCH_DISAPPEARED", "预演匹配的产品已不存在", status_code=409)
        if action == "update":
            for key in allowed_update_fields:
                if hasattr(obj, key) and data.get(key) not in (None, ""):
                    setattr(obj, key, data[key])
            db.flush()
        return {"match_ref": str(obj.id), "after": _model_values(obj, self.fields)}

    def rollback_row(self, db, *, match_ref, before, after, context):
        obj = db.get(Product, int(match_ref))
        if before:
            if not obj:
                raise EtlError("ETL_ROLLBACK_TARGET_MISSING", "产品撤销目标已不存在")
            _assert_rollback_image_matches(obj, before, after, self.fields, "产品")
            for field in self.fields:
                if field.key in before:
                    setattr(obj, field.key, before[field.key])
        elif obj:
            _assert_created_row_unchanged(obj, after, self.fields, "产品")
            db.delete(obj)

    @staticmethod
    def _match_key(data: dict[str, Any]) -> tuple[str, str, str]:
        unit = str(data.get("unit") or "")
        model = str(data.get("model_number") or "").strip()
        return (unit, "model" if model else "name", model or str(data.get("name") or ""))


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
            issues.append(_issue("ETL_SUPPLIER_NOT_FOUND", "supplier_name", "供应商不存在"))
        if not product:
            issues.append(_issue("ETL_PRODUCT_NOT_FOUND", "product_name", "产品不存在"))
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
                order_date=_parse_date(data["order_date"]),
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
        quantity = _decimal_or_zero(data.get("quantity"))
        unit_price = _decimal_or_zero(data.get("unit_price"))
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
            _assert_snapshot_unchanged(
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
                    _assert_snapshot_unchanged(
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
            issues.append(
                _issue("ETL_QUANTITY_REQUIRED", "quantity_kg", "公斤数或桶数至少填写一项")
            )
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
                ShipmentEtlImportFingerprint.file_name
                == str(context.get("file_name") or ""),
                ShipmentEtlImportFingerprint.unit_name
                == str(data.get("purchase_unit") or ""),
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
        parsed = {
            "external_order_no": data.get("external_order_no"),
            "etl_run_id": context.get("run_id"),
            "etl_fingerprint": fingerprint,
        }
        quantity_kg = float(_decimal_or_zero(data.get("quantity_kg")))
        quantity_tins = int(_decimal_or_zero(data.get("quantity_tins")))
        obj = ShipmentRecord(
            tenant_id=tenant_id_for_write(),
            purchase_unit=str(data["purchase_unit"]),
            product_name=str(data["product_name"]),
            model_number=_optional_text(data.get("model_number")),
            quantity_kg=quantity_kg,
            quantity_tins=quantity_tins,
            tin_spec=float(_decimal_or_zero(data.get("tin_spec"))) or None,
            unit_price=_decimal_or_zero(data.get("unit_price")),
            amount=_decimal_or_zero(data.get("amount")),
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
                order_number=_optional_text(data.get("external_order_no")),
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
                        order_number=_optional_text(data.get("external_order_no")),
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
            _assert_snapshot_unchanged(obj, after, "发货记录")
            db.delete(obj)
        from app.db.models.shipment_etl_fingerprint import ShipmentEtlImportFingerprint

        db.query(ShipmentEtlImportFingerprint).filter(
            ShipmentEtlImportFingerprint.shipment_id == int(match_ref)
        ).delete(synchronize_session=False)


class KnowledgeAdapter(TargetAdapter):
    type = "knowledge"
    label = "知识库"
    reversible = True
    actions = ("new", "update", "skip")
    fields = (
        TargetField(
            "document_path",
            "文档路径",
            aliases=("document_path",),
            updatable=True,
        ),
        TargetField("content", "内容", aliases=("内容", "正文"), updatable=True),
        TargetField("source_key", "来源键", aliases=("来源", "来源键")),
    )
    default_match_keys = ("content_hash",)

    def validate(self, data):
        if not data.get("document_path") and not data.get("content"):
            return [_issue("ETL_KNOWLEDGE_CONTENT_REQUIRED", "content", "文档或内容不能为空")]
        return []

    @staticmethod
    def _content_hash(data: dict[str, Any], context: dict[str, Any]) -> str:
        content = str(data.get("content") or "")
        if content:
            return hashlib.sha256(content.encode("utf-8")).hexdigest()
        # 文档型输入由上传层计算完整文件哈希；不要信任映射值中的任意本地路径。
        return str(context.get("file_sha256") or "")

    @staticmethod
    def _source_label(data: dict[str, Any], context: dict[str, Any]) -> str:
        return str(data.get("source_key") or context.get("file_name") or "etl-import")

    def _documents(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        cache = context.setdefault("_preview_cache", {})
        cache_key = f"knowledge:{tenant_id_for_write()}"
        if cache_key in cache:
            return cache[cache_key]
        from app.application.dataset_rag_app_service import (
            DATASET_READ_PERMISSION,
            DatasetAccessContext,
            get_dataset_rag_app_service,
        )

        tenant_key = str(tenant_id_for_write())
        status = get_dataset_rag_app_service().status(
            dataset_id="office-docking",
            tenant_id=tenant_key,
            access_context=DatasetAccessContext(
                actor_id=str(context.get("owner_user_id") or ""),
                tenant_id=tenant_key,
                permissions=frozenset({DATASET_READ_PERMISSION}),
            ),
        )
        documents = status.get("documents") if status.get("success") else []
        cache[cache_key] = documents if isinstance(documents, list) else []
        return cache[cache_key]

    def preview(self, db, data, *, allowed_update_fields, context):
        issues = self.validate(data)
        document_path = str(data.get("document_path") or "").strip()
        if document_path and not _is_uploaded_document_path(document_path, context):
            issues.append(
                _issue(
                    "ETL_DOCUMENT_PATH_FORBIDDEN",
                    "document_path",
                    "知识库文档路径必须指向本次上传文件",
                )
            )
        if issues:
            return PreviewDecision("error", issues=issues, reason="validation_failed")
        content_hash = self._content_hash(data, context)
        source_label = self._source_label(data, context)
        documents = self._documents(context)
        duplicate = next(
            (
                document
                for document in documents
                if str((document.get("metadata") or {}).get("content_hash") or "")
                == content_hash
            ),
            None,
        )
        if duplicate:
            return PreviewDecision(
                "skip",
                match_ref=str(duplicate.get("document_id") or ""),
                before=json_safe(duplicate),
                after=json_safe(duplicate),
                reason="duplicate_content_hash",
            )
        source_matches = [
            document for document in documents if str(document.get("source") or "") == source_label
        ]
        previous = (
            max(source_matches, key=lambda item: int(item.get("version") or 1))
            if source_matches
            else None
        )
        after = {
            **json_safe(data),
            "content_hash": content_hash,
            "source_key": source_label,
        }
        if previous:
            if {"content", "document_path"} & set(allowed_update_fields):
                return PreviewDecision(
                    "update",
                    match_ref=str(previous.get("document_id") or ""),
                    before=json_safe(previous),
                    after=after,
                    reason="confirmed_source_replacement",
                )
            return PreviewDecision(
                "skip",
                match_ref=str(previous.get("document_id") or ""),
                before=json_safe(previous),
                after=json_safe(previous),
                reason="source_exists_update_not_confirmed",
            )
        return PreviewDecision("new", after=after, reason="content_not_found")

    def execute_row(self, db, data, *, action, match_ref, allowed_update_fields, context):
        from app.application.dataset_rag_app_service import (
            DATASET_WRITE_PERMISSION,
            DatasetAccessContext,
            get_dataset_rag_app_service,
        )

        document_path = str(data.get("document_path") or "").strip()
        if document_path and not _is_uploaded_document_path(document_path, context):
            raise EtlError(
                "ETL_DOCUMENT_PATH_FORBIDDEN",
                "知识库文档路径必须指向本次上传文件",
            )
        stable = self._content_hash(data, context)
        document_id = f"etl-{stable[:24]}"
        tenant_key = str(tenant_id_for_write())
        source_label = self._source_label(data, context)
        access = DatasetAccessContext(
            actor_id=str(context.get("owner_user_id") or ""),
            tenant_id=tenant_key,
            permissions=frozenset({DATASET_WRITE_PERMISSION}),
        )
        result = get_dataset_rag_app_service().ingest_document(
            dataset_id="office-docking",
            source=source_label,
            text=str(data.get("content") or ""),
            file_path=str(data.get("document_path") or ""),
            document_id=document_id,
            tenant_id=tenant_key,
            metadata={"etl_run_id": context.get("run_id"), "content_hash": stable},
            access_context=access,
        )
        if not result.get("success", True):
            raise EtlError("ETL_KNOWLEDGE_INGEST_FAILED", "知识库写入失败")
        document = result.get("document") or {}
        return {
            "match_ref": document_id,
            "after": {
                "document_id": document_id,
                "content_hash": stable,
                "source_key": source_label,
                "version": document.get("version"),
            },
        }

    def rollback_row(self, db, *, match_ref, before, after, context):
        from app.application.dataset_rag_app_service import (
            DATASET_WRITE_PERMISSION,
            DatasetAccessContext,
            get_dataset_rag_app_service,
        )

        result = get_dataset_rag_app_service().delete_document(
            dataset_id="office-docking",
            document_id=match_ref,
            access_context=DatasetAccessContext(
                actor_id=str(context.get("owner_user_id") or ""),
                tenant_id=str(tenant_id_for_write()),
                permissions=frozenset({DATASET_WRITE_PERMISSION}),
            ),
        )
        if not result.get("success", True):
            raise EtlError("ETL_KNOWLEDGE_ROLLBACK_FAILED", "知识库撤销失败")


class AttendanceAdapter(TargetAdapter):
    type = "attendance"
    label = "考勤"
    reversible = True
    fields = (TargetField("document_path", "考勤文件", aliases=("document_path",)),)
    default_match_keys = ("source_file", "source_row")

    def execute_batch(
        self, rows: Iterable[dict[str, Any]], context: dict[str, Any]
    ) -> dict[str, Any]:
        from app.application.attendance_import_app_service import import_attendance_workbook

        source_path = Path(str(context["upload_path"]))
        if source_path.suffix.lower() not in {".xlsx", ".xlsm"}:
            raise EtlError("ETL_ATTENDANCE_FILE_INVALID", "考勤仅支持 Excel 工作簿")
        data_root = Path(get_app_data_dir())
        db_path = data_root / "data" / "mod_dbs" / "taiyangniao-pro.db"
        result = import_attendance_workbook(
            source_path,
            db_path,
            source_file_key=f"{context['file_sha256']}:{source_path.name}",
            sync_ui_tables=True,
        )
        row_count = int(context.get("row_count") or 0)
        callback = context.get("progress_callback")
        if callable(callback):
            callback(row_count, row_count)
        return {"receipt": result, "executed": row_count}

    def rollback_batch(self, context: dict[str, Any], receipt: dict[str, Any]) -> int:
        import sqlite3

        source_file = str(receipt.get("source_file") or "")
        db_path = Path(str(receipt.get("db_path") or ""))
        if not source_file or not db_path.is_file():
            raise EtlError("ETL_ATTENDANCE_ROLLBACK_DATA_MISSING", "考勤撤销依据不存在")
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("BEGIN")
            deleted = 0
            for table in (
                "attendance_daily_records",
                "attendance_employees",
                "attendance_departments",
                "products",
                "customers",
            ):
                try:
                    cursor = conn.execute(
                        f"DELETE FROM {table} WHERE source_file = ?", (source_file,)
                    )
                    deleted += int(cursor.rowcount or 0)
                except sqlite3.OperationalError:
                    continue
            batch_id = int(receipt.get("batch_id") or 0)
            if batch_id:
                conn.execute("DELETE FROM attendance_import_batches WHERE id = ?", (batch_id,))
            conn.commit()
            return deleted
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


class ExportAdapter(TargetAdapter):
    reversible = False
    fields = ()
    default_match_keys = ()
    allow_dynamic_fields = True

    def execute_batch(
        self, rows: Iterable[dict[str, Any]], context: dict[str, Any]
    ) -> dict[str, Any]:
        root = Path(get_app_data_dir()).resolve() / "etl" / "exports"
        root.mkdir(parents=True, exist_ok=True)
        suffix = ".csv" if self.type == "export_csv" else ".xlsx"
        path = root / f"etl-{context['run_id']}{suffix}"
        iterator = iter(rows)
        first = next(iterator, None)
        headers = list(context.get("output_headers") or (list(first) if first else []))
        stream = itertools.chain((first,), iterator) if first is not None else iter(())
        total = int(context.get("row_count") or 0)
        executed = 0
        if self.type == "export_csv":
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=headers)
                writer.writeheader()
                for executed, row in enumerate(stream, start=1):
                    writer.writerow(
                        {
                            key: neutralize_spreadsheet_formula(row.get(key, ""))
                            for key in headers
                        }
                    )
                    if executed % 500 == 0:
                        callback = context.get("progress_callback")
                        if callable(callback):
                            callback(executed, total)
        else:
            from openpyxl import Workbook

            workbook = Workbook(write_only=True)
            worksheet = workbook.create_sheet("ETL导出")
            worksheet.append(headers)
            for executed, row in enumerate(stream, start=1):
                worksheet.append(
                    [
                        neutralize_spreadsheet_formula(row.get(key, ""))
                        for key in headers
                    ]
                )
                if executed % 500 == 0:
                    callback = context.get("progress_callback")
                    if callable(callback):
                        callback(executed, total)
            workbook.save(path)
            workbook.close()
        callback = context.get("progress_callback")
        if callable(callback):
            callback(executed, total)
        return {
            "receipt": {
                "file_name": path.name,
                "download_url": f"/api/etl/runs/{context['run_id']}/download",
                "reversible": False,
            },
            "executed": executed,
        }


class ExportCsvAdapter(ExportAdapter):
    type = "export_csv"
    label = "CSV 导出"


class ExportXlsxAdapter(ExportAdapter):
    type = "export_xlsx"
    label = "Excel 导出"


class WebhookAdapter(TargetAdapter):
    type = "webhook"
    label = "Webhook"
    reversible = False
    fields = ()
    allow_dynamic_fields = True

    def execute_batch(
        self, rows: Iterable[dict[str, Any]], context: dict[str, Any]
    ) -> dict[str, Any]:
        import httpx

        config = context.get("target_config") or {}
        endpoint = str(config.get("endpoint_url") or "")
        _assert_safe_webhook_url(endpoint)
        headers = dict(config.get("headers") or {})
        secret = read_webhook_secret(config.get("secret_ref"))
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        total = int(context.get("row_count") or (len(rows) if hasattr(rows, "__len__") else 0))
        chunk_count = max(1, (total + 499) // 500)
        iterator = iter(rows)
        receipts = []
        executed = 0
        with httpx.Client(timeout=10.0, follow_redirects=False) as client:
            for index in range(chunk_count):
                chunk = list(itertools.islice(iterator, 500))
                if not chunk and not context.get("connectivity_test"):
                    break
                idempotency_key = f"{context['run_id']}:{index}"
                payload = {
                    "run_id": context["run_id"],
                    "chunk_index": index,
                    "chunk_count": chunk_count,
                    "idempotency_key": idempotency_key,
                    "rows": json_safe(chunk),
                }
                response = None
                for attempt in range(3):
                    try:
                        response = client.post(
                            endpoint,
                            json=payload,
                            headers={**headers, "Idempotency-Key": idempotency_key},
                        )
                        if response.status_code < 500:
                            break
                    except httpx.HTTPError:
                        response = None
                    if attempt < 2:
                        time.sleep(2**attempt)
                if response is None or response.status_code >= 300:
                    raise EtlError(
                        "ETL_WEBHOOK_DELIVERY_FAILED",
                        f"Webhook 第 {index + 1} 个分片发送失败",
                        status_code=502,
                    )
                receipts.append({"chunk_index": index, "status_code": response.status_code})
                executed += len(chunk)
                callback = context.get("progress_callback")
                if callable(callback):
                    callback(executed, total)
        return {
            "receipt": {
                "chunks": receipts,
                "reversible": False,
                "executed_rows": executed,
            },
            "executed": executed,
        }


def _assert_safe_webhook_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise EtlError("ETL_WEBHOOK_URL_INVALID", "Webhook URL 必须是有效的 HTTP(S) 地址")
    if parsed.scheme != "https" and not _truthy_env("FHD_ETL_ALLOW_HTTP_WEBHOOK"):
        raise EtlError("ETL_WEBHOOK_HTTPS_REQUIRED", "Webhook 默认只允许 HTTPS")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443)}
    except OSError as exc:
        raise EtlError("ETL_WEBHOOK_DNS_FAILED", "Webhook 域名无法解析") from exc
    if not _truthy_env("FHD_ETL_ALLOW_PRIVATE_WEBHOOK"):
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
            ):
                raise EtlError("ETL_WEBHOOK_PRIVATE_ADDRESS_FORBIDDEN", "Webhook 禁止访问内网地址")


def _issue(code: str, field: str, message: str) -> dict[str, Any]:
    return {"code": code, "field": field, "severity": "error", "message": message}


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _decimal_or_zero(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0").replace(",", ""))
    except Exception as exc:  # noqa: BLE001
        raise EtlError("ETL_NUMBER_INVALID", f"数字格式不正确: {value}") from exc


def _parse_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise EtlError("ETL_DATE_INVALID", f"日期格式不正确: {value}") from exc


def _model_values(obj: Any, fields: tuple[TargetField, ...]) -> dict[str, Any]:
    return json_safe({field.key: getattr(obj, field.key, None) for field in fields})


def _values_equal(current: Any, expected: Any) -> bool:
    if isinstance(current, Decimal):
        try:
            return current == Decimal(str(expected))
        except Exception:  # noqa: BLE001
            return False
    if isinstance(current, datetime):
        return current.isoformat() == str(expected)
    if isinstance(current, date):
        return current.isoformat() == str(expected)
    if current is None or expected is None:
        return current is None and expected is None
    return str(current) == str(expected)


def _changed_image_fields(
    before: dict[str, Any],
    after: dict[str, Any],
    fields: tuple[TargetField, ...],
) -> list[TargetField]:
    return [
        field
        for field in fields
        if field.key in before
        and field.key in after
        and not _values_equal(before.get(field.key), after.get(field.key))
    ]


def _assert_rollback_image_matches(
    obj: Any,
    before: dict[str, Any],
    after: dict[str, Any],
    fields: tuple[TargetField, ...],
    label: str,
) -> None:
    for field in _changed_image_fields(before, after, fields):
        if not _values_equal(getattr(obj, field.key, None), after.get(field.key)):
            raise EtlError(
                "ETL_ROLLBACK_CONCURRENT_CHANGE",
                f"{label}在本次导入后又被修改，已停止撤销以避免覆盖新数据",
                status_code=409,
            )


def _assert_created_row_unchanged(
    obj: Any,
    after: dict[str, Any],
    fields: tuple[TargetField, ...],
    label: str,
) -> None:
    for field in fields:
        if field.key not in after:
            continue
        if not _values_equal(getattr(obj, field.key, None), after.get(field.key)):
            raise EtlError(
                "ETL_ROLLBACK_CONCURRENT_CHANGE",
                f"{label}在本次导入后又被修改，已停止撤销以避免删除新数据",
                status_code=409,
            )


def _assert_snapshot_unchanged(
    obj: Any,
    snapshot: dict[str, Any],
    label: str,
) -> None:
    for key, expected in snapshot.items():
        if key in {"id", "created_at", "updated_at"} or not hasattr(obj, key):
            continue
        if not _values_equal(getattr(obj, key), expected):
            raise EtlError(
                "ETL_ROLLBACK_CONCURRENT_CHANGE",
                f"{label}在本次导入后又被修改，已停止撤销以避免删除新数据",
                status_code=409,
            )


def _is_uploaded_document_path(document_path: str, context: dict[str, Any]) -> bool:
    upload_path = str(context.get("upload_path") or "").strip()
    if not upload_path:
        return False
    try:
        return Path(document_path).expanduser().resolve() == Path(upload_path).resolve()
    except OSError:
        return False


def _truthy_env(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


_ADAPTERS: dict[str, TargetAdapter] = {
    adapter.type: adapter
    for adapter in (
        KnowledgeAdapter(),
        CustomerAdapter(),
        ProductAdapter(),
        PurchaseOrderAdapter(),
        ShipmentAdapter(),
        AttendanceAdapter(),
        ExportXlsxAdapter(),
        ExportCsvAdapter(),
        WebhookAdapter(),
    )
}


def get_adapter(target_type: str) -> TargetAdapter:
    adapter = _ADAPTERS.get(str(target_type or "").strip())
    if adapter is None:
        raise EtlError("ETL_TARGET_UNSUPPORTED", f"不支持的目标类型: {target_type}")
    return adapter


def target_capabilities() -> list[dict[str, Any]]:
    return [adapter.capability() for adapter in _ADAPTERS.values()]
