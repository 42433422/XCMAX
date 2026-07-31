"""Product master-data ETL adapter."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.application.etl.errors import EtlError
from app.application.etl.product_identity import (
    database_model_ambiguity_issue,
    product_name_key,
)
from app.application.etl.targets.base import (
    PreviewDecision,
    TargetAdapter,
    TargetField,
    json_safe,
)
from app.application.etl.targets.customer_product_support import owned_query
from app.application.etl.targets.helpers import (
    assert_created_row_unchanged,
    assert_rollback_image_matches,
    decimal_or_zero,
    model_values,
    optional_text,
)
from app.db.models.product import Product
from app.infrastructure.tenant_scope import tenant_id_for_write


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
        query = owned_query(db, Product).filter(Product.unit == str(data.get("unit") or ""))
        model = str(data.get("model_number") or "").strip()
        if model:
            return query.filter(Product.model_number == model).first()
        return query.filter(Product.name == str(data.get("name") or "")).first()

    @staticmethod
    def _name_key(data: dict[str, Any]) -> tuple[str, str]:
        return product_name_key(data, unit_field="unit")

    @classmethod
    def model_ambiguity_issue(
        cls,
        data: dict[str, Any],
        candidates: list[Any],
        *,
        exact_match: bool,
    ) -> dict[str, Any] | None:
        return database_model_ambiguity_issue(
            data,
            candidates,
            exact_match=exact_match,
        )

    def _same_name_candidates(self, db: Session, data: dict[str, Any]) -> list[Product]:
        return (
            owned_query(db, Product)
            .filter(
                Product.unit == str(data.get("unit") or ""),
                Product.name == str(data.get("name") or ""),
            )
            .all()
        )

    def preview(self, db, data, *, allowed_update_fields, context):
        issues = self.validate(data)
        if issues:
            return PreviewDecision("error", issues=issues, reason="validation_failed")
        cache = context.setdefault("_preview_cache", {})
        index = cache.get("product_by_match_key")
        name_index = cache.get("product_by_name_key")
        if index is None or name_index is None:
            products = owned_query(db, Product).all()
            index = {}
            name_index = {}
            for item in products:
                item_data = {
                    "unit": item.unit,
                    "model_number": item.model_number,
                    "name": item.name,
                }
                index[self._match_key(item_data)] = item
                name_index.setdefault(self._name_key(item_data), []).append(item)
            cache["product_by_match_key"] = index
            cache["product_by_name_key"] = name_index
        match_key = self._match_key(data)
        obj = index.get(match_key)
        ambiguity = self.model_ambiguity_issue(
            data,
            list((name_index or {}).get(self._name_key(data), [])),
            exact_match=bool(obj),
        )
        if ambiguity:
            return PreviewDecision(
                "error",
                issues=[ambiguity],
                reason="product_model_ambiguous",
            )
        if not obj:
            virtual = {"_etl_virtual": True, **json_safe(data)}
            index[match_key] = virtual
            (name_index or {}).setdefault(self._name_key(data), []).append(virtual)
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
            ambiguity = self.model_ambiguity_issue(
                data,
                self._same_name_candidates(db, data),
                exact_match=False,
            )
            if ambiguity:
                raise EtlError(ambiguity["code"], ambiguity["message"], status_code=409)
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
        obj = owned_query(db, Product).filter(Product.id == int(match_ref)).first()
        if not obj:
            raise EtlError("ETL_MATCH_DISAPPEARED", "预演匹配的产品已不存在", status_code=409)
        if action == "update":
            for key in allowed_update_fields:
                if hasattr(obj, key) and data.get(key) not in (None, ""):
                    setattr(obj, key, data[key])
            db.flush()
        return {"match_ref": str(obj.id), "after": model_values(obj, self.fields)}

    def rollback_row(self, db, *, match_ref, before, after, context):
        obj = owned_query(db, Product).filter(Product.id == int(match_ref)).first()
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
