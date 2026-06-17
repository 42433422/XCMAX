"""Tests for app.fastapi_routes.finance_invoices_api — invoice management routes."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app() -> FastAPI:
    from app.fastapi_routes.finance_invoices_api import router

    app = FastAPI()
    app.include_router(router)
    return app


def _admin_session(request_mod=None):
    """Return a patch that makes _require_admin_session return None (admin OK)."""
    return patch(
        "app.fastapi_routes.finance_invoices_api._require_admin_session",
        return_value=None,
    )


def _no_session():
    """Return a patch that makes _require_admin_session return 401."""
    from fastapi.responses import JSONResponse

    return patch(
        "app.fastapi_routes.finance_invoices_api._require_admin_session",
        return_value=JSONResponse({"success": False, "message": "请先登录"}, status_code=401),
    )


def _forbidden_session():
    """Return a patch that makes _require_admin_session return 403."""
    from fastapi.responses import JSONResponse

    return patch(
        "app.fastapi_routes.finance_invoices_api._require_admin_session",
        return_value=JSONResponse(
            {"success": False, "message": "需要管理员账号登录后访问"}, status_code=403
        ),
    )


# ---------------------------------------------------------------------------
# finance_tax_channel
# ---------------------------------------------------------------------------


class TestFinanceTaxChannel:
    def test_returns_stub_by_default(self):
        app = _make_app()
        client = TestClient(app)
        with _admin_session():
            resp = client.get("/api/finance/invoices/tax-channel")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["self_hosted"] is True
        assert data["external_erp"] is False

    def test_baiwang_configured_when_env_set(self):
        app = _make_app()
        client = TestClient(app)
        with _admin_session(), patch.dict(os.environ, {"TAX_INVOICE_PROVIDER": "baiwang"}):
            resp = client.get("/api/finance/invoices/tax-channel")
        data = resp.json()
        assert data["baiwang_configured"] is True
        assert data["provider"] == "baiwang"

    def test_unknown_provider_echoed(self):
        app = _make_app()
        client = TestClient(app)
        with _admin_session(), patch.dict(os.environ, {"TAX_INVOICE_PROVIDER": "custom"}):
            resp = client.get("/api/finance/invoices/tax-channel")
        data = resp.json()
        assert data["provider"] == "custom"
        assert data["label"] == "custom"

    def test_unauthenticated_returns_401(self):
        app = _make_app()
        client = TestClient(app)
        with _no_session():
            resp = client.get("/api/finance/invoices/tax-channel")
        assert resp.status_code == 401

    def test_forbidden_returns_403(self):
        app = _make_app()
        client = TestClient(app)
        with _forbidden_session():
            resp = client.get("/api/finance/invoices/tax-channel")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# finance_crm_invoices_list
# ---------------------------------------------------------------------------


class TestFinanceCrmInvoicesList:
    def test_list_success(self):
        app = _make_app()
        client = TestClient(app)
        with (
            _admin_session(),
            patch(
                "app.fastapi_routes.finance_invoices_api.list_crm_invoices",
                create=True,
            ) as mock_list,
        ):
            # We need to patch the lazy import inside the route
            with patch(
                "app.services.user_cs_crm_store.list_crm_invoices",
                return_value={"invoices": [], "total": 0},
            ):
                resp = client.get("/api/finance/invoices/crm")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["finance_self_hosted"] is True

    def test_unauthenticated(self):
        app = _make_app()
        client = TestClient(app)
        with _no_session():
            resp = client.get("/api/finance/invoices/crm")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# finance_crm_invoice_detail
# ---------------------------------------------------------------------------


class TestFinanceCrmInvoiceDetail:
    def test_detail_not_found(self):
        app = _make_app()
        client = TestClient(app)
        with (
            _admin_session(),
            patch(
                "app.services.user_cs_crm_store.get_crm_invoice_by_id",
                return_value=None,
            ),
        ):
            resp = client.get("/api/finance/invoices/crm/999")
        assert resp.status_code == 404

    def test_detail_found(self):
        app = _make_app()
        client = TestClient(app)
        with (
            _admin_session(),
            patch(
                "app.services.user_cs_crm_store.get_crm_invoice_by_id",
                return_value={"id": 1, "amount": 100},
            ),
        ):
            resp = client.get("/api/finance/invoices/crm/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["invoice"]["id"] == 1


# ---------------------------------------------------------------------------
# finance_crm_invoice_issue
# ---------------------------------------------------------------------------


class TestFinanceCrmInvoiceIssue:
    def test_issue_no_ids_returns_400(self):
        app = _make_app()
        client = TestClient(app)
        with _admin_session():
            resp = client.post(
                "/api/finance/invoices/crm/issue",
                json={"username": "test"},
            )
        assert resp.status_code == 400

    def test_issue_with_market_user_id(self):
        app = _make_app()
        client = TestClient(app)
        pipeline_doc = {
            "crm_opportunity_id": 10,
            "invoice": {"number": "INV-001"},
        }
        with (
            _admin_session(),
            patch(
                "app.services.user_cs_pipeline.load_pipeline",
                return_value={"crm_opportunity_id": 10},
            ) as mock_load,
            patch(
                "app.services.tax_invoice_provider.issue_crm_invoice_for_pipeline",
                return_value=pipeline_doc,
            ) as mock_issue,
            patch(
                "app.services.user_cs_pipeline.save_pipeline",
                return_value=pipeline_doc,
            ) as mock_save,
        ):
            resp = client.post(
                "/api/finance/invoices/crm/issue",
                json={"market_user_id": 42, "username": "test"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_issue_no_crm_opportunity_returns_400(self):
        app = _make_app()
        client = TestClient(app)
        with (
            _admin_session(),
            patch(
                "app.services.user_cs_pipeline.load_pipeline",
                return_value={},
            ),
            patch(
                "app.services.user_cs_crm_store.get_opportunity_by_market_user",
                return_value=None,
            ),
        ):
            resp = client.post(
                "/api/finance/invoices/crm/issue",
                json={"market_user_id": 42, "username": "test"},
            )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# finance_crm_invoice_archive
# ---------------------------------------------------------------------------


class TestFinanceCrmInvoiceArchive:
    def test_archive_not_found(self):
        app = _make_app()
        client = TestClient(app)
        with (
            _admin_session(),
            patch(
                "app.services.user_cs_crm_store.get_crm_invoice_by_id",
                return_value=None,
            ),
        ):
            resp = client.post("/api/finance/invoices/crm/999/archive")
        assert resp.status_code == 404

    def test_archive_success(self):
        app = _make_app()
        client = TestClient(app)
        inv = {"id": 1, "market_user_id": 42, "amount": 500}
        with (
            _admin_session(),
            patch(
                "app.services.user_cs_crm_store.get_crm_invoice_by_id",
                return_value=inv,
            ),
            patch(
                "app.services.finance_unified_archive.archive_from_crm_invoice",
                return_value={"archive_id": "A1"},
            ),
        ):
            resp = client.post("/api/finance/invoices/crm/1/archive")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["archive"]["archive_id"] == "A1"


# ---------------------------------------------------------------------------
# finance_market_invoices_list
# ---------------------------------------------------------------------------


class TestFinanceMarketInvoicesList:
    def test_market_list_success(self):
        app = _make_app()
        client = TestClient(app)
        mock_proxy = AsyncMock(return_value={"success": True, "data": []})
        with (
            _admin_session(),
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                mock_proxy,
                create=True,
            ),
        ):
            resp = client.get("/api/finance/invoices/market")
        assert resp.status_code == 200

    def test_market_list_with_status(self):
        app = _make_app()
        client = TestClient(app)
        mock_proxy = AsyncMock(return_value={"success": True, "data": []})
        with (
            _admin_session(),
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                mock_proxy,
                create=True,
            ),
        ):
            resp = client.get("/api/finance/invoices/market?status=paid")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# finance_market_invoice_review
# ---------------------------------------------------------------------------


class TestFinanceMarketInvoiceReview:
    def test_review_issue(self):
        app = _make_app()
        client = TestClient(app)
        mock_proxy = AsyncMock(return_value={"success": True})
        with (
            _admin_session(),
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                mock_proxy,
                create=True,
            ),
        ):
            resp = client.patch(
                "/api/finance/invoices/market/5",
                json={"action": "issue", "pdf_url": "https://example.com/a.pdf"},
            )
        assert resp.status_code == 200

    def test_review_reject(self):
        app = _make_app()
        client = TestClient(app)
        mock_proxy = AsyncMock(return_value={"success": True})
        with (
            _admin_session(),
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                mock_proxy,
                create=True,
            ),
        ):
            resp = client.patch(
                "/api/finance/invoices/market/5",
                json={"action": "reject", "reject_reason": "invalid"},
            )
        assert resp.status_code == 200
