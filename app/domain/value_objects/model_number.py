"""产品型号等使用的值对象。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelNumber:
    value: str

    def __post_init__(self) -> None:
        v = str(self.value or "").strip()
        if not v:
            raise ValueError("型号不能为空")
        object.__setattr__(self, "value", v)

    def __str__(self) -> str:
        return str(self.value or "")

    def matches(self, other: ModelNumber) -> bool:
        return self.value.lower() == other.value.lower()

    def contains(self, fragment: str) -> bool:
        return str(fragment or "").lower() in self.value.lower()
