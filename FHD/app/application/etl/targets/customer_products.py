"""Linked customer and product aggregate ETL adapter."""

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
from app.application.etl.targets.customer_product_preview import (
    CustomerProductPreviewMixin,
)
from app.application.etl.targets.customer_product_support import (
    CUSTOMER_MODEL_FIELDS,
    customer_image_matches,
    customer_values,
    owned_query,
)
from app.application.etl.targets.helpers import (
    assert_created_row_unchanged,
    assert_rollback_image_matches,
    decimal_or_zero,
    model_values,
    optional_text,
)
from app.application.etl.targets.products import ProductAdapter
from app.db.models.product import Product
from app.db.models.purchase_unit import PurchaseUnit
from app.infrastructure.tenant_scope import tenant_id_for_write


class CustomerProductsAdapter(CustomerProductPreviewMixin, TargetAdapter):
    """One logical target for the purchase-unit/product aggregate."""

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

    _customer_fields = frozenset(CUSTOMER_MODEL_FIELDS)
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
            key: data.get(key) for key in CUSTOMER_MODEL_FIELDS if data.get(key) not in (None, "")
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

    def preview(self, db, data, *, allowed_update_fields, context):
        issues = self.validate(data)
        if issues:
            return PreviewDecision("error", issues=issues, reason="validation_failed")
        customer = self._customer_preview_state(db, data, allowed_update_fields, context)
        if customer.get("conflicts_in_row"):
            return PreviewDecision(
                "error",
                before={"customer": json_safe(customer["before"]), "product": {}},
                after={"customer": json_safe(customer["after"]), "product": {}},
                issues=list(customer["conflicts_in_row"]),
                reason="linked_customer_fields_conflict",
            )
        product = self._product_preview_state(db, data, allowed_update_fields, context)
        if product.get("model_ambiguity_issues"):
            return PreviewDecision(
                "error",
                before={
                    "customer": json_safe(customer["before"]),
                    "product": json_safe(product["before"]),
                },
                after={
                    "customer": json_safe(customer["after"]),
                    "product": json_safe(product["after"]),
                },
                issues=list(product["model_ambiguity_issues"]),
                reason="linked_product_model_ambiguous",
            )
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
        if customer["is_new"] or customer.get("changed_in_row") or product.get("changed_in_row"):
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
        customer = owned_query(db, PurchaseUnit).filter(PurchaseUnit.unit_name == name).first()
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
        before = customer_values(customer)
        updated = False
        if not created:
            for key in allowed_update_fields & self._customer_fields:
                model_field = CUSTOMER_MODEL_FIELDS[key]
                value = data.get(key)
                if value not in (None, "") and value != getattr(customer, model_field):
                    setattr(customer, model_field, value)
                    updated = True
            if updated:
                db.flush()
        return customer, created, updated, before

    def execute_row(self, db, data, *, action, match_ref, allowed_update_fields, context):
        _customer_id, preview_product_id = self._parse_match_ref(match_ref)
        product_data = self._product_data(data)
        product_adapter = ProductAdapter()
        if action == "new":
            ambiguity = product_adapter.model_ambiguity_issue(
                product_data,
                product_adapter._same_name_candidates(db, product_data),
                exact_match=False,
            )
            if ambiguity:
                raise EtlError(ambiguity["code"], ambiguity["message"], status_code=409)
        customer, customer_created, customer_updated, customer_before = self._ensure_customer(
            db, data, allowed_update_fields, context
        )
        product = (
            owned_query(db, Product).filter(Product.id == preview_product_id).first()
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
            "customer": customer_values(customer),
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
            owned_query(db, Product).filter(Product.id == product_id).first()
            if product_id
            else None
        )
        if metadata.get("product_created"):
            if not product:
                raise EtlError("ETL_ROLLBACK_TARGET_MISSING", "关联产品撤销目标已不存在")
            assert_created_row_unchanged(product, product_after, ProductAdapter.fields, "关联产品")
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

        customer_after = after.get("customer") if isinstance(after.get("customer"), dict) else {}
        customer_before = (
            metadata.get("customer_before")
            if isinstance(metadata.get("customer_before"), dict)
            else {}
        )
        customer = (
            owned_query(db, PurchaseUnit).filter(PurchaseUnit.id == customer_id).first()
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
            if not customer_image_matches(customer, customer_after, keys=changed):
                raise EtlError(
                    "ETL_ROLLBACK_CONCURRENT_CHANGE",
                    "关联客户在本次导入后又被修改，已停止撤销以避免覆盖新数据",
                    status_code=409,
                )
            for key, model_field in CUSTOMER_MODEL_FIELDS.items():
                if key in customer_before:
                    setattr(customer, model_field, customer_before[key])
        if metadata.get("customer_created"):
            if not customer:
                raise EtlError("ETL_ROLLBACK_TARGET_MISSING", "关联客户撤销目标已不存在")
            remaining_products = (
                owned_query(db, Product).filter(Product.unit == customer.unit_name).count()
            )
            if remaining_products:
                raise EtlError(
                    "ETL_ROLLBACK_CONCURRENT_CHANGE",
                    "关联客户下仍有其他产品，已停止删除客户",
                    status_code=409,
                )
            if not customer_image_matches(customer, customer_after):
                raise EtlError(
                    "ETL_ROLLBACK_CONCURRENT_CHANGE",
                    "关联客户在本次导入后又被修改，已停止撤销以避免删除新数据",
                    status_code=409,
                )
            db.delete(customer)
