"""Tests for app.services.tax_invoice_provider."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.tax_invoice_provider import (
    _now_iso,
    issue_crm_invoice_for_pipeline,
)


class TestNowIso:
    """Tests for _now_iso."""

    def test_returns_iso_string(self) -> None:
        result = _now_iso()
        assert isinstance(result, str)
        assert "T" in result  # ISO format contains T

    def test_returns_utc(self) -> None:
        result = _now_iso()
        # Should contain +00:00 or Z for UTC
        assert "+00:00" in result or result.endswith("Z")


class TestIssueCrmInvoiceForPipeline:
    """Tests for issue_crm_invoice_for_pipeline."""

    def test_basic_invoice(self) -> None:
        mock_create = MagicMock(return_value={"id": 42, "invoice_no": "INV-001"})
        with patch("app.services.user_cs_crm_store.create_crm_invoice_for_pipeline", mock_create):
            doc = {
                "market_user_id": "100",
                "payment": {"contract_amount_cents": 50000},
                "crm_opportunity_id": "200",
                "username": "testuser",
            }
            result = issue_crm_invoice_for_pipeline(doc)
            assert result["invoice"]["id"] == 42
            assert result["crm_invoice_id"] == 42
            assert result["invoice_no"] == "INV-001"

    def test_missing_fields_use_defaults(self) -> None:
        mock_create = MagicMock(return_value={"id": 1, "invoice_no": "INV-002"})
        with patch("app.services.user_cs_crm_store.create_crm_invoice_for_pipeline", mock_create):
            doc = {}
            result = issue_crm_invoice_for_pipeline(doc)
            mock_create.assert_called_once_with(
                0,  # market_user_id defaults to 0
                opportunity_id=None,
                amount_cents=0,
                username="",
            )

    def test_payment_not_dict(self) -> None:
        mock_create = MagicMock(return_value={"id": 1, "invoice_no": "INV-003"})
        with patch("app.services.user_cs_crm_store.create_crm_invoice_for_pipeline", mock_create):
            doc = {"market_user_id": "50", "payment": "not a dict"}
            result = issue_crm_invoice_for_pipeline(doc)
            mock_create.assert_called_once_with(
                50,
                opportunity_id=None,
                amount_cents=0,
                username="",
            )

    def test_crm_opportunity_id_zero_becomes_none(self) -> None:
        mock_create = MagicMock(return_value={"id": 1, "invoice_no": "INV-004"})
        with patch("app.services.user_cs_crm_store.create_crm_invoice_for_pipeline", mock_create):
            doc = {"crm_opportunity_id": "0"}
            result = issue_crm_invoice_for_pipeline(doc)
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args
            assert call_kwargs[1]["opportunity_id"] is None

    def test_does_not_mutate_original(self) -> None:
        mock_create = MagicMock(return_value={"id": 1, "invoice_no": "INV-005"})
        with patch("app.services.user_cs_crm_store.create_crm_invoice_for_pipeline", mock_create):
            doc = {"market_user_id": "10"}
            original_keys = set(doc.keys())
            result = issue_crm_invoice_for_pipeline(doc)
            # The function does dict(doc) so original is preserved
            assert set(doc.keys()) == original_keys
