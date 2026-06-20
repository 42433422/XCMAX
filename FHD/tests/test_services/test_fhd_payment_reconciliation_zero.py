"""Tests for app.services.fhd_payment_reconciliation."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.services.fhd_payment_reconciliation import (
    _parse_dt,
    compute_fhd_period_snapshot,
)


class TestParseDt:
    """Tests for _parse_dt."""

    def test_none_returns_none(self) -> None:
        assert _parse_dt(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert _parse_dt("") is None

    def test_valid_iso_format(self) -> None:
        result = _parse_dt("2026-01-15T10:30:00")
        assert result is not None
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 15

    def test_valid_iso_with_timezone(self) -> None:
        result = _parse_dt("2026-01-15T10:30:00+08:00")
        assert result is not None

    def test_utc_z_suffix(self) -> None:
        result = _parse_dt("2026-01-15T10:30:00Z")
        assert result is not None

    def test_invalid_format_returns_none(self) -> None:
        result = _parse_dt("not-a-date")
        assert result is None


class TestComputeFhdPeriodSnapshot:
    """Tests for compute_fhd_period_snapshot."""

    def test_returns_expected_structure(self) -> None:
        start = datetime(2026, 1, 1)
        end = datetime(2026, 1, 31)
        result = compute_fhd_period_snapshot(start, end)
        assert "period_start" in result
        assert "period_end" in result
        assert "orders" in result
        assert "totals" in result

    def test_period_start_end(self) -> None:
        start = datetime(2026, 1, 1)
        end = datetime(2026, 1, 31)
        result = compute_fhd_period_snapshot(start, end)
        assert result["period_start"] == start.isoformat()
        assert result["period_end"] == end.isoformat()

    def test_orders_is_empty_list(self) -> None:
        start = datetime(2026, 1, 1)
        end = datetime(2026, 1, 31)
        result = compute_fhd_period_snapshot(start, end)
        assert result["orders"] == []

    def test_totals_is_empty_dict(self) -> None:
        start = datetime(2026, 1, 1)
        end = datetime(2026, 1, 31)
        result = compute_fhd_period_snapshot(start, end)
        assert result["totals"] == {}
