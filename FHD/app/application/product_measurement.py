"""Resolve measured units without treating legacy customer labels as quantities."""

from app.infrastructure.repositories.product_query_helpers import TRIVIAL_MEASURE_UNITS


def product_measurement_unit(product) -> str | None:
    explicit = getattr(product, "measurement_unit", None)
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    legacy = getattr(product, "unit", None)
    if isinstance(legacy, str) and legacy.strip() in TRIVIAL_MEASURE_UNITS | {
        "kg",
        "g",
        "t",
        "m",
        "cm",
        "mm",
        "L",
        "ml",
        "pcs",
    }:
        return legacy.strip()
    return None
