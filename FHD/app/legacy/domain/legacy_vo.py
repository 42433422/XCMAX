"""发货单聚合使用的涂料行业值对象（兼容入口；领域侧请用 domain.shipment.value_objects）。"""

from __future__ import annotations

from app.legacy.domain.value_objects_compat import ContactInfo, Money, OrderNumber, Quantity

__all__ = ["Quantity", "Money", "ContactInfo", "OrderNumber"]
