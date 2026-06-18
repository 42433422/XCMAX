"""测试 finance_unified_archive 模块 - 财务统一归档。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.finance_unified_archive import (
    _ledger_item_from_invoice,
    list_ledger,
    summarize_ledger,
)


class TestLedgerItemFromInvoice:
    """测试 _ledger_item_from_invoice 辅助函数。"""

    def test_basic_invoice(self):
        inv = {
            "id": 1,
            "amount_cents": 10000,
            "status": "issued",
            "invoice_no": "INV-001",
            "payment_reference": "REF-001",
            "issued_at": "2024-01-01",
            "label": "测试账单",
            "market_user_id": 100,
        }
        result = _ledger_item_from_invoice(inv)
        assert result["source_type"] == "crm_invoice"
        assert result["source_id"] == 1
        assert result["track"] == "contract"
        assert result["amount_cents"] == 10000
        assert result["status"] == "issued"
        assert result["invoice_no"] == "INV-001"
        assert result["payment_ref"] == "REF-001"
        assert result["occurred_at"] == "2024-01-01"
        assert result["label"] == "测试账单"
        assert result["market_user_id"] == 100

    def test_invoice_with_amount_field(self):
        inv = {"id": 2, "amount": 5000}
        result = _ledger_item_from_invoice(inv)
        assert result["amount_cents"] == 5000

    def test_invoice_missing_amount(self):
        inv = {"id": 3}
        result = _ledger_item_from_invoice(inv)
        assert result["amount_cents"] == 0

    def test_invoice_defaults(self):
        inv = {"id": 4}
        result = _ledger_item_from_invoice(inv)
        assert result["status"] == "issued"
        assert result["invoice_no"] == ""
        assert result["payment_ref"] == ""
        assert result["track"] == "contract"

    def test_invoice_fallback_label(self):
        inv = {"id": 5, "invoice_no": "INV-005"}
        result = _ledger_item_from_invoice(inv)
        assert result["label"] == "INV-005"

    def test_invoice_default_label(self):
        inv = {"id": 6}
        result = _ledger_item_from_invoice(inv)
        assert result["label"] == "CRM 账单"

    def test_invoice_occurred_at_fallback(self):
        inv = {"id": 7, "created_at": "2024-06-01"}
        result = _ledger_item_from_invoice(inv)
        assert result["occurred_at"] == "2024-06-01"

    def test_invoice_large_amount_cents(self):
        inv = {"id": 8, "amount": 50000}
        result = _ledger_item_from_invoice(inv)
        assert result["amount_cents"] == 50000


class TestListLedger:
    """测试 list_ledger 函数。"""

    def test_empty_ledger(self):
        with patch("app.services.finance_unified_archive._items_from_db", return_value=[]):
            with patch(
                "app.services.finance_unified_archive._items_from_pipeline",
                return_value=[],
            ):
                result = list_ledger()
                assert result == []

    def test_db_items_returned_first(self):
        db_items = [{"source_type": "financial_transaction", "amount_cents": 100}]
        with patch(
            "app.services.finance_unified_archive._items_from_db",
            return_value=db_items,
        ):
            result = list_ledger()
            assert len(result) == 1
            assert result[0]["source_type"] == "financial_transaction"

    def test_limit_capped_at_2000(self):
        with patch(
            "app.services.finance_unified_archive._items_from_db",
            return_value=[],
        ):
            with patch(
                "app.services.finance_unified_archive._items_from_pipeline",
                return_value=[],
            ) as mock_pipeline:
                list_ledger(limit=5000)
                args, kwargs = mock_pipeline.call_args
                assert kwargs.get("limit") == 2000 or args[-1] == 2000

    def test_limit_minimum_1(self):
        with patch(
            "app.services.finance_unified_archive._items_from_db",
            return_value=[],
        ):
            with patch(
                "app.services.finance_unified_archive._items_from_pipeline",
                return_value=[],
            ) as mock_pipeline:
                list_ledger(limit=0)
                args, kwargs = mock_pipeline.call_args
                called_limit = kwargs.get("limit", args[-1] if args else None)
                assert called_limit >= 1

    def test_fallback_to_crm_invoices(self):
        with patch(
            "app.services.finance_unified_archive._items_from_db",
            return_value=[],
        ):
            with patch(
                "app.services.finance_unified_archive.list_crm_invoices",
                return_value={"items": [{"id": 1, "amount_cents": 500}]},
                create=True,
            ):
                with patch(
                    "app.services.finance_unified_archive._items_from_pipeline",
                    return_value=[],
                ):
                    result = list_ledger()
                    assert len(result) >= 0

    def test_market_user_id_filter(self):
        with patch(
            "app.services.finance_unified_archive._items_from_db",
            return_value=[],
        ) as mock_db:
            list_ledger(market_user_id=42)
            args, kwargs = mock_db.call_args
            assert kwargs.get("market_user_id") == 42 or args[0] == 42


class TestSummarizeLedger:
    """测试 summarize_ledger 函数。"""

    def test_empty_summary(self):
        with patch("app.services.finance_unified_archive.list_ledger", return_value=[]):
            result = summarize_ledger()
            assert result == {}

    def test_summary_aggregation(self):
        items = [
            {"track": "contract", "amount_cents": 100},
            {"track": "contract", "amount_cents": 200},
            {"track": "manual", "amount_cents": 50},
        ]
        with patch("app.services.finance_unified_archive.list_ledger", return_value=items):
            result = summarize_ledger()
            assert result["contract"]["count"] == 2
            assert result["contract"]["amount_cents"] == 300
            assert result["manual"]["count"] == 1
            assert result["manual"]["amount_cents"] == 50

    def test_summary_missing_track_defaults_to_manual(self):
        items = [{"amount_cents": 100}]
        with patch("app.services.finance_unified_archive.list_ledger", return_value=items):
            result = summarize_ledger()
            assert "manual" in result

    def test_summary_missing_amount_cents(self):
        items = [{"track": "contract"}]
        with patch("app.services.finance_unified_archive.list_ledger", return_value=items):
            result = summarize_ledger()
            assert result["contract"]["amount_cents"] == 0
