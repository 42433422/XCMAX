"""FHD 支付订单对账区间快照（MODstore reconciliation 合并用）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def compute_fhd_period_snapshot(start: datetime, end: datetime) -> dict[str, Any]:
    return {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "orders": [],
        "totals": {},
    }
