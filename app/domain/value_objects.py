"""扁平值对象模块（v10 兼容 shim，转发至 value_objects_compat）。"""

from __future__ import annotations

from app.domain.value_objects_compat import (
    ContactInfo,
    ModelNumber,
    Money,
    OrderNumber,
    Price,
    Quantity,
)

__all__ = [
    "ContactInfo",
    "ModelNumber",
    "Money",
    "OrderNumber",
    "Price",
    "Quantity",
]
