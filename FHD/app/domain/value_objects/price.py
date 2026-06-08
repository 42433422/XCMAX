"""单价与折扣（订单行计价）。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .quantity import Quantity


@dataclass(frozen=True)
class Price:
    unit_price: float
    discount_rate: float = 1.0

    def __post_init__(self) -> None:
        if self.unit_price < 0:
            raise ValueError("单价不能为负数")
        if not 0 <= self.discount_rate <= 1:
            raise ValueError("折扣率必须在 0-1 之间")

    def final_price(self) -> float:
        return float(self.unit_price) * float(self.discount_rate)

    def calculate_amount(self, quantity: Quantity) -> float:
        return float(Decimal(str(self.final_price())) * quantity.value)
