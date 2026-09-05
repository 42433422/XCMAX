"""Customer master-data ETL adapter."""

from __future__ import annotations

from app.application.etl.errors import EtlError
from app.application.etl.targets.base import (
    PreviewDecision,
    TargetAdapter,
    TargetField,
    json_safe,
)
from app.application.etl.targets.customer_product_support import (
    CUSTOMER_MODEL_FIELDS,
    customer_image_matches,
    customer_values,
    owned_query,
)
from app.application.etl.targets.helpers import optional_text
from app.application.etl.targets.rollback_compare_swap import delete_created_row, restore_fields
from app.db.models.purchase_unit import PurchaseUnit
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
            index = {str(item.unit_name): item for item in owned_query(db, PurchaseUnit).all()}
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
        before = customer_values(obj)
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
                owned_query(db, PurchaseUnit)
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
            return {"match_ref": str(obj.id), "after": customer_values(obj)}
        obj = owned_query(db, PurchaseUnit).filter(PurchaseUnit.id == int(match_ref)).first()
        if not obj:
            raise EtlError("ETL_MATCH_DISAPPEARED", "预演匹配的客户已不存在", status_code=409)
        if action == "update":
            for key in allowed_update_fields:
                model_field = CUSTOMER_MODEL_FIELDS.get(key)
                if model_field and data.get(key) not in (None, ""):
                    setattr(obj, model_field, data[key])
            db.flush()
        return {"match_ref": str(obj.id), "after": customer_values(obj)}

    def rollback_row(self, db, *, match_ref, before, after, context):
        obj = owned_query(db, PurchaseUnit).filter(PurchaseUnit.id == int(match_ref)).first()
        if before:
            if not obj:
                raise EtlError("ETL_ROLLBACK_TARGET_MISSING", "客户撤销目标已不存在")
            changed = {
                key
                for key in before
                if key in after and str(before.get(key)) != str(after.get(key))
            }
            if not customer_image_matches(obj, after, keys=changed):
                raise EtlError(
                    "ETL_ROLLBACK_CONCURRENT_CHANGE",
                    "客户在本次导入后又被修改，已停止撤销以避免覆盖新数据",
                    status_code=409,
                )
            restore_fields(
                db,
                obj,
                {
                    CUSTOMER_MODEL_FIELDS[key]: before[key]
                    for key in changed
                    if key in CUSTOMER_MODEL_FIELDS
                },
                "客户",
            )
        elif obj:
            if not customer_image_matches(obj, after):
                raise EtlError(
                    "ETL_ROLLBACK_CONCURRENT_CHANGE",
                    "客户在本次导入后又被修改，已停止撤销以避免删除新数据",
                    status_code=409,
                )
            delete_created_row(db, obj, "客户")
