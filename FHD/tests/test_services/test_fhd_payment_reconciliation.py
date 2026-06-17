"""Tests for app.services.fhd_payment_reconciliation."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.services.fhd_payment_reconciliation import (
    _parse_dt,
    compute_fhd_period_snapshot,
)


class TestParseDt:
    def test_none_returns_none(self):
        assert _parse_dt(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_dt("") is None

    def test_valid_iso_format(self):
        result = _parse_dt("2026-06-16T10:30:00")
        assert result is not None
        assert result.year == 2026
        assert result.month == 6
        assert result.day == 16

    def test_iso_with_z_suffix(self):
        result = _parse_dt("2026-06-16T10:30:00Z")
        assert result is not None
        assert result.year == 2026

    def test_iso_with_timezone(self):
        result = _parse_dt("2026-06-16T10:30:00+08:00")
        assert result is not None

    def test_invalid_format_returns_none(self):
        assert _parse_dt("not-a-date") is None


class TestComputeFhdPeriodSnapshot:
    def test_returns_dict_with_required_keys(self):
        start = datetime(2026, 6, 1)
        end = datetime(2026, 6, 30)
        result = compute_fhd_period_snapshot(start, end)
        assert "period_start" in result
        assert "period_end" in result
        assert "orders" in result
        assert "totals" in result

    def test_period_start_end_match_input(self):
        start = datetime(2026, 6, 1)
        end = datetime(2026, 6, 30)
        result = compute_fhd_period_snapshot(start, end)
        assert result["period_start"] == start.isoformat()
        assert result["period_end"] == end.isoformat()

    def test_orders_initially_empty(self):
        start = datetime(2026, 6, 1)
        end = datetime(2026, 6, 30)
        result = compute_fhd_period_snapshot(start, end)
        assert result["orders"] == []
        assert result["totals"] == {}
