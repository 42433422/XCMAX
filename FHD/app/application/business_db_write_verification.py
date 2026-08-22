"""Tenant-scoped read-after-write verification for the Business Harness."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.exc import SQLAlchemyError


def _nested_id(value: Any) -> int | None:
    if not isinstance(value, dict):
        return None
    for key in ("id", "customer_id", "product_id", "material_id", "record_id"):
        try:
            record_id = int(value.get(key) or 0)
        except (TypeError, ValueError):
            record_id = 0
        if record_id > 0:
            return record_id
    for key in ("data", "raw", "result", "record", "shipment"):
        nested_record_id = _nested_id(value.get(key))
        if nested_record_id:
            return nested_record_id
    return None


def _normalized_fields(payload: dict[str, Any]) -> dict[str, Any]:
    nested = payload.get("changes")
    if not isinstance(nested, dict):
        nested = payload.get("fields")
    return dict(nested) if isinstance(nested, dict) else dict(payload)


def _model_config(entity: str):
    if entity == "customers":
        from app.db.models.purchase_unit import PurchaseUnit

        return (
            PurchaseUnit,
            {
                "unit_name": "unit_name",
                "customer_name": "unit_name",
                "name": "unit_name",
                "contact_person": "contact_person",
                "contact_phone": "contact_phone",
                "contact_address": "address",
                "address": "address",
            },
            ("unit_name", "customer_name", "name"),
        )
    if entity == "products":
        from app.db.models.product import Product

        return (
            Product,
            {
                "name_or_model": "name",
                "product_name": "name",
                "name": "name",
                "model_number": "model_number",
                "product_code": "model_number",
                "unit_price": "price",
                "price": "price",
                "measure_unit": "unit",
                "unit": "unit",
            },
            ("model_number", "product_code", "product_name", "name", "name_or_model"),
        )
    if entity == "materials":
        from app.db.models.material import Material

        return (
            Material,
            {
                "material_code": "material_code",
                "material_name": "name",
                "name": "name",
                "unit_price": "unit_price",
                "quantity": "quantity",
            },
            ("material_code", "material_name", "name"),
        )
    if entity == "shipment_records":
        from app.db.models.shipment import ShipmentRecord

        return (
            ShipmentRecord,
            {
                "purchase_unit": "purchase_unit",
                "unit_name": "purchase_unit",
                "product_name": "product_name",
                "model_number": "model_number",
                "status": "status",
            },
            ("id", "record_id"),
        )
    raise ValueError(f"unsupported entity: {entity}")


def _same_value(actual: Any, expected: Any) -> bool:
    if isinstance(actual, Decimal):
        try:
            return actual == Decimal(str(expected))
        except (ValueError, TypeError):
            return False
    if isinstance(actual, float):
        try:
            return abs(actual - float(expected)) < 1e-9
        except (ValueError, TypeError):
            return False
    return actual == expected or str(actual) == str(expected)


def verify_business_db_write(
    *, entity: str, operation: str, payload: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    """Return a success result only after committed tenant data can be read back."""

    if not result.get("success"):
        return result

    from app.db.session import get_db
    from app.infrastructure.tenant_scope import tenant_id_for_write

    tenant_id = tenant_id_for_write()
    verification: dict[str, Any] = {
        "verified": False,
        "entity": entity,
        "operation": operation,
        "tenant_id": tenant_id,
        "state": "unverified",
        "checked_fields": [],
    }
    try:
        model, field_map, selector_keys = _model_config(entity)
        record_id = _nested_id(result) or _nested_id(payload)
        fields = _normalized_fields(payload)
        with get_db() as db:
            query = db.query(model).filter(model.tenant_id == tenant_id)
            if record_id:
                query = query.filter(model.id == record_id)
            else:
                selector = next(
                    (
                        (field_map.get(key, key), fields.get(key))
                        for key in selector_keys
                        if fields.get(key) not in (None, "")
                    ),
                    None,
                )
                if selector is None:
                    verification["reason"] = "write_result_missing_identity"
                    return _failed_result(result, verification)
                column_name, value = selector
                query = query.filter(getattr(model, column_name) == value)
            rows = query.limit(2).all()
            snapshots: list[dict[str, Any]] = [
                {
                    "id": int(row.id),
                    "is_active": bool(row.is_active) if hasattr(row, "is_active") else None,
                    "values": {
                        column_name: getattr(row, column_name)
                        for column_name in set(field_map.values())
                    },
                }
                for row in rows
            ]

        if len(snapshots) > 1:
            verification["reason"] = "ambiguous_readback"
            return _failed_result(result, verification)
        record = snapshots[0] if snapshots else None
        if record_id:
            verification["record_id"] = record_id

        if operation == "delete":
            inactive = record is not None and record["is_active"] is False
            verification["state"] = (
                "absent" if record is None else "inactive" if inactive else "present"
            )
            verification["verified"] = record is None or inactive
            if not verification["verified"]:
                verification["reason"] = "record_still_active"
                return _failed_result(result, verification)
            return {**result, "business_verification": verification}

        if record is None:
            verification.update(state="absent", reason="record_not_found")
            return _failed_result(result, verification)
        if record["is_active"] is False:
            verification.update(state="inactive", reason="record_inactive")
            return _failed_result(result, verification)

        checked: list[str] = []
        for input_name, column_name in field_map.items():
            if input_name not in fields or fields[input_name] in (None, ""):
                continue
            if not _same_value(record["values"][column_name], fields[input_name]):
                verification.update(
                    state="present", reason="field_mismatch", checked_fields=checked
                )
                return _failed_result(result, verification)
            checked.append(column_name)
        verification.update(
            verified=True,
            state="present",
            record_id=record["id"],
            checked_fields=sorted(set(checked)),
        )
        return {**result, "business_verification": verification}
    except (AttributeError, RuntimeError, SQLAlchemyError, TypeError, ValueError):
        verification["reason"] = "readback_unavailable"
        return _failed_result(result, verification)


def _failed_result(result: dict[str, Any], verification: dict[str, Any]) -> dict[str, Any]:
    return {
        **result,
        "success": False,
        "error_code": "business_write_verification_failed",
        "message": "业务写入未通过数据库回查，已按失败处理。",
        "business_verification": verification,
    }


__all__ = ["verify_business_db_write"]
