"""Payment gateway aggregates (read-heavy; writes delegated to Java)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OrderRef:
    order_no: str
    user_id: int
    amount: float
    status: str = ""
