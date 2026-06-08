"""发货单等业务使用的订单号值对象。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class OrderNumber:
    value: str

    def __post_init__(self) -> None:
        v = str(self.value or "").strip()
        if not v:
            raise ValueError("订单号不能为空")
        object.__setattr__(self, "value", v)

    def __str__(self) -> str:
        return str(self.value or "")

    @classmethod
    def generate(cls) -> OrderNumber:
        return cls(f"SO-{uuid.uuid4().hex[:12].upper()}")
