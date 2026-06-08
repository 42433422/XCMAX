"""发货单聚合使用的涂料行业值对象（来自 ``app/domain/value_objects.py`` 扁平模块）。"""

from __future__ import annotations

from app.domain.value_objects import ContactInfo, Money, OrderNumber, Quantity

__all__ = ["Quantity", "Money", "ContactInfo", "OrderNumber"]
