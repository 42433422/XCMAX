"""Explicit quantity conversion for new shipment writes; never infer a package weight."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any


def shipment_quantity_hint(code: str) -> str:
    return {
        "SHIPMENT_SPEC_REQUIRED": "请补充计量单位和每件/每桶规格，或明确填写实际公斤数后再出单。",
        "SHIPMENT_SPEC_INVALID": "数量或规格无效，请填写有限、非负的数量及大于零的规格后再出单。",
    }.get(code, "")


class ShipmentQuantityValidationError(ValueError):
    def __init__(self, code: str, row_index: int | None = None):
        self.code = code
        self.row_index = row_index
        hint = shipment_quantity_hint(code)
        super().__init__((f"第 {row_index} 项：" if row_index else "") + hint)

    def result(self) -> dict[str, Any]:
        return {
            "success": False,
            "error_code": self.code,
            "message": str(self),
            "row_index": self.row_index,
            "doc_name": None,
            "file_path": None,
        }


def resolve_shipment_quantity(
    product: dict[str, Any], *, row_index: int | None = None
) -> tuple[int, float, float | None]:
    if not isinstance(product, dict):
        raise ShipmentQuantityValidationError("SHIPMENT_SPEC_INVALID", row_index)

    def number(value: Any, *, positive: bool = False) -> float:
        try:
            parsed = float(value)
        except (ValueError, TypeError, OverflowError):
            raise ShipmentQuantityValidationError("SHIPMENT_SPEC_INVALID", row_index) from None
        if (
            isinstance(value, bool)
            or not math.isfinite(parsed)
            or parsed < 0
            or (positive and parsed == 0)
        ):
            raise ShipmentQuantityValidationError("SHIPMENT_SPEC_INVALID", row_index)
        return parsed

    specs = [
        number(product[key], positive=True)
        for key in ("tin_spec", "spec", "weight_per_unit", "spec_per_tin")
        if key in product and product[key] is not None and product[key] != ""
    ]
    if specs and any(value != specs[0] for value in specs):
        raise ShipmentQuantityValidationError("SHIPMENT_SPEC_INVALID", row_index)
    spec = specs[0] if specs else None
    unit = str(product.get("unit") or product.get("quantity_unit") or "").strip().lower()
    if unit and unit not in {"kg", "公斤", "千克", "桶", "件", "个", "箱", "包", "袋", "瓶"}:
        raise ShipmentQuantityValidationError("SHIPMENT_SPEC_INVALID", row_index)
    kg = product.get("quantity_kg")
    if kg is None and unit in {"kg", "公斤", "千克"}:
        kg = product.get("quantity")
    if kg is None and product.get("quantity_tins") is None and "quantity" in product and not unit:
        raise ShipmentQuantityValidationError("SHIPMENT_SPEC_REQUIRED", row_index)
    primary = product.get("quantity_tins")
    if primary is None:
        primary = 0 if unit in {"kg", "公斤", "千克"} else product.get("quantity", 0)
    tins = number(0 if primary is None else primary)
    if not tins.is_integer():
        raise ShipmentQuantityValidationError("SHIPMENT_SPEC_INVALID", row_index)
    if kg is None:
        if spec is None:
            raise ShipmentQuantityValidationError("SHIPMENT_SPEC_REQUIRED", row_index)
        kg = tins * spec
    kg = number(kg)
    return int(tins), kg, spec


def validate_shipment_products(products: Sequence[Any]) -> None:
    for index, product in enumerate(products or [], 1):
        resolve_shipment_quantity(product, row_index=index)
