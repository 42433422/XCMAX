"""兼容入口；领域侧请用 domain.shipment.value_objects。"""

from __future__ import annotations

from app.domain.shipment.value_objects import ContactInfo, Money, OrderNumber, Quantity

__all__ = ["Quantity", "Money", "ContactInfo", "OrderNumber"]
