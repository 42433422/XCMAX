"""Product master-data ETL adapter."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.application.elt.errors import EltError
from app.application.elt.product_identity import (
    database_model_ambiguity_issue,
    product_name_key,
)
from app.application.elt.targets.customer_product_support import owned_query
from app.application.elt.targets.helpers import (
    assert_created_row_unchanged,
    assert_rollback_image_matches,
    decimal_or_none,
    issue,
    model_values,
    optional_text,
)
from app.application.elt.targets.rollback_compare_swap import delete_created_row, restore_fields
from app.application.elt.targets.targets_base import (
    PreviewDecision,
    TargetAdapter,
    TargetField,
    json_safe,
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
            scale=2,
        ),
        TargetField("category", "分类", aliases=("分类",), updatable=True),
        TargetField("brand", "品牌", aliases=("品牌",), updatable=True),
        TargetField("description", "描述", aliases=("描述", "备注"), updatable=True),
    )

    def _match(self, db: Session, data: dict[str, Any]) -> Product | None:
        query = owned_query(db, Product).filter(Product.unit == str(data.get("unit") or ""))
        model = str(data.get("model_number") or "").strip()
        if model:
            return cast("Product | None", query.filter(Product.model_number == model).first())
        return cast(
            "Product | None", query.filter(Product.name == str(data.get("name") or "")).first()
        )

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

    def _same_name_candidates(
        self, db: Session, data: dict[str, Any], *, normalized: bool = False
    ) -> list[Product]:
        query = owned_query(db, Product)
        if normalized:
            unit, name = self._name_key(data)
            query = query.filter(func.trim(Product.unit) == unit, func.trim(Product.name) == name)
        else:
            query = query.filter(
                Product.unit == str(data.get("unit") or ""),
                Product.name == str(data.get("name") or ""),
            )
        return cast("list[Product]", query.all())

    @classmethod
    def _no_model_conflict(cls, data, candidates):
        code = "ELT_PRODUCT_NO_MODEL_CONFLICT"
        if len(candidates) > 1:
            return issue(
                code, "model_number", "同一客户同名产品匹配到多条记录；请补全型号后重新预演"
            )
        if not candidates:
            return None
        candidate = candidates[0]
        values = candidate if isinstance(candidate, dict) else model_values(candidate, cls.fields)
        if (optional_text(data.get("specification")) or "") != (
            optional_text(values.get("specification")) or ""
        ):
            return issue(
                code, "specification", "同一客户同名无型号产品的规格不同；请核对后重新预演"
            )
        price = decimal_or_none(data.get("price"))
        existing_price = decimal_or_none(values.get("price"))
        # Product inserts with no price receive the ORM column's zero default.
        if price != existing_price and not (price is None and existing_price == 0):
            return issue(code, "price", "同一客户同名无型号产品的价格不同；请核对后重新预演")
        return None

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
        name_key = self._name_key(data)
        candidates = name_index.get(name_key, [])
        ambiguity = self.model_ambiguity_issue(data, candidates, exact_match=bool(obj))
        if ambiguity:
            return PreviewDecision(
                "error",
                issues=[ambiguity],
                reason="product_model_ambiguous",
            )
        no_model = match_key[1] == "name"
        if no_model:
            conflict = self._no_model_conflict(data, candidates)
            if conflict:
                return PreviewDecision(
                    "error", issues=[conflict], reason="product_no_model_conflict"
                )
            obj = candidates[0] if candidates else None
        if not obj:
            virtual = {"_elt_virtual": True, **json_safe(data)}
            index[match_key] = virtual
            name_index.setdefault(name_key, []).append(virtual)
            return PreviewDecision("new", after=json_safe(data), reason="product_not_found")
        if isinstance(obj, dict):
            return PreviewDecision(
                "skip",
                before=json_safe(obj),
                after=json_safe(obj),
                reason="duplicate_in_source_file",
            )
        before = model_values(obj, self.fields)
        if no_model:
            return PreviewDecision(
                "skip",
                match_ref=str(obj.id),
                before=before,
                after=before,
                reason="duplicate_product",
            )
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
        no_model = self._match_key(data)[1] == "name"
        if action == "new" or (action == "update" and no_model):
            candidates = self._same_name_candidates(db, data, normalized=no_model)
            conflict = self.model_ambiguity_issue(data, candidates, exact_match=False)
            if no_model and not conflict:
                conflict = self._no_model_conflict(data, candidates)
            if conflict:
                raise EltError(conflict["code"], conflict["message"], status_code=409)
        if action == "new":
            already_exists = bool(candidates) if no_model else self._match(db, data) is not None
            if already_exists:
                raise EltError(
                    "ELT_MATCH_CHANGED",
                    "产品在预演后已存在，请重新预演",
                    status_code=409,
                )
            obj = Product(
                tenant_id=tenant_id_for_write(),
                unit=str(data.get("unit") or ""),
                model_number=optional_text(data.get("model_number")),
                name=str(data.get("name") or ""),
                specification=optional_text(data.get("specification")),
                price=decimal_or_none(data.get("price")),
                category=optional_text(data.get("category")),
                brand=optional_text(data.get("brand")),
                description=optional_text(data.get("description")),
            )
            db.add(obj)
            db.flush()
            return {"match_ref": str(obj.id), "after": model_values(obj, self.fields)}
        if action == "update" and no_model:
            raise EltError(
                "ELT_PRODUCT_NO_MODEL_CONFLICT",
                "无型号产品不能覆盖已有记录；请补全型号后重新预演",
                status_code=409,
            )
        obj = owned_query(db, Product).filter(Product.id == int(match_ref)).first()
        if not obj:
            raise EltError("ELT_MATCH_DISAPPEARED", "预演匹配的产品已不存在", status_code=409)
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
                raise EltError("ELT_ROLLBACK_TARGET_MISSING", "产品撤销目标已不存在")
            changed_fields = assert_rollback_image_matches(obj, before, after, self.fields, "产品")
            restore_fields(
                db, obj, {field.key: before[field.key] for field in changed_fields}, "产品"
            )
        elif obj:
            assert_created_row_unchanged(obj, after, self.fields, "产品")
            delete_created_row(db, obj, "产品")

    @staticmethod
    def _match_key(data: dict[str, Any]) -> tuple[str, str, str]:
        unit = str(data.get("unit") or "")
        model = str(data.get("model_number") or "").strip()
        return (unit, "model" if model else "name", model or str(data.get("name") or ""))
