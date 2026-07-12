"""Application facade for FHD model-payment reconciliation snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def parse_period_dt(value: str) -> datetime | None:
    from app.services.fhd_payment_reconciliation import _parse_dt

    return _parse_dt(value)


def compute_fhd_period_snapshot(start: datetime, end: datetime) -> dict[str, Any]:
    from app.services.fhd_payment_reconciliation import compute_fhd_period_snapshot as impl

    return impl(start, end)


__all__ = ["compute_fhd_period_snapshot", "parse_period_dt"]
