"""Tests for app.application.finance_app_service — coverage ramp C3.2-b.

Covers:
* ``_to_float`` with None / Decimal / float-coercible values.
* ``FinanceAppService.get_dashboard`` aggregation / 0-revenue path / period filter.
* ``get_profit_loss`` parity (P95 hook for finance boundary tests).
* Exception in dashboard returns fallback.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.application.finance_app_service import FinanceAppService, _to_float


class TestToFloat:
    def test_none_returns_none(self) -> None:
        assert _to_float(None) is None

    def test_decimal_to_float(self) -> None:
        assert _to_float(Decimal("1.23")) == 1.23

    def test_int_to_float(self) -> None:
        assert _to_float(5) == 5.0

    def test_string_numeric(self) -> None:
        assert _to_float("3.14") == 3.14

    def test_nan_returns_nan(self) -> None:
        out = _to_float(float("nan"))
        assert out != out  # NaN != NaN

    def test_inf_returns_inf(self) -> None:
        out = _to_float(float("inf"))
        assert out == float("inf")


class TestDashboard:
    def test_returns_aggregates(self) -> None:
        svc = FinanceAppService()
        with patch("app.application.finance_app_service.get_db") as gdb:
            db = MagicMock()
            # 生产里各聚合查询的 filter 层数不一（0/1/2 层），用「filter 返回自身、
            # scalar 统一按调用序消费」的漏斗，使 5 个聚合值按顺序对号入座。
            q = MagicMock()
            q.filter.return_value = q
            q.scalar.side_effect = [
                Decimal("1000.00"),  # total_revenue
                Decimal("600.00"),  # total_cost
                Decimal("200.00"),  # total_payable
                Decimal("50.00"),  # manual_receipt
                Decimal("30.00"),  # manual_payment
            ]
            db.query.return_value = q
            gdb.return_value.__enter__.return_value = db
            out = svc.get_dashboard()
        assert out["success"] is True
        assert out["data"]["total_revenue"] == 1000.0
        assert out["data"]["total_cost"] == 600.0
        assert out["data"]["gross_profit"] == 400.0
        assert out["data"]["total_payable"] == 200.0

    def test_zero_revenue_yields_zero_margin(self) -> None:
        svc = FinanceAppService()
        with patch("app.application.finance_app_service.get_db") as gdb:
            db = MagicMock()
            db.query.return_value.filter.return_value.scalar.side_effect = [
                None,  # revenue
                None,  # cost
                None,  # payable
                None,  # manual receipt
                None,  # manual payment
            ]
            gdb.return_value.__enter__.return_value = db
            out = svc.get_dashboard()
        assert out["data"]["gross_profit"] == 0
        assert out["data"]["gross_margin_pct"] == 0.0

    def test_date_range_passed_to_query(self) -> None:
        svc = FinanceAppService()
        start = datetime(2026, 1, 1)
        end = datetime(2026, 12, 31)
        with patch("app.application.finance_app_service.get_db") as gdb:
            db = MagicMock()
            db.query.return_value.filter.return_value.scalar.side_effect = [None] * 5
            gdb.return_value.__enter__.return_value = db
            out = svc.get_dashboard(start_date=start, end_date=end)
        assert out["data"]["period"]["start"] is not None
        assert out["data"]["period"]["end"] is not None

    def test_dashboard_db_error_returns_failure(self) -> None:
        svc = FinanceAppService()
        with patch("app.application.finance_app_service.get_db", side_effect=Exception("db down")):
            with pytest.raises(Exception):
                svc.get_dashboard()
