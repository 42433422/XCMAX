"""Shared persistence helpers for customer/product ETL adapters."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy.orm import Session

from app.application.etl.targets.base import json_safe
from app.db.models.purchase_unit import PurchaseUnit
from app.infrastructure.tenant_scope import apply_tenant_filter

CUSTOMER_MODEL_FIELDS = {
    "customer_name": "unit_name",
    "contact_person": "contact_person",
    "contact_phone": "contact_phone",
    "contact_address": "address",
}


def customer_values(obj: PurchaseUnit) -> dict[str, Any]:
    return cast(
        "dict[str, Any]",
        json_safe(
            {
                target: getattr(obj, model_field, None)
                for target, model_field in CUSTOMER_MODEL_FIELDS.items()
            }
        ),
    )


def customer_image_matches(
    obj: PurchaseUnit,
    expected: dict[str, Any],
    *,
    keys: set[str] | None = None,
) -> bool:
    current = customer_values(obj)
    selected = keys if keys is not None else set(expected)
    return all(
        (current.get(key) is None and expected.get(key) is None)
        or str(current.get(key)) == str(expected.get(key))
        for key in selected
        if key in expected
    )


def owned_query(db: Session, model: Any):
    return apply_tenant_filter(db.query(model), model)
