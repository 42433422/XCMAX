"""Customer and product ETL target adapters."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.application.etl.errors import EtlError
from app.application.etl.targets.base import (
    PreviewDecision,
    TargetAdapter,
    TargetField,
    json_safe,
)
from app.application.etl.targets.helpers import (
    assert_created_row_unchanged,
    assert_rollback_image_matches,
    decimal_or_zero,
    model_values,
    optional_text,
)
from app.db.models.customer import Customer
from app.db.models.product import Product
from app.infrastructure.tenant_scope import tenant_id_for_write


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
        before = model_values(obj, self.fields)
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
                contact_person=optional_text(data.get("contact_person")),
                contact_phone=optional_text(data.get("contact_phone")),
                contact_address=optional_text(data.get("contact_address")),
            )
            db.add(obj)
            db.flush()
            return {"match_ref": str(obj.id), "after": model_values(obj, self.fields)}
        obj = db.get(Customer, int(match_ref))
        if not obj:
            raise EtlError("ETL_MATCH_DISAPPEARED", "预演匹配的客户已不存在", status_code=409)
        if action == "update":
            for key in allowed_update_fields:
                if hasattr(obj, key) and data.get(key) not in (None, ""):
                    setattr(obj, key, data[key])
            db.flush()
        return {"match_ref": str(obj.id), "after": model_values(obj, self.fields)}

    def rollback_row(self, db, *, match_ref, before, after, context):
        obj = db.get(Customer, int(match_ref))
        if before:
            if not obj:
                raise EtlError("ETL_ROLLBACK_TARGET_MISSING", "客户撤销目标已不存在")
            assert_rollback_image_matches(obj, before, after, self.fields, "客户")
            for field in self.fields:
                if field.key in before:
                    setattr(obj, field.key, before[field.key])
        elif obj:
            assert_created_row_unchanged(obj, after, self.fields, "客户")
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
        TargetField("specification", "规格", aliases=("规格", "规格型号"), updatable=True),
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
        before = model_values(obj, self.fields)
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
                model_number=optional_text(data.get("model_number")),
                name=str(data.get("name") or ""),
                specification=optional_text(data.get("specification")),
                price=decimal_or_zero(data.get("price")),
                category=optional_text(data.get("category")),
                brand=optional_text(data.get("brand")),
                description=optional_text(data.get("description")),
            )
            db.add(obj)
            db.flush()
            return {"match_ref": str(obj.id), "after": model_values(obj, self.fields)}
        obj = db.get(Product, int(match_ref))
        if not obj:
            raise EtlError("ETL_MATCH_DISAPPEARED", "预演匹配的产品已不存在", status_code=409)
        if action == "update":
            for key in allowed_update_fields:
                if hasattr(obj, key) and data.get(key) not in (None, ""):
                    setattr(obj, key, data[key])
            db.flush()
        return {"match_ref": str(obj.id), "after": model_values(obj, self.fields)}

    def rollback_row(self, db, *, match_ref, before, after, context):
        obj = db.get(Product, int(match_ref))
        if before:
            if not obj:
                raise EtlError("ETL_ROLLBACK_TARGET_MISSING", "产品撤销目标已不存在")
            assert_rollback_image_matches(obj, before, after, self.fields, "产品")
            for field in self.fields:
                if field.key in before:
                    setattr(obj, field.key, before[field.key])
        elif obj:
            assert_created_row_unchanged(obj, after, self.fields, "产品")
            db.delete(obj)

    @staticmethod
    def _match_key(data: dict[str, Any]) -> tuple[str, str, str]:
        unit = str(data.get("unit") or "")
        model = str(data.get("model_number") or "").strip()
        return (unit, "model" if model else "name", model or str(data.get("name") or ""))
