"""统一查询网关。"""

from __future__ import annotations

from app.services.unified_query_service import (  # noqa: F401
    find_product,
    find_purchase_unit,
    get_product_names,
    get_purchase_units,
    query_service,
)

__all__ = [
    "find_product",
    "find_purchase_unit",
    "get_product_names",
    "get_purchase_units",
    "query_service",
]
