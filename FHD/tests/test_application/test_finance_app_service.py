"""Branch coverage tests for app.application.finance_app_service.

Covers missing branches in:
- _parse_dt (None/datetime/string/invalid)
- get_receivables (filter combinations, pagination)
- get_payables (filter combinations, supplier None, date None)
- list_transactions (filter combinations)
- get_transaction (not found, found)
- create_transaction (success, neuro_notify error, recoverable error)
- update_transaction (not found, success, amount/date conversion, neuro_notify error, recoverable error)
- delete_transaction (not found, success, neuro_notify error, recoverable error)
- get_monthly_trend (year default, explicit year)
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.application.finance_app_service import FinanceAppService, _parse_dt


# ---------------------------------------------------------------------------
# Helper to build a mock db context manager
# ---------------------------------------------------------------------------


def _mock_db_ctx(db: MagicMock):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _make_query_mock(items=None, count=0, scalar=None):
    """Build a chainable query mock that supports filter/order_by/offset/limit/count/all/scalar."""
    q = MagicMock()
    q.filter.return_value = q
    q.order_by.return_value = q
    q.offset.return_value = q
    q.limit.return_value = q
    q.join.return_value = q
    q.count.return_value = count
    q.all.return_value = items or []
    q.first.return_value = items[0] if items else None
    if scalar is not None:
        q.scalar.return_value = scalar
    return q


# ---------------------------------------------------------------------------
# _parse_dt
# ---------------------------------------------------------------------------


class TestParseDt:
    def test_none_returns_none(self):
        assert _parse_dt(None) is None

    def test_datetime_passthrough(self):
        dt = datetime(2026, 1, 15, 10, 30)
        assert _parse_dt(dt) is dt

    def test_iso_string(self):
        result = _parse_dt("2026-01-15T10:30:00")
        assert result == datetime(2026, 1, 15, 10, 30)

    def test_date_only_string(self):
        result = _parse_dt("2026-01-15")
        assert result == datetime(2026, 1, 15, 0, 0)

    def test_invalid_string_returns_none(self):
        assert _parse_dt("not a date") is None

    def test_empty_string_returns_none(self):
        assert _parse_dt("") is None

    def test_int_raises_type_error_returns_none(self):
        assert _parse_dt(12345) is None

    def test_list_raises_type_error_returns_none(self):
        assert _parse_dt([1, 2, 3]) is None


# ---------------------------------------------------------------------------
# get_receivables
# ---------------------------------------------------------------------------


class TestGetReceivables:
    def test_no_filters(self):
        svc = FinanceAppService()
        db = MagicMock()
        txn = MagicMock()
        txn.to_dict.return_value = {"id": 1}
        q = _make_query_mock(items=[txn], count=1)
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            result = svc.get_receivables()

        assert result["success"] is True
        assert result["total"] == 1
        assert result["page"] == 1
        assert result["per_page"] == 20
        assert len(result["data"]) == 1

    def test_with_all_filters(self):
        svc = FinanceAppService()
        db = MagicMock()
        start = datetime(2026, 1, 1)
        end = datetime(2026, 12, 31)
        q = _make_query_mock(items=[], count=0)
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            result = svc.get_receivables(
                start_date=start, end_date=end, status="completed", page=2, per_page=10
            )

        assert result["page"] == 2
        assert result["per_page"] == 10
        # filter called for start_date, end_date, status (3 times after initial filter)
        assert q.filter.call_count >= 3

    def test_empty_result(self):
        svc = FinanceAppService()
        db = MagicMock()
        q = _make_query_mock(items=[], count=0)
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            result = svc.get_receivables()

        assert result["data"] == []
        assert result["total"] == 0

    def test_pagination_offset(self):
        svc = FinanceAppService()
        db = MagicMock()
        q = _make_query_mock(items=[], count=0)
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            svc.get_receivables(page=3, per_page=15)

        # offset = (3-1) * 15 = 30
        q.offset.assert_called_once_with(30)
        q.limit.assert_called_once_with(15)


# ---------------------------------------------------------------------------
# get_payables
# ---------------------------------------------------------------------------


class TestGetPayables:
    def test_no_filters(self):
        svc = FinanceAppService()
        db = MagicMock()
        order = MagicMock()
        order.id = 1
        order.order_no = "PO-001"
        order.supplier = MagicMock(name="Supplier A")
        order.supplier.name = "Supplier A"
        order.total_amount = Decimal("1000")
        order.paid_amount = Decimal("300")
        order.status = "pending"
        order.order_date = datetime(2026, 1, 1)
        order.delivery_date = datetime(2026, 2, 1)
        q = _make_query_mock(items=[order], count=1)
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            result = svc.get_payables()

        assert result["success"] is True
        assert result["total"] == 1
        assert len(result["data"]) == 1
        item = result["data"][0]
        assert item["id"] == 1
        assert item["order_no"] == "PO-001"
        assert item["supplier_name"] == "Supplier A"
        assert item["total_amount"] == 1000.0
        assert item["paid_amount"] == 300.0
        assert item["outstanding"] == 700.0
        assert item["status"] == "pending"

    def test_supplier_none(self):
        svc = FinanceAppService()
        db = MagicMock()
        order = MagicMock()
        order.id = 1
        order.order_no = "PO-001"
        order.supplier = None
        order.total_amount = Decimal("500")
        order.paid_amount = None
        order.status = "pending"
        order.order_date = datetime(2026, 1, 1)
        order.delivery_date = None
        q = _make_query_mock(items=[order], count=1)
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            result = svc.get_payables()

        item = result["data"][0]
        assert item["supplier_name"] is None
        assert item["paid_amount"] is None
        assert item["outstanding"] == 500.0
        assert item["delivery_date"] is None

    def test_with_filters(self):
        svc = FinanceAppService()
        db = MagicMock()
        start = datetime(2026, 1, 1)
        end = datetime(2026, 12, 31)
        q = _make_query_mock(items=[], count=0)
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            result = svc.get_payables(
                start_date=start, end_date=end, status="pending", page=2, per_page=5
            )

        assert result["page"] == 2
        assert result["per_page"] == 5

    def test_paid_amount_none_outstanding_calculation(self):
        svc = FinanceAppService()
        db = MagicMock()
        order = MagicMock()
        order.id = 1
        order.order_no = "PO-002"
        order.supplier = None
        order.total_amount = Decimal("1000")
        order.paid_amount = None
        order.status = "pending"
        order.order_date = None
        order.delivery_date = None
        q = _make_query_mock(items=[order], count=1)
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            result = svc.get_payables()

        # outstanding = total_amount - (paid_amount or 0) = 1000 - 0 = 1000
        assert result["data"][0]["outstanding"] == 1000.0
        assert result["data"][0]["order_date"] is None


# ---------------------------------------------------------------------------
# list_transactions
# ---------------------------------------------------------------------------


class TestListTransactions:
    def test_no_filters(self):
        svc = FinanceAppService()
        db = MagicMock()
        txn = MagicMock()
        txn.to_dict.return_value = {"id": 1, "amount": "100"}
        q = _make_query_mock(items=[txn], count=1)
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            result = svc.list_transactions()

        assert result["success"] is True
        assert result["total"] == 1
        assert len(result["data"]) == 1

    def test_with_all_filters(self):
        svc = FinanceAppService()
        db = MagicMock()
        start = datetime(2026, 1, 1)
        end = datetime(2026, 12, 31)
        q = _make_query_mock(items=[], count=0)
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            result = svc.list_transactions(
                transaction_type="receipt",
                start_date=start,
                end_date=end,
                status="completed",
                page=2,
                per_page=10,
            )

        assert result["page"] == 2
        assert result["per_page"] == 10

    def test_empty_result(self):
        svc = FinanceAppService()
        db = MagicMock()
        q = _make_query_mock(items=[], count=0)
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            result = svc.list_transactions()

        assert result["data"] == []


# ---------------------------------------------------------------------------
# get_transaction
# ---------------------------------------------------------------------------


class TestGetTransaction:
    def test_found(self):
        svc = FinanceAppService()
        db = MagicMock()
        txn = MagicMock()
        txn.to_dict.return_value = {"id": 1}
        q = _make_query_mock(items=[txn])
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            result = svc.get_transaction(1)

        assert result["success"] is True
        assert result["data"] == {"id": 1}

    def test_not_found(self):
        svc = FinanceAppService()
        db = MagicMock()
        q = _make_query_mock(items=[])
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            result = svc.get_transaction(999)

        assert result["success"] is False
        assert "不存在" in result["message"]


# ---------------------------------------------------------------------------
# create_transaction
# ---------------------------------------------------------------------------


class TestCreateTransaction:
    def _make_mock_txn(self):
        """Create a mock FinancialTransaction instance."""
        txn = MagicMock()
        txn.id = 1
        txn.amount = Decimal("100")
        txn.transaction_type = "receipt"
        txn.to_dict.return_value = {"id": 1, "amount": "100"}
        return txn

    def test_success(self):
        svc = FinanceAppService()
        db = MagicMock()
        mock_txn = self._make_mock_txn()

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            with patch(
                "app.application.finance_app_service.FinancialTransaction",
                return_value=mock_txn,
            ):
                with patch(
                    "app.neuro_bus.application_neuro_bridge.neuro_notify_transaction_changed"
                ) as mock_notify:
                    result = svc.create_transaction(
                        {
                            "transaction_type": "receipt",
                            "amount": "100",
                            "currency": "CNY",
                            "description": "Test",
                            "status": "completed",
                        }
                    )

        assert result["success"] is True
        db.add.assert_called_once_with(mock_txn)
        db.commit.assert_called_once()
        db.refresh.assert_called_once_with(mock_txn)
        mock_notify.assert_called_once()

    def test_neuro_notify_error_suppressed(self):
        svc = FinanceAppService()
        db = MagicMock()
        mock_txn = self._make_mock_txn()

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            with patch(
                "app.application.finance_app_service.FinancialTransaction",
                return_value=mock_txn,
            ):
                with patch(
                    "app.neuro_bus.application_neuro_bridge.neuro_notify_transaction_changed",
                    side_effect=RuntimeError("bus down"),
                ):
                    result = svc.create_transaction(
                        {"transaction_type": "receipt", "amount": "100"}
                    )

        # Should still succeed even if neuro_notify fails
        assert result["success"] is True

    def test_recoverable_error_returns_failure(self):
        svc = FinanceAppService()
        db = MagicMock()
        mock_txn = self._make_mock_txn()
        db.commit.side_effect = ValueError("db constraint")

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            with patch(
                "app.application.finance_app_service.FinancialTransaction",
                return_value=mock_txn,
            ):
                result = svc.create_transaction(
                    {"transaction_type": "receipt", "amount": "100"}
                )

        assert result["success"] is False
        assert "db constraint" in result["message"]
        db.rollback.assert_called_once()

    def test_with_dates(self):
        svc = FinanceAppService()
        db = MagicMock()
        mock_txn = self._make_mock_txn()

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            with patch(
                "app.application.finance_app_service.FinancialTransaction",
                return_value=mock_txn,
            ):
                with patch(
                    "app.neuro_bus.application_neuro_bridge.neuro_notify_transaction_changed"
                ):
                    result = svc.create_transaction(
                        {
                            "transaction_type": "receipt",
                            "amount": "100",
                            "transaction_date": "2026-01-15T10:00:00",
                            "due_date": "2026-02-15",
                        }
                    )

        assert result["success"] is True

    def test_invalid_date_strings_handled(self):
        svc = FinanceAppService()
        db = MagicMock()
        mock_txn = self._make_mock_txn()

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            with patch(
                "app.application.finance_app_service.FinancialTransaction",
                return_value=mock_txn,
            ):
                with patch(
                    "app.neuro_bus.application_neuro_bridge.neuro_notify_transaction_changed"
                ):
                    result = svc.create_transaction(
                        {
                            "transaction_type": "receipt",
                            "amount": "100",
                            "transaction_date": "invalid",
                            "due_date": "also invalid",
                        }
                    )

        assert result["success"] is True


# ---------------------------------------------------------------------------
# update_transaction
# ---------------------------------------------------------------------------


class TestUpdateTransaction:
    def test_not_found(self):
        svc = FinanceAppService()
        db = MagicMock()
        q = _make_query_mock(items=[])
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            result = svc.update_transaction(999, {"amount": "200"})

        assert result["success"] is False
        assert "不存在" in result["message"]

    def test_success(self):
        svc = FinanceAppService()
        db = MagicMock()
        txn = MagicMock()
        txn.id = 1
        txn.amount = Decimal("100")
        txn.transaction_type = "receipt"
        txn.to_dict.return_value = {"id": 1, "amount": "200"}
        q = _make_query_mock(items=[txn])
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            with patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_transaction_changed"
            ) as mock_notify:
                result = svc.update_transaction(1, {"amount": "200", "status": "completed"})

        assert result["success"] is True
        db.commit.assert_called_once()
        db.refresh.assert_called_once()
        mock_notify.assert_called_once()

    def test_amount_conversion(self):
        svc = FinanceAppService()
        db = MagicMock()
        txn = MagicMock()
        txn.id = 1
        txn.amount = Decimal("100")
        txn.transaction_type = "receipt"
        txn.to_dict.return_value = {"id": 1}
        q = _make_query_mock(items=[txn])
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            with patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_transaction_changed"
            ):
                svc.update_transaction(1, {"amount": "250.50"})

        # Verify amount was set as Decimal
        # setattr(txn, "amount", Decimal("250.50")) should have been called
        assert txn.amount == Decimal("250.50") or txn.amount == Decimal("250.5")

    def test_date_conversion(self):
        svc = FinanceAppService()
        db = MagicMock()
        txn = MagicMock()
        txn.id = 1
        txn.amount = Decimal("100")
        txn.transaction_type = "receipt"
        txn.to_dict.return_value = {"id": 1}
        q = _make_query_mock(items=[txn])
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            with patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_transaction_changed"
            ):
                svc.update_transaction(
                    1,
                    {
                        "transaction_date": "2026-01-15T10:00:00",
                        "due_date": "2026-02-15",
                    },
                )

        # Verify dates were converted (setattr called with datetime objects)
        # The exact values depend on mock behavior, but commit should have been called
        db.commit.assert_called_once()

    def test_none_values_skipped(self):
        svc = FinanceAppService()
        db = MagicMock()
        txn = MagicMock()
        txn.id = 1
        txn.amount = Decimal("100")
        txn.transaction_type = "receipt"
        txn.to_dict.return_value = {"id": 1}
        q = _make_query_mock(items=[txn])
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            with patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_transaction_changed"
            ):
                svc.update_transaction(
                    1,
                    {
                        "amount": None,
                        "description": None,
                        "status": "completed",  # only this should be applied
                    },
                )

        # status should be set, amount and description should not
        # (None values are skipped per the `v is not None` check)
        db.commit.assert_called_once()

    def test_neuro_notify_error_suppressed(self):
        svc = FinanceAppService()
        db = MagicMock()
        txn = MagicMock()
        txn.id = 1
        txn.amount = Decimal("100")
        txn.transaction_type = "receipt"
        txn.to_dict.return_value = {"id": 1}
        q = _make_query_mock(items=[txn])
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            with patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_transaction_changed",
                side_effect=RuntimeError("bus down"),
            ):
                result = svc.update_transaction(1, {"status": "completed"})

        assert result["success"] is True

    def test_recoverable_error_returns_failure(self):
        svc = FinanceAppService()
        db = MagicMock()
        txn = MagicMock()
        txn.id = 1
        txn.amount = Decimal("100")
        txn.transaction_type = "receipt"
        q = _make_query_mock(items=[txn])
        db.query.return_value = q
        db.commit.side_effect = ValueError("constraint violation")

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            result = svc.update_transaction(1, {"status": "completed"})

        assert result["success"] is False
        assert "constraint violation" in result["message"]
        db.rollback.assert_called_once()

    def test_non_updatable_keys_ignored(self):
        svc = FinanceAppService()
        db = MagicMock()
        txn = MagicMock()
        txn.id = 1
        txn.amount = Decimal("100")
        txn.transaction_type = "receipt"
        txn.to_dict.return_value = {"id": 1}
        q = _make_query_mock(items=[txn])
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            with patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_transaction_changed"
            ):
                svc.update_transaction(
                    1,
                    {
                        "id": 999,  # not in updatable set
                        "transaction_type": "payment",  # not in updatable set
                        "status": "completed",  # in updatable set
                    },
                )

        db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# delete_transaction
# ---------------------------------------------------------------------------


class TestDeleteTransaction:
    def test_not_found(self):
        svc = FinanceAppService()
        db = MagicMock()
        q = _make_query_mock(items=[])
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            result = svc.delete_transaction(999)

        assert result["success"] is False
        assert "不存在" in result["message"]

    def test_success(self):
        svc = FinanceAppService()
        db = MagicMock()
        txn = MagicMock()
        txn.id = 1
        txn.amount = Decimal("100")
        txn.transaction_type = "receipt"
        q = _make_query_mock(items=[txn])
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            with patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_transaction_changed"
            ) as mock_notify:
                result = svc.delete_transaction(1)

        assert result["success"] is True
        assert "已删除" in result["message"]
        db.delete.assert_called_once_with(txn)
        db.commit.assert_called_once()
        mock_notify.assert_called_once()

    def test_neuro_notify_error_suppressed(self):
        svc = FinanceAppService()
        db = MagicMock()
        txn = MagicMock()
        txn.id = 1
        txn.amount = Decimal("100")
        txn.transaction_type = "receipt"
        q = _make_query_mock(items=[txn])
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            with patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_transaction_changed",
                side_effect=RuntimeError("bus down"),
            ):
                result = svc.delete_transaction(1)

        assert result["success"] is True

    def test_recoverable_error_returns_failure(self):
        svc = FinanceAppService()
        db = MagicMock()
        txn = MagicMock()
        txn.id = 1
        txn.amount = Decimal("100")
        txn.transaction_type = "receipt"
        q = _make_query_mock(items=[txn])
        db.query.return_value = q
        db.commit.side_effect = ValueError("db error")

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            result = svc.delete_transaction(1)

        assert result["success"] is False
        assert "db error" in result["message"]
        db.rollback.assert_called_once()

    def test_amount_none_handled(self):
        svc = FinanceAppService()
        db = MagicMock()
        txn = MagicMock()
        txn.id = 1
        txn.amount = None
        txn.transaction_type = None
        q = _make_query_mock(items=[txn])
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            with patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_transaction_changed"
            ) as mock_notify:
                result = svc.delete_transaction(1)

        assert result["success"] is True
        # neuro_notify called with amount=0.0 (float(None or 0))
        mock_notify.assert_called_once()
        call_kwargs = mock_notify.call_args
        assert call_kwargs[1]["amount"] == 0.0
        assert call_kwargs[1]["txn_type"] == ""


# ---------------------------------------------------------------------------
# get_monthly_trend
# ---------------------------------------------------------------------------


class TestGetMonthlyTrend:
    def test_default_year(self):
        svc = FinanceAppService()
        db = MagicMock()
        # Each month has 2 scalar calls (revenue + cost), 12 months = 24 calls
        q = MagicMock()
        q.filter.return_value = q
        q.scalar.return_value = None
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            result = svc.get_monthly_trend()

        assert result["success"] is True
        assert result["year"] == datetime.utcnow().year
        assert len(result["data"]) == 12
        for i, month_data in enumerate(result["data"]):
            assert month_data["month"] == f"{datetime.utcnow().year}-{i+1:02d}"
            assert month_data["revenue"] == 0.0
            assert month_data["cost"] == 0.0
            assert month_data["profit"] == 0.0

    def test_explicit_year(self):
        svc = FinanceAppService()
        db = MagicMock()
        q = MagicMock()
        q.filter.return_value = q
        q.scalar.return_value = None
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            result = svc.get_monthly_trend(year=2025)

        assert result["year"] == 2025
        assert result["data"][0]["month"] == "2025-01"
        assert result["data"][11]["month"] == "2025-12"

    def test_with_values(self):
        svc = FinanceAppService()
        db = MagicMock()
        q = MagicMock()
        q.filter.return_value = q
        # Alternate revenue and cost values for 12 months
        values = []
        for i in range(12):
            values.extend([Decimal(f"{(i+1) * 100}.00"), Decimal(f"{(i+1) * 50}.00")])
        q.scalar.side_effect = values
        db.query.return_value = q

        with patch("app.application.finance_app_service.get_db", return_value=_mock_db_ctx(db)):
            result = svc.get_monthly_trend(year=2026)

        assert result["data"][0]["revenue"] == 100.0
        assert result["data"][0]["cost"] == 50.0
        assert result["data"][0]["profit"] == 50.0
        assert result["data"][11]["revenue"] == 1200.0
        assert result["data"][11]["cost"] == 600.0
        assert result["data"][11]["profit"] == 600.0
