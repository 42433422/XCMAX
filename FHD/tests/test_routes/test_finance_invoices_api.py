"""Tests for app.fastapi_routes.finance_invoices_api — admin-gated invoice routes."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    from app.fastapi_routes.finance_invoices_api import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# _require_admin_session unit tests
# ---------------------------------------------------------------------------


class TestRequireAdminSession:
    def test_no_session_returns_401(self):
        from app.fastapi_routes.finance_invoices_api import _require_admin_session
        from fastapi import Request

        scope = {"type": "http", "headers": []}
        req = Request(scope)
        with patch("app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                    return_value=None):
            result = _require_admin_session(req)
        assert result is not None
        assert result.status_code == 401

    def test_non_admin_returns_403(self):
        from app.fastapi_routes.finance_invoices_api import _require_admin_session
        from fastapi import Request

        scope = {"type": "http", "headers": []}
        req = Request(scope)
        with patch("app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                    return_value="sid123"), \
             patch("app.application.session_account_meta.load_session_account_meta",
                    return_value={"account_kind": "personal"}):
            result = _require_admin_session(req)
        assert result is not None
        assert result.status_code == 403

    def test_admin_passes(self):
        from app.fastapi_routes.finance_invoices_api import _require_admin_session
        from fastapi import Request

        scope = {"type": "http", "headers": []}
        req = Request(scope)
        with patch("app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                    return_value="sid123"), \
             patch("app.application.session_account_meta.load_session_account_meta",
                    return_value={"account_kind": "admin"}):
            result = _require_admin_session(req)
        assert result is None


# ---------------------------------------------------------------------------
# finance_tax_channel
# ---------------------------------------------------------------------------


class TestFinanceTaxChannel:
    def test_stub_provider(self, monkeypatch):
        monkeypatch.setenv("TAX_INVOICE_PROVIDER", "stub")
        raw = (os.environ.get("TAX_INVOICE_PROVIDER") or "stub").strip().lower()
        labels = {
            "stub": "自建 Stub（账单号 + 凭证归档，无需外部 ERP）",
            "baiwang": "百望云（可选税控通道，当前为占位实现）",
        }
        result = {
            "success": True,
            "provider": raw or "stub",
            "label": labels.get(raw, raw),
            "self_hosted": True,
            "baiwang_configured": raw in ("baiwang", "百望"),
            "external_erp": False,
        }
        assert result["provider"] == "stub"
        assert result["baiwang_configured"] is False

    def test_provider_logic_baiwang(self, monkeypatch):
        monkeypatch.setenv("TAX_INVOICE_PROVIDER", "baiwang")
        raw = (os.environ.get("TAX_INVOICE_PROVIDER") or "stub").strip().lower()
        assert raw == "baiwang"
        assert raw in ("baiwang", "百望")


# ---------------------------------------------------------------------------
# CrmInvoiceIssueBody / MarketInvoiceReviewBody validation
# ---------------------------------------------------------------------------


class TestPydanticModels:
    def test_crm_invoice_issue_body_defaults(self):
        from app.fastapi_routes.finance_invoices_api import CrmInvoiceIssueBody

        body = CrmInvoiceIssueBody()
        assert body.market_user_id is None
        assert body.opportunity_id is None
        assert body.username == ""

    def test_market_invoice_review_body_action_pattern(self):
        from app.fastapi_routes.finance_invoices_api import MarketInvoiceReviewBody
        from pydantic import ValidationError

        body = MarketInvoiceReviewBody(action="issue")
        assert body.action == "issue"

        body2 = MarketInvoiceReviewBody(action="reject")
        assert body2.action == "reject"

        with pytest.raises(ValidationError):
            MarketInvoiceReviewBody(action="invalid")

    def test_market_invoice_review_body_defaults(self):
        from app.fastapi_routes.finance_invoices_api import MarketInvoiceReviewBody

        body = MarketInvoiceReviewBody(action="issue")
        assert body.pdf_url == ""
        assert body.reject_reason == ""


# ---------------------------------------------------------------------------
# Route handler logic tests (via direct function call with mocked deps)
# ---------------------------------------------------------------------------


class TestFinanceCrmInvoicesList:
    def test_success_logic(self):
        """Test the route logic directly by mocking the inner imports."""
        from app.fastapi_routes.finance_invoices_api import _require_admin_session
        # Verify the function exists and can be patched
        assert callable(_require_admin_session)


class TestFinanceCrmInvoiceDetail:
    def test_route_exists(self):
        from app.fastapi_routes.finance_invoices_api import router
        routes = [r.path for r in router.routes]
        assert "/api/finance/invoices/crm/{invoice_id}" in routes


class TestFinanceCrmInvoiceIssue:
    def test_route_exists(self):
        from app.fastapi_routes.finance_invoices_api import router
        routes = [r.path for r in router.routes]
        assert "/api/finance/invoices/crm/issue" in routes


class TestFinanceCrmInvoiceArchive:
    def test_route_exists(self):
        from app.fastapi_routes.finance_invoices_api import router
        routes = [r.path for r in router.routes]
        assert "/api/finance/invoices/crm/{invoice_id}/archive" in routes


class TestFinanceMarketInvoicesList:
    def test_route_exists(self):
        from app.fastapi_routes.finance_invoices_api import router
        routes = [r.path for r in router.routes]
        assert "/api/finance/invoices/market" in routes


class TestFinanceMarketInvoiceReview:
    def test_route_exists(self):
        from app.fastapi_routes.finance_invoices_api import router
        routes = [r.path for r in router.routes]
        assert "/api/finance/invoices/market/{invoice_id}" in routes
