"""Quantity normalization and backorder-source parsing for fulfillment."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from app.db.models import SalesOrderItem

_SOURCE_ITEM_RE = re.compile(r"backorder source_item_id=(\d+)\Z")


def to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def parse_source_item_id(remark: str | None) -> int | None:
    """Return the source item id only for an exact backorder marker."""
    if not remark:
        return None
    match = _SOURCE_ITEM_RE.fullmatch(remark)
    return int(match.group(1)) if match is not None else None


def effective_ordered(item: SalesOrderItem) -> Decimal:
    """Prefer ordered_quantity and fall back to the legacy quantity field."""
    ordered = to_decimal(getattr(item, "ordered_quantity", None))
    return ordered if ordered > 0 else to_decimal(getattr(item, "quantity", None))
