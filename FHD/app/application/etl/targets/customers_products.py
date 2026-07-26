"""Customer and product ETL target adapters."""

from __future__ import annotations

import json
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
from app.db.models.product import Product
from app.db.models.purchase_unit import PurchaseUnit
from app.infrastructure.tenant_scope import apply_tenant_filter, tenant_id_for_write

_CUSTOMER_MODEL_FIELDS = {
    "customer_name": "unit_name",
    "contact_person": "contact_person",
    "contact_phone": "contact_phone",
    "contact_address": "address",
}


def _customer_values(obj: PurchaseUnit) -> dict[str, Any]:
    return json_safe(
        {
            target: getattr(obj, model_field, None)
            for target, model_field in _CUSTOMER_MODEL_FIELDS.items()
        }
    )


def _customer_image_matches(
    obj: PurchaseUnit,
    expected: dict[str, Any],
    *,
    keys: set[str] | None = None,
) -> bool:
    current = _customer_values(obj)
    selected = keys if keys is not None else set(expected)
    return all(
        (current.get(key) is None and expected.get(key) is None)
        or str(current.get(key)) == str(expected.get(key))
        for key in selected
        if key in expected
    )


def _owned_query(db: Session, model: Any):
    return apply_tenant_filter(db.query(model), model)


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
            index = {str(item.unit_name): item for item in _owned_query(db, PurchaseUnit).all()}
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
        before = _customer_values(obj)
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
                _owned_query(db, PurchaseUnit)
                .filter(PurchaseUnit.unit_name == str(data["customer_name"]))
                .first()
            )
            if existing:
                raise EtlError(
                    "ETL_MATCH_CHANGED",
                    "客户在预演后已存在，请重新预演",
                    status_code=409,
                )
            obj = PurchaseUnit(
                tenant_id=tenant_id_for_write(),
                unit_name=str(data["customer_name"]),
                contact_person=optional_text(data.get("contact_person")),
                contact_phone=optional_text(data.get("contact_phone")),
                address=optional_text(data.get("contact_address")),
                is_active=True,
            )
            db.add(obj)
            db.flush()
            return {"match_ref": str(obj.id), "after": _customer_values(obj)}
        obj = (
            _owned_query(db, PurchaseUnit)
            .filter(PurchaseUnit.id == int(match_ref))
            .first()
        )
        if not obj:
            raise EtlError("ETL_MATCH_DISAPPEARED", "预演匹配的客户已不存在", status_code=409)
        if action == "update":
            for key in allowed_update_fields:
                model_field = _CUSTOMER_MODEL_FIELDS.get(key)
                if model_field and data.get(key) not in (None, ""):
                    setattr(obj, model_field, data[key])
            db.flush()
        return {"match_ref": str(obj.id), "after": _customer_values(obj)}

    def rollback_row(self, db, *, match_ref, before, after, context):
        obj = (
            _owned_query(db, PurchaseUnit)
            .filter(PurchaseUnit.id == int(match_ref))
            .first()
        )
        if before:
            if not obj:
                raise EtlError("ETL_ROLLBACK_TARGET_MISSING", "客户撤销目标已不存在")
            changed = {
                key
                for key in before
                if key in after and str(before.get(key)) != str(after.get(key))
            }
            if not _customer_image_matches(obj, after, keys=changed):
                raise EtlError(
                    "ETL_ROLLBACK_CONCURRENT_CHANGE",
                    "客户在本次导入后又被修改，已停止撤销以避免覆盖新数据",
                    status_code=409,
                )
            for key, model_field in _CUSTOMER_MODEL_FIELDS.items():
                if key in before:
                    setattr(obj, model_field, before[key])
        elif obj:
            if not _customer_image_matches(obj, after):
                raise EtlError(
                    "ETL_ROLLBACK_CONCURRENT_CHANGE",
                    "客户在本次导入后又被修改，已停止撤销以避免删除新数据",
                    status_code=409,
                )
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
        query = _owned_query(db, Product).filter(Product.unit == str(data.get("unit") or ""))
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
                for item in _owned_query(db, Product).all()
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
        obj = _owned_query(db, Product).filter(Product.id == int(match_ref)).first()
        if not obj:
            raise EtlError("ETL_MATCH_DISAPPEARED", "预演匹配的产品已不存在", status_code=409)
        if action == "update":
            for key in allowed_update_fields:
                if hasattr(obj, key) and data.get(key) not in (None, ""):
                    setattr(obj, key, data[key])
            db.flush()
        return {"match_ref": str(obj.id), "after": model_values(obj, self.fields)}

    def rollback_row(self, db, *, match_ref, before, after, context):
        obj = _owned_query(db, Product).filter(Product.id == int(match_ref)).first()
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


class CustomerProductsAdapter(TargetAdapter):
    """One logical target for the purchase-unit/product aggregate.

    Product rows are related to the canonical PurchaseUnit through the exact
    normalized unit name used by the existing ERP customer and product pages.
    """

    type = "customer_products"
    label = "客户及产品"
    reversible = True
    actions = ("new", "update", "skip")
    default_match_keys = ("customer_name", "model_number")
    fields = (
        TargetField(
            "customer_name",
            "客户/购买单位",
            required=True,
            aliases=("客户", "客户名称", "单位", "购买单位", "购货单位"),
        ),
        TargetField("contact_person", "联系人", aliases=("联系人", "姓名"), updatable=True),
        TargetField(
            "contact_phone",
            "联系电话",
            aliases=("电话", "手机", "联系方式"),
            updatable=True,
        ),
        TargetField(
            "contact_address",
            "联系地址",
            aliases=("地址", "收货地址"),
            updatable=True,
        ),
        TargetField("model_number", "产品型号", aliases=("型号", "产品型号")),
        TargetField(
            "name",
            "产品名称",
            required=True,
            aliases=("品名", "产品", "产品名称", "名称"),
        ),
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
        TargetField("description", "产品描述", aliases=("描述", "备注"), updatable=True),
    )

    _customer_fields = frozenset(_CUSTOMER_MODEL_FIELDS)
    _product_fields = frozenset(
        {
            "specification",
            "price",
            "category",
            "brand",
            "description",
        }
    )

    @staticmethod
    def _customer_data(data: dict[str, Any]) -> dict[str, Any]:
        return {
            key: data.get(key)
            for key in _CUSTOMER_MODEL_FIELDS
            if data.get(key) not in (None, "")
        }

    @staticmethod
    def _product_data(data: dict[str, Any]) -> dict[str, Any]:
        return {
            "unit": str(data.get("customer_name") or "").strip(),
            "model_number": data.get("model_number"),
            "name": data.get("name"),
            "specification": data.get("specification"),
            "price": data.get("price"),
            "category": data.get("category"),
            "brand": data.get("brand"),
            "description": data.get("description"),
        }

    @staticmethod
    def _match_ref(customer_id: int | None, product_id: int | None) -> str:
        if product_id is None:
            return ""
        return json.dumps(
            {"customer_id": customer_id, "product_id": product_id},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @staticmethod
    def _parse_match_ref(match_ref: str) -> tuple[int | None, int | None]:
        try:
            payload = json.loads(match_ref or "{}")
            customer_id = int(payload["customer_id"]) if payload.get("customer_id") else None
            product_id = int(payload["product_id"]) if payload.get("product_id") else None
            return customer_id, product_id
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise EtlError(
                "ETL_MATCH_REF_INVALID",
                "客户及产品的预演匹配引用无效，请重新预演",
                status_code=409,
            ) from exc

    def _customer_preview_state(
        self,
        db: Session,
        data: dict[str, Any],
        allowed_update_fields: set[str],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        cache = context.setdefault("_preview_cache", {})
        index = cache.get("customer_product_customer_by_name")
        if index is None:
            index = {
                str(item.unit_name): {
                    "id": item.id,
                    "before": _customer_values(item),
                    "after": _customer_values(item),
                    "is_new": False,
                }
                for item in _owned_query(db, PurchaseUnit).all()
            }
            cache["customer_product_customer_by_name"] = index
        name = str(data.get("customer_name") or "").strip()
        state = index.get(name)
        if state is None:
            after = {
                "customer_name": name,
                "contact_person": optional_text(data.get("contact_person")),
                "contact_phone": optional_text(data.get("contact_phone")),
                "contact_address": optional_text(data.get("contact_address")),
            }
            state = {
                "id": None,
                "before": {},
                "after": after,
                "is_new": True,
                "input_values": {},
            }
            index[name] = state
        input_values = state.setdefault("input_values", {})
        conflicts: list[dict[str, Any]] = []
        for key, value in self._customer_data(data).items():
            if key == "customer_name":
                continue
            previous = input_values.get(key)
            if previous not in (None, "") and str(previous) != str(value):
                conflicts.append(
                    {
                        "code": "ETL_PARENT_FIELDS_CONFLICT",
                        "field": key,
                        "severity": "error",
                        "message": f"同一客户在文件中的{key}不一致，请先确认",
                    }
                )
            else:
                input_values[key] = value
        state["conflicts_in_row"] = conflicts
        if state["is_new"]:
            state["changed_in_row"] = False
            return state
        updates = {
            key: data.get(key)
            for key in allowed_update_fields & self._customer_fields
            if data.get(key) not in (None, "")
            and data.get(key) != state["after"].get(key)
        }
        if updates:
            state["after"] = {**state["after"], **updates}
            state["changed_in_row"] = True
        else:
            state["changed_in_row"] = False
        return state

    def _product_preview_state(
        self,
        db: Session,
        data: dict[str, Any],
        allowed_update_fields: set[str],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        product_data = self._product_data(data)
        cache = context.setdefault("_preview_cache", {})
        index = cache.get("customer_product_product_by_match_key")
        product_adapter = ProductAdapter()
        if index is None:
            index = {
                product_adapter._match_key(
                    {
                        "unit": item.unit,
                        "model_number": item.model_number,
                        "name": item.name,
                    }
                ): {
                    "id": item.id,
                    "before": model_values(item, ProductAdapter.fields),
                    "after": model_values(item, ProductAdapter.fields),
                    "is_new": False,
                }
                for item in _owned_query(db, Product).all()
            }
            cache["customer_product_product_by_match_key"] = index
        match_key = product_adapter._match_key(product_data)
        state = index.get(match_key)
        if state is None:
            state = {
                "id": None,
                "before": {},
                "after": json_safe(product_data),
                "is_new": True,
                "seen": True,
            }
            index[match_key] = state
            return state
        if state.get("seen"):
            state["duplicate_in_source"] = True
            return state
        state["seen"] = True
        updates = {
            key: product_data.get(key)
            for key in allowed_update_fields & self._product_fields
            if product_data.get(key) not in (None, "")
            and product_data.get(key) != state["after"].get(key)
        }
        if updates:
            state["after"] = {**state["after"], **updates}
            state["changed_in_row"] = True
        else:
            state["changed_in_row"] = False
        return state

    def preview(self, db, data, *, allowed_update_fields, context):
        issues = self.validate(data)
        if issues:
            return PreviewDecision("error", issues=issues, reason="validation_failed")
        customer = self._customer_preview_state(
            db, data, allowed_update_fields, context
        )
        if customer.get("conflicts_in_row"):
            return PreviewDecision(
                "error",
                before={"customer": json_safe(customer["before"]), "product": {}},
                after={"customer": json_safe(customer["after"]), "product": {}},
                issues=list(customer["conflicts_in_row"]),
                reason="linked_customer_fields_conflict",
            )
        product = self._product_preview_state(db, data, allowed_update_fields, context)
        before = {
            "customer": json_safe(customer["before"]),
            "product": json_safe(product["before"]),
        }
        after = {
            "customer": json_safe(customer["after"]),
            "product": json_safe(product["after"]),
            "relationship": {
                "customer_name": str(data.get("customer_name") or "").strip(),
                "product_unit": str(data.get("customer_name") or "").strip(),
            },
        }
        match_ref = self._match_ref(customer.get("id"), product.get("id"))
        if customer["is_new"] and not product["is_new"]:
            return PreviewDecision(
                "error",
                match_ref=match_ref,
                before=before,
                after=after,
                issues=[
                    {
                        "code": "ETL_ORPHAN_PRODUCT_REQUIRES_REPAIR",
                        "field": "customer_name",
                        "severity": "error",
                        "message": "发现产品存在但对应客户缺失，请先修复主数据关系",
                    }
                ],
                reason="orphan_product_requires_repair",
            )
        if product.get("duplicate_in_source"):
            return PreviewDecision(
                "skip",
                before=before,
                after=after,
                reason="duplicate_product_in_source_file",
            )
        if product["is_new"]:
            return PreviewDecision(
                "new",
                before=before,
                after=after,
                reason=(
                    "customer_and_product_not_found"
                    if customer["is_new"]
                    else "linked_product_not_found"
                ),
            )
        if (
            customer["is_new"]
            or customer.get("changed_in_row")
            or product.get("changed_in_row")
        ):
            return PreviewDecision(
                "update",
                match_ref=match_ref,
                before=before,
                after=after,
                reason="linked_customer_or_product_changed",
            )
        return PreviewDecision(
            "skip",
            match_ref=match_ref,
            before=before,
            after=after,
            reason="duplicate_customer_product_link",
        )

    def _ensure_customer(
        self,
        db: Session,
        data: dict[str, Any],
        allowed_update_fields: set[str],
        context: dict[str, Any],
    ) -> tuple[PurchaseUnit, bool, bool, dict[str, Any]]:
        name = str(data.get("customer_name") or "").strip()
        customer = (
            _owned_query(db, PurchaseUnit)
            .filter(PurchaseUnit.unit_name == name)
            .first()
        )
        created = customer is None
        if created:
            customer = PurchaseUnit(
                tenant_id=tenant_id_for_write(),
                unit_name=name,
                contact_person=optional_text(data.get("contact_person")),
                contact_phone=optional_text(data.get("contact_phone")),
                address=optional_text(data.get("contact_address")),
                is_active=True,
            )
            db.add(customer)
            db.flush()
        before = _customer_values(customer)
        updated = False
        if not created:
            for key in allowed_update_fields & self._customer_fields:
                model_field = _CUSTOMER_MODEL_FIELDS[key]
                value = data.get(key)
                if value not in (None, "") and value != getattr(customer, model_field):
                    setattr(customer, model_field, value)
                    updated = True
            if updated:
                db.flush()
        return customer, created, updated, before

    def execute_row(self, db, data, *, action, match_ref, allowed_update_fields, context):
        _customer_id, preview_product_id = self._parse_match_ref(match_ref)
        customer, customer_created, customer_updated, customer_before = (
            self._ensure_customer(db, data, allowed_update_fields, context)
        )
        product_data = self._product_data(data)
        product_adapter = ProductAdapter()
        product = (
            _owned_query(db, Product)
            .filter(Product.id == preview_product_id)
            .first()
            if preview_product_id
            else None
        )
        if product is None:
            product = product_adapter._match(db, product_data)
        product_created = False
        product_updated = False
        product_before = model_values(product, ProductAdapter.fields) if product else {}
        if action == "new":
            if product is not None:
                raise EtlError(
                    "ETL_MATCH_CHANGED",
                    "关联产品在预演后已存在，请重新预演",
                    status_code=409,
                )
            product = Product(
                tenant_id=tenant_id_for_write(),
                unit=str(product_data["unit"]),
                model_number=optional_text(product_data.get("model_number")),
                name=str(product_data.get("name") or ""),
                specification=optional_text(product_data.get("specification")),
                price=decimal_or_zero(product_data.get("price")),
                category=optional_text(product_data.get("category")),
                brand=optional_text(product_data.get("brand")),
                description=optional_text(product_data.get("description")),
            )
            db.add(product)
            db.flush()
            product_created = True
        elif product is None:
            raise EtlError(
                "ETL_MATCH_DISAPPEARED",
                "预演匹配的关联产品已不存在",
                status_code=409,
            )
        elif action == "update":
            for key in allowed_update_fields & self._product_fields:
                value = product_data.get(key)
                converted = decimal_or_zero(value) if key == "price" else optional_text(value)
                if value not in (None, "") and converted != getattr(product, key):
                    setattr(product, key, converted)
                    product_updated = True
            if product_updated:
                db.flush()
        after = {
            "customer": _customer_values(customer),
            "product": model_values(product, ProductAdapter.fields),
            "relationship": {
                "customer_name": customer.unit_name,
                "product_unit": product.unit,
            },
            "_etl": {
                "customer_created": customer_created,
                "customer_updated": customer_updated,
                "customer_before": customer_before,
                "product_created": product_created,
                "product_updated": product_updated,
                "product_before": product_before,
            },
        }
        return {
            "match_ref": self._match_ref(customer.id, product.id),
            "after": after,
        }

    def rollback_row(self, db, *, match_ref, before, after, context):
        customer_id, product_id = self._parse_match_ref(match_ref)
        metadata = after.get("_etl") if isinstance(after.get("_etl"), dict) else {}
        product_after = after.get("product") if isinstance(after.get("product"), dict) else {}
        product_before = (
            metadata.get("product_before")
            if isinstance(metadata.get("product_before"), dict)
            else {}
        )
        product = (
            _owned_query(db, Product).filter(Product.id == product_id).first()
            if product_id
            else None
        )
        if metadata.get("product_created"):
            if not product:
                raise EtlError("ETL_ROLLBACK_TARGET_MISSING", "关联产品撤销目标已不存在")
            assert_created_row_unchanged(
                product, product_after, ProductAdapter.fields, "关联产品"
            )
            db.delete(product)
            db.flush()
        elif metadata.get("product_updated"):
            if not product:
                raise EtlError("ETL_ROLLBACK_TARGET_MISSING", "关联产品撤销目标已不存在")
            assert_rollback_image_matches(
                product,
                product_before,
                product_after,
                ProductAdapter.fields,
                "关联产品",
            )
            for field in ProductAdapter.fields:
                if field.key in product_before:
                    value = product_before[field.key]
                    if field.key == "price":
                        value = decimal_or_zero(value)
                    setattr(product, field.key, value)
            db.flush()

        customer_after = (
            after.get("customer") if isinstance(after.get("customer"), dict) else {}
        )
        customer_before = (
            metadata.get("customer_before")
            if isinstance(metadata.get("customer_before"), dict)
            else {}
        )
        customer = (
            _owned_query(db, PurchaseUnit)
            .filter(PurchaseUnit.id == customer_id)
            .first()
            if customer_id
            else None
        )
        if metadata.get("customer_updated"):
            if not customer:
                raise EtlError("ETL_ROLLBACK_TARGET_MISSING", "关联客户撤销目标已不存在")
            changed = {
                key
                for key in customer_before
                if key in customer_after
                and str(customer_before.get(key)) != str(customer_after.get(key))
            }
            if not _customer_image_matches(customer, customer_after, keys=changed):
                raise EtlError(
                    "ETL_ROLLBACK_CONCURRENT_CHANGE",
                    "关联客户在本次导入后又被修改，已停止撤销以避免覆盖新数据",
                    status_code=409,
                )
            for key, model_field in _CUSTOMER_MODEL_FIELDS.items():
                if key in customer_before:
                    setattr(customer, model_field, customer_before[key])
        if metadata.get("customer_created"):
            if not customer:
                raise EtlError("ETL_ROLLBACK_TARGET_MISSING", "关联客户撤销目标已不存在")
            remaining_products = (
                _owned_query(db, Product)
                .filter(Product.unit == customer.unit_name)
                .count()
            )
            if remaining_products:
                raise EtlError(
                    "ETL_ROLLBACK_CONCURRENT_CHANGE",
                    "关联客户下仍有其他产品，已停止删除客户",
                    status_code=409,
                )
            if not _customer_image_matches(customer, customer_after):
                raise EtlError(
                    "ETL_ROLLBACK_CONCURRENT_CHANGE",
                    "关联客户在本次导入后又被修改，已停止撤销以避免删除新数据",
                    status_code=409,
                )
            db.delete(customer)
