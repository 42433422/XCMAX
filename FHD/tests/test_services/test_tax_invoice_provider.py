"""Tests for app.services.tax_invoice_provider."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from app.services.tax_invoice_provider import issue_crm_invoice_for_pipeline, _now_iso


class TestNowIso:
    def test_returns_iso_string(self):
        result = _now_iso()
        assert isinstance(result, str)
        assert "T" in result


class TestIssueCrmInvoiceForPipeline:
    @patch("app.services.user_cs_crm_store.create_crm_invoice_for_pipeline")
    def test_basic_invoice(self, mock_create):
        mock_create.return_value = {"id": 42, "invoice_no": "INV-001"}
        doc = {
            "market_user_id": 123,
            "payment": {"contract_amount_cents": 50000},
            "crm_opportunity_id": 99,
            "username": "testuser",
        }
        result = issue_crm_invoice_for_pipeline(doc)
        assert result["crm_invoice_id"] == 42
        assert result["invoice_no"] == "INV-001"
        assert "invoice" in result

    @patch("app.services.user_cs_crm_store.create_crm_invoice_for_pipeline")
    def test_missing_payment(self, mock_create):
        mock_create.return_value = {"id": 1, "invoice_no": "INV-002"}
        doc = {"market_user_id": 123}
        result = issue_crm_invoice_for_pipeline(doc)
        mock_create.assert_called_once_with(123, opportunity_id=None, amount_cents=0, username="")

    @patch("app.services.user_cs_crm_store.create_crm_invoice_for_pipeline")
    def test_missing_fields_use_defaults(self, mock_create):
        mock_create.return_value = {"id": 0, "invoice_no": ""}
        doc = {}
        result = issue_crm_invoice_for_pipeline(doc)
        assert result["crm_invoice_id"] == 0
        assert result["invoice_no"] == ""

    @patch("app.services.user_cs_crm_store.create_crm_invoice_for_pipeline")
    def test_non_dict_payment(self, mock_create):
        mock_create.return_value = {"id": 1, "invoice_no": "INV-003"}
        doc = {"market_user_id": 1, "payment": "not a dict"}
        result = issue_crm_invoice_for_pipeline(doc)
        mock_create.assert_called_once_with(1, opportunity_id=None, amount_cents=0, username="")
