"""发货单聚合使用的涂料行业值对象（``value_objects_compat`` 兼容层）。"""

from __future__ import annotations

from app.domain.value_objects_compat import ContactInfo, Money, OrderNumber, Quantity

__all__ = ["Quantity", "Money", "ContactInfo", "OrderNumber"]
