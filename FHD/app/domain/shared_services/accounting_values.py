"""Shared amount conversion and reference data for accounting services."""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def to_float(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def to_decimal(value: Any) -> Decimal:
    """Convert an accounting amount without introducing binary-float error."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


DEFAULT_CHART_OF_ACCOUNTS: list[dict[str, Any]] = [
    {"code": "1401", "name": "库存商品", "type": "asset", "debit_credit": "debit"},
    {"code": "2201", "name": "应付账款", "type": "liability", "debit_credit": "credit"},
    {"code": "1122", "name": "应收账款", "type": "asset", "debit_credit": "debit"},
    {"code": "1001", "name": "库存现金", "type": "asset", "debit_credit": "debit"},
    {"code": "6001", "name": "主营业务收入", "type": "revenue", "debit_credit": "credit"},
    {"code": "5001", "name": "主营业务成本", "type": "expense", "debit_credit": "debit"},
    {"code": "1405", "name": "原材料", "type": "asset", "debit_credit": "debit"},
    {"code": "2211", "name": "应付职工薪酬", "type": "liability", "debit_credit": "credit"},
]


AGING_BUCKETS: list[tuple[str, int, int]] = [
    ("0-30", 0, 30),
    ("31-60", 31, 60),
    ("61-90", 61, 90),
    ("90+", 91, 10**9),
]
