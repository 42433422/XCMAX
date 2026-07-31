"""Target-specific projections for deterministic delivery-note regions."""

from __future__ import annotations

from typing import Any

_SHIPMENT_FIELD_MAP = {
    "customer_name": "purchase_unit",
    "name": "product_name",
    "specification": "tin_spec",
    "price": "unit_price",
}


def project_delivery_region(
    values: dict[str, Any],
    *,
    target_type: str,
    meta: dict[str, Any],
) -> dict[str, Any]:
    """Project one detected delivery line into a supported ETL target schema."""
    if target_type != "shipment_records":
        return dict(values)

    projected: dict[str, Any] = {}
    for key, value in values.items():
        target_key = _SHIPMENT_FIELD_MAP.get(key, key)
        if target_key in {
            "purchase_unit",
            "product_name",
            "model_number",
            "quantity_kg",
            "quantity_tins",
            "tin_spec",
            "unit_price",
            "amount",
        }:
            projected[target_key] = value
    order_number = str(meta.get("order_number") or "").strip()
    if order_number:
        projected["external_order_no"] = order_number
    return projected


def region_source_features(
    *,
    target_type: str,
    regions: list[dict[str, Any]],
    rows: int,
) -> dict[str, Any]:
    selected = [region for region in regions if region.get("status") == "selected"]
    excluded = [region for region in regions if region.get("status") == "excluded"]
    return {
        "kind": (
            "workbook_delivery_regions"
            if target_type == "shipment_records"
            else "workbook_regions"
        ),
        "business_document_type": "delivery_note",
        "suggested_target_type": (
            "shipment_records"
            if target_type == "shipment_records"
            else "customer_products"
        ),
        "region_summary": {
            "candidates": len(regions),
            "selected": len(selected),
            "excluded": len(excluded),
            "business_rows": rows,
            "customers": sorted(
                {
                    str(region.get("customer_name") or "")
                    for region in selected
                    if region.get("customer_name")
                }
            ),
        },
    }


__all__ = ["project_delivery_region", "region_source_features"]
