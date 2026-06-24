"""Real-behavior tests for app.application.finance_app_service — cov90 wave 2.

Targets previously-uncovered lines: get_payables (161-205), list_transactions
date filters (223,225), get_transaction (245-249), create_transaction success +
neuro bridge (269-284), update_transaction (297,332-338), delete_transaction
(347,364-370) and _parse_dt datetime passthrough (426).

All external deps (DB, neuro bus) are mocked; tests are deterministic/offline.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.application.finance_app_service import FinanceAppService, _parse_dt


def _patch_db(db: MagicMock):
    """Return a patch ctx for get_db whose __enter__ yields ``db``."""
    gdb = patch("app.application.finance_app_service.get_db")
    return gdb, db


# ── get_payables ────────────────────────────────────────────────────────────


class TestGetPayables:
    def _order(self) -> MagicMock:
        o = MagicMock()
        o.id = 7
        o.order_no = "PO-001"
        o.supplier = MagicMock()
        o.supplier.name = "Acme"
        o.total_amount = Decimal("1000")
        o.paid_amount = Decimal("400")
        o.status = "open"
        o.order_date = datetime(2026, 3, 1)
        o.delivery_date = datetime(2026, 3, 10)
        return o

    def test_returns_orders_with_outstanding(self) -> None:
        svc = FinanceAppService()
        db = MagicMock()
        q = MagicMock()
        q.join.return_value = q
        q.filter.return_value = q
        q.count.return_value = 1
        q.order_by.return_value = q
        q.offset.return_value = q
        q.limit.return_value = q
        q.all.return_value = [self._order()]
        db.query.return_value = q
        gdb, _ = _patch_db(db)
        with gdb as p:
            p.return_value.__enter__.return_value = db
            out = svc.get_payables()
        assert out["success"] is True
        assert out["total"] == 1
        assert out["page"] == 1
        row = out["data"][0]
        assert row["id"] == 7
        assert row["order_no"] == "PO-001"
        assert row["supplier_name"] == "Acme"
        assert row["total_amount"] == 1000.0
        assert row["paid_amount"] == 400.0
        # outstanding = total - paid
        assert row["outstanding"] == 600.0
        assert row["order_date"] == datetime(2026, 3, 1).isoformat()
        assert row["delivery_date"] == datetime(2026, 3, 10).isoformat()

    def test_applies_all_filters_and_nulls(self) -> None:
        svc = FinanceAppService()
        db = MagicMock()
        q = MagicMock()
        q.join.return_value = q
        q.filter.return_value = q
        q.count.return_value = 1
        q.order_by.return_value = q
        q.offset.return_value = q
        q.limit.return_value = q
        # order with no supplier and no paid_amount / dates -> exercise None branches
        o = MagicMock()
        o.id = 9
        o.order_no = "PO-009"
        o.supplier = None
        o.total_amount = Decimal("500")
        o.paid_amount = None
        o.status = "draft"
        o.order_date = None
        o.delivery_date = None
        q.all.return_value = [o]
        db.query.return_value = q
        gdb, _ = _patch_db(db)
        with gdb as p:
            p.return_value.__enter__.return_value = db
            out = svc.get_payables(
                start_date=datetime(2026, 1, 1),
                end_date=datetime(2026, 12, 31),
                status="draft",
                page=2,
                per_page=5,
            )
        row = out["data"][0]
        assert row["supplier_name"] is None
        # paid_amount None -> outstanding == total - 0
        assert row["outstanding"] == 500.0
        assert row["paid_amount"] is None
        assert row["order_date"] is None
        assert row["delivery_date"] is None
        assert out["page"] == 2
        assert out["per_page"] == 5
        # 1 base filter (status notin) + 3 conditional filters
        assert q.filter.call_count == 4


# ── list_transactions date-filter branches (223, 225) ────────────────────────


class TestListTransactionsDateFilters:
    def test_start_and_end_date_filters_applied(self) -> None:
        svc = FinanceAppService()
        db = MagicMock()
        q = MagicMock()
        q.filter.return_value = q
        q.count.return_value = 0
        q.order_by.return_value = q
        q.offset.return_value = q
        q.limit.return_value = q
        q.all.return_value = []
        db.query.return_value = q
        gdb, _ = _patch_db(db)
        with gdb as p:
            p.return_value.__enter__.return_value = db
            out = svc.list_transactions(
                transaction_type="receipt",
                start_date=datetime(2026, 1, 1),
                end_date=datetime(2026, 2, 1),
                status="completed",
            )
        assert out["success"] is True
        assert out["data"] == []
        assert out["total"] == 0
        # type + start + end + status -> 4 filters
        assert q.filter.call_count == 4


# ── get_transaction (245-249) ────────────────────────────────────────────────


class TestGetTransaction:
    def test_found_returns_to_dict(self) -> None:
        svc = FinanceAppService()
        db = MagicMock()
        txn = MagicMock()
        txn.to_dict.return_value = {"id": 3, "amount": 12.5}
        db.query.return_value.filter.return_value.first.return_value = txn
        gdb, _ = _patch_db(db)
        with gdb as p:
            p.return_value.__enter__.return_value = db
            out = svc.get_transaction(3)
        assert out == {"success": True, "data": {"id": 3, "amount": 12.5}}

    def test_missing_returns_failure(self) -> None:
        svc = FinanceAppService()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        gdb, _ = _patch_db(db)
        with gdb as p:
            p.return_value.__enter__.return_value = db
            out = svc.get_transaction(999)
        assert out == {"success": False, "message": "凭证不存在"}


# ── create_transaction success + neuro bridge (269-284) ──────────────────────


class TestCreateTransaction:
    def _data(self) -> dict:
        return {
            "transaction_type": "receipt",
            "amount": "150.00",
            "transaction_date": "2026-03-01T00:00:00",
            "description": "test",
        }

    def test_success_notifies_neuro_bridge(self) -> None:
        svc = FinanceAppService()
        db = MagicMock()
        gdb, _ = _patch_db(db)
        created = {}

        def _refresh(obj):
            obj.id = 42
            obj.amount = Decimal("150.00")
            obj.transaction_type = "receipt"
            obj.to_dict = lambda: {"id": 42, "amount": 150.0}
            created["txn"] = obj

        db.refresh.side_effect = _refresh
        notify = MagicMock()
        with gdb as p:
            p.return_value.__enter__.return_value = db
            with patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_transaction_changed",
                notify,
            ):
                out = svc.create_transaction(self._data())
        assert out["success"] is True
        assert out["data"] == {"id": 42, "amount": 150.0}
        db.add.assert_called_once()
        db.commit.assert_called_once()
        notify.assert_called_once()
        kwargs = notify.call_args.kwargs
        assert notify.call_args.args[0] == "created"
        assert kwargs["transaction_id"] == 42
        assert kwargs["amount"] == 150.0
        assert kwargs["txn_type"] == "receipt"

    def test_neuro_bridge_failure_is_swallowed(self) -> None:
        svc = FinanceAppService()
        db = MagicMock()
        gdb, _ = _patch_db(db)

        def _refresh(obj):
            obj.id = 1
            obj.amount = Decimal("10")
            obj.transaction_type = "payment"
            obj.to_dict = lambda: {"id": 1}

        db.refresh.side_effect = _refresh
        with gdb as p:
            p.return_value.__enter__.return_value = db
            # RuntimeError is in RECOVERABLE_ERRORS -> swallowed, still success
            with patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_transaction_changed",
                side_effect=RuntimeError("bus down"),
            ):
                out = svc.create_transaction({"transaction_type": "payment", "amount": "10"})
        assert out["success"] is True
        assert out["data"] == {"id": 1}

    def test_missing_required_key_returns_failure(self) -> None:
        svc = FinanceAppService()
        db = MagicMock()
        gdb, _ = _patch_db(db)
        with gdb as p:
            p.return_value.__enter__.return_value = db
            # KeyError (LookupError, recoverable) on data["transaction_type"]
            out = svc.create_transaction({"amount": "10"})
        assert out["success"] is False
        db.rollback.assert_called_once()


# ── update_transaction (297, 332-338) ────────────────────────────────────────


class TestUpdateTransaction:
    def test_missing_returns_failure(self) -> None:
        svc = FinanceAppService()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        gdb, _ = _patch_db(db)
        with gdb as p:
            p.return_value.__enter__.return_value = db
            out = svc.update_transaction(5, {"amount": "20"})
        assert out == {"success": False, "message": "凭证不存在"}

    def test_success_applies_updates_and_notifies(self) -> None:
        svc = FinanceAppService()
        db = MagicMock()
        txn = MagicMock()
        txn.id = 8
        txn.amount = Decimal("20")
        txn.transaction_type = "receipt"
        txn.to_dict.return_value = {"id": 8, "amount": 20.0}
        db.query.return_value.filter.return_value.first.return_value = txn
        gdb, _ = _patch_db(db)
        notify = MagicMock()
        with gdb as p:
            p.return_value.__enter__.return_value = db
            with patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_transaction_changed",
                notify,
            ):
                out = svc.update_transaction(
                    8,
                    {
                        "amount": "20",
                        "transaction_date": "2026-04-01T00:00:00",
                        "status": "completed",
                        "ignored_field": "x",  # not in updatable -> skipped
                        "currency": None,  # None -> skipped
                    },
                )
        assert out["success"] is True
        assert out["data"] == {"id": 8, "amount": 20.0}
        db.commit.assert_called_once()
        # amount coerced to Decimal
        assert txn.amount == Decimal("20")
        # transaction_date parsed to datetime
        assert txn.transaction_date == datetime(2026, 4, 1)
        assert txn.status == "completed"
        notify.assert_called_once()
        assert notify.call_args.args[0] == "updated"

    def test_db_error_rolls_back(self) -> None:
        svc = FinanceAppService()
        db = MagicMock()
        txn = MagicMock()
        txn.id = 8
        txn.amount = Decimal("20")
        txn.transaction_type = "receipt"
        db.query.return_value.filter.return_value.first.return_value = txn
        db.commit.side_effect = RuntimeError("commit failed")
        gdb, _ = _patch_db(db)
        with gdb as p:
            p.return_value.__enter__.return_value = db
            out = svc.update_transaction(8, {"status": "completed"})
        assert out["success"] is False
        assert "commit failed" in out["message"]
        db.rollback.assert_called_once()


# ── delete_transaction (347, 364-370) ────────────────────────────────────────


class TestDeleteTransaction:
    def test_missing_returns_failure(self) -> None:
        svc = FinanceAppService()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        gdb, _ = _patch_db(db)
        with gdb as p:
            p.return_value.__enter__.return_value = db
            out = svc.delete_transaction(5)
        assert out == {"success": False, "message": "凭证不存在"}

    def test_success_deletes_and_notifies(self) -> None:
        svc = FinanceAppService()
        db = MagicMock()
        txn = MagicMock()
        txn.id = 11
        txn.amount = Decimal("33")
        txn.transaction_type = "payment"
        db.query.return_value.filter.return_value.first.return_value = txn
        gdb, _ = _patch_db(db)
        notify = MagicMock()
        with gdb as p:
            p.return_value.__enter__.return_value = db
            with patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_transaction_changed",
                notify,
            ):
                out = svc.delete_transaction(11)
        assert out == {"success": True, "message": "凭证已删除"}
        db.delete.assert_called_once_with(txn)
        db.commit.assert_called_once()
        notify.assert_called_once()
        kwargs = notify.call_args.kwargs
        assert kwargs["transaction_id"] == 11
        assert kwargs["amount"] == 33.0
        assert kwargs["txn_type"] == "payment"

    def test_db_error_rolls_back(self) -> None:
        svc = FinanceAppService()
        db = MagicMock()
        txn = MagicMock()
        txn.id = 11
        txn.amount = Decimal("33")
        txn.transaction_type = "payment"
        db.query.return_value.filter.return_value.first.return_value = txn
        db.commit.side_effect = ValueError("delete boom")
        gdb, _ = _patch_db(db)
        with gdb as p:
            p.return_value.__enter__.return_value = db
            out = svc.delete_transaction(11)
        assert out["success"] is False
        assert "delete boom" in out["message"]
        db.rollback.assert_called_once()


# ── _parse_dt datetime passthrough (425-426) ─────────────────────────────────


class TestParseDt:
    def test_datetime_passthrough(self) -> None:
        dt = datetime(2026, 5, 5, 12, 0, 0)
        assert _parse_dt(dt) is dt

    def test_none_returns_none(self) -> None:
        assert _parse_dt(None) is None

    def test_iso_string_parsed(self) -> None:
        assert _parse_dt("2026-06-01T08:30:00") == datetime(2026, 6, 1, 8, 30, 0)

    def test_invalid_string_returns_none(self) -> None:
        assert _parse_dt("not-a-date") is None
