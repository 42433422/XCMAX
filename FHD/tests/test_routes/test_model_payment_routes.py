"""Tests for app.fastapi_routes.model_payment — route endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import ErrorCode, PaymentError
from app.fastapi_routes.model_payment import router


@pytest.fixture
def app_mp():
    """Create a FastAPI app with the model_payment router mounted."""
    _app = FastAPI()
    _app.include_router(router)

    # Register AppError handler so PaymentError returns correct status code
    from app.errors import AppError

    @_app.exception_handler(AppError)
    async def app_error_handler(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            {"success": False, "code": exc.code.value, "message": exc.message},
            status_code=exc.status_code,
        )

    return _app


@pytest.fixture
def client_mp(app_mp):
    """TestClient for model_payment routes."""
    with TestClient(app_mp, raise_server_exceptions=False, follow_redirects=False) as c:
        yield c


# ========================= GET /api/model-payment/plans ==================


class TestGetPlans:
    def test_plans_returns_200(self, client_mp):
        with patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali, \
             patch("app.fastapi_routes.model_payment.is_modstore_payment_sot", return_value=False), \
             patch("app.fastapi_routes.model_payment.is_fhd_postgres_payment_sot", return_value=False), \
             patch("app.fastapi_routes.model_payment.model_payment_backend", return_value="json"), \
             patch("app.fastapi_routes.model_payment.list_saas_plans", return_value=[]):
            mock_ali.alipay_ui_ready.return_value = False
            r = client_mp.get("/api/model-payment/plans")
            assert r.status_code == 200
            body = r.json()
            assert body["success"] is True
            assert "plans" in body["data"]
            assert "integration" in body["data"]

    def test_plans_includes_demo_plans(self, client_mp):
        with patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali, \
             patch("app.fastapi_routes.model_payment.is_modstore_payment_sot", return_value=False), \
             patch("app.fastapi_routes.model_payment.is_fhd_postgres_payment_sot", return_value=False), \
             patch("app.fastapi_routes.model_payment.model_payment_backend", return_value="json"), \
             patch("app.fastapi_routes.model_payment.list_saas_plans", return_value=[]):
            mock_ali.alipay_ui_ready.return_value = False
            r = client_mp.get("/api/model-payment/plans")
            plans = r.json()["data"]["plans"]
            ids = [p["id"] for p in plans]
            assert "demo-starter" in ids
            assert "demo-standard" in ids
            assert "demo-pro" in ids


# ========================= GET /api/model-payment/wechat-redirect ========


class TestWechatRedirect:
    def test_wechat_redirect_no_url_returns_503(self, client_mp):
        mock_proxy = MagicMock()
        mock_proxy.wechat_checkout_redirect_url.return_value = None
        with patch.dict("sys.modules", {"app.infrastructure.payment.modstore_payment_proxy": mock_proxy}):
            r = client_mp.get("/api/model-payment/wechat-redirect", params={"plan_id": "p1"})
            assert r.status_code == 503
            assert r.json()["success"] is False

    def test_wechat_redirect_with_url_returns_302(self, client_mp):
        mock_proxy = MagicMock()
        mock_proxy.wechat_checkout_redirect_url.return_value = "https://pay.example.com/checkout"
        with patch.dict("sys.modules", {"app.infrastructure.payment.modstore_payment_proxy": mock_proxy}):
            r = client_mp.get("/api/model-payment/wechat-redirect", params={"plan_id": "p1"})
            assert r.status_code == 302


# ========================= POST /api/model-payment/checkout ==============


class TestCheckout:
    def test_checkout_modstore_sot_with_plan_success(self, client_mp):
        mock_proxy = MagicMock()
        mock_proxy.proxy_checkout.return_value = {"success": True, "data": {"order_id": "x1"}}
        with patch("app.fastapi_routes.model_payment.is_modstore_payment_sot", return_value=True), \
             patch("app.fastapi_routes.model_payment.modstore_payment_hint", return_value="hint"), \
             patch.dict("sys.modules", {"app.infrastructure.payment.modstore_payment_proxy": mock_proxy}):
            r = client_mp.post("/api/model-payment/checkout", json={
                "plan_id": "demo-starter", "channel": "alipay"
            })
            assert r.status_code == 200
            assert r.json()["success"] is True

    def test_checkout_modstore_sot_no_plan_returns_409(self, client_mp):
        with patch("app.fastapi_routes.model_payment.is_modstore_payment_sot", return_value=True), \
             patch("app.fastapi_routes.model_payment.modstore_payment_hint", return_value="hint"):
            r = client_mp.post("/api/model-payment/checkout", json={})
            assert r.status_code == 409
            assert r.json()["success"] is False

    def test_checkout_modstore_sot_proxy_fails_returns_409(self, client_mp):
        mock_proxy = MagicMock()
        mock_proxy.proxy_checkout.return_value = {"success": False, "error": "proxy error"}
        with patch("app.fastapi_routes.model_payment.is_modstore_payment_sot", return_value=True), \
             patch("app.fastapi_routes.model_payment.modstore_payment_hint", return_value="hint"), \
             patch.dict("sys.modules", {"app.infrastructure.payment.modstore_payment_proxy": mock_proxy}):
            r = client_mp.post("/api/model-payment/checkout", json={"plan_id": "p1"})
            assert r.status_code == 409
            assert r.json()["data"]["proxy_error"] == "proxy error"

    def test_checkout_json_legacy_with_postgres_url_returns_409(self, client_mp):
        with patch("app.fastapi_routes.model_payment.is_modstore_payment_sot", return_value=False), \
             patch("app.fastapi_routes.model_payment.is_json_legacy_payment_sot", return_value=True), \
             patch.dict("os.environ", {"DATABASE_URL": "postgresql://user:pass@host/db"}, clear=False):
            r = client_mp.post("/api/model-payment/checkout", json={"plan_id": "demo-starter"})
            assert r.status_code == 409

    def test_checkout_invalid_channel_returns_400(self, client_mp):
        with patch("app.fastapi_routes.model_payment.is_modstore_payment_sot", return_value=False), \
             patch("app.fastapi_routes.model_payment.is_json_legacy_payment_sot", return_value=False), \
             patch.dict("os.environ", {}, clear=False):
            r = client_mp.post("/api/model-payment/checkout", json={
                "plan_id": "demo-starter", "channel": "wechat"
            })
            assert r.status_code == 400
            assert "仅支持支付宝" in r.json()["message"]

    def test_checkout_unknown_plan_raises_payment_error(self, client_mp):
        with patch("app.fastapi_routes.model_payment.is_modstore_payment_sot", return_value=False), \
             patch("app.fastapi_routes.model_payment.is_json_legacy_payment_sot", return_value=False), \
             patch("app.fastapi_routes.model_payment._plan_by_id", return_value=None), \
             patch.dict("os.environ", {}, clear=False):
            r = client_mp.post("/api/model-payment/checkout", json={"plan_id": "nonexistent"})
            assert r.status_code == 400

    def test_checkout_demo_mode_alipay_not_ready(self, client_mp):
        with patch("app.fastapi_routes.model_payment.is_modstore_payment_sot", return_value=False), \
             patch("app.fastapi_routes.model_payment.is_json_legacy_payment_sot", return_value=False), \
             patch("app.fastapi_routes.model_payment._plan_by_id", return_value={
                 "id": "demo-starter", "title": "体验档", "amount_cents": 990
             }), \
             patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali, \
             patch.dict("os.environ", {}, clear=False):
            mock_ali.alipay_ui_ready.return_value = False
            mock_ali.credentials_ready.return_value = False
            mock_ali.warn_notify_url_path_once.return_value = None
            r = client_mp.post("/api/model-payment/checkout", json={"plan_id": "demo-starter"})
            assert r.status_code == 200
            body = r.json()
            assert body["success"] is True
            assert body["data"]["status"] == "demo_pending"
            assert body["data"]["client_payload"]["demo"] is True

    def test_checkout_demo_mode_sdk_import_error(self, client_mp):
        with patch("app.fastapi_routes.model_payment.is_modstore_payment_sot", return_value=False), \
             patch("app.fastapi_routes.model_payment.is_json_legacy_payment_sot", return_value=False), \
             patch("app.fastapi_routes.model_payment._plan_by_id", return_value={
                 "id": "demo-starter", "title": "体验档", "amount_cents": 990
             }), \
             patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali, \
             patch.dict("os.environ", {}, clear=False):
            mock_ali.alipay_ui_ready.return_value = False
            mock_ali.credentials_ready.return_value = True
            mock_ali.sdk_import_error.return_value = "python-alipay-sdk not installed"
            mock_ali.warn_notify_url_path_once.return_value = None
            r = client_mp.post("/api/model-payment/checkout", json={"plan_id": "demo-starter"})
            assert r.status_code == 200
            body = r.json()
            assert body["data"]["status"] == "demo_pending"

    def test_checkout_alipay_ready_pay_success(self, client_mp):
        with patch("app.fastapi_routes.model_payment.is_modstore_payment_sot", return_value=False), \
             patch("app.fastapi_routes.model_payment.is_json_legacy_payment_sot", return_value=False), \
             patch("app.fastapi_routes.model_payment._plan_by_id", return_value={
                 "id": "demo-starter", "title": "体验档", "amount_cents": 990
             }), \
             patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali, \
             patch("app.fastapi_routes.model_payment.mp_orders") as mock_orders, \
             patch.dict("os.environ", {}, clear=False):
            mock_ali.alipay_ui_ready.return_value = True
            mock_ali.warn_notify_url_path_once.return_value = None
            mock_ali.create_pay_order.return_value = {
                "success": True,
                "type": "page",
                "redirect_url": "https://pay.alipay.com/xxx",
                "qr_code": None,
                "raw": {"trade_no": "T123"},
            }
            mock_orders.record_checkout_pending.return_value = None
            r = client_mp.post("/api/model-payment/checkout", json={"plan_id": "demo-starter"})
            assert r.status_code == 200
            body = r.json()
            assert body["success"] is True
            assert body["data"]["status"] == "pending_payment"
            assert body["data"]["redirect_url"] == "https://pay.alipay.com/xxx"

    def test_checkout_alipay_ready_pay_failure(self, client_mp):
        with patch("app.fastapi_routes.model_payment.is_modstore_payment_sot", return_value=False), \
             patch("app.fastapi_routes.model_payment.is_json_legacy_payment_sot", return_value=False), \
             patch("app.fastapi_routes.model_payment._plan_by_id", return_value={
                 "id": "demo-starter", "title": "体验档", "amount_cents": 990
             }), \
             patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali, \
             patch.dict("os.environ", {}, clear=False):
            mock_ali.alipay_ui_ready.return_value = True
            mock_ali.warn_notify_url_path_once.return_value = None
            mock_ali.create_pay_order.return_value = {
                "success": False,
                "message": "下单失败",
            }
            r = client_mp.post("/api/model-payment/checkout", json={"plan_id": "demo-starter"})
            assert r.status_code == 200
            body = r.json()
            assert body["success"] is False

    def test_checkout_alipay_ready_write_order_fails(self, client_mp):
        with patch("app.fastapi_routes.model_payment.is_modstore_payment_sot", return_value=False), \
             patch("app.fastapi_routes.model_payment.is_json_legacy_payment_sot", return_value=False), \
             patch("app.fastapi_routes.model_payment._plan_by_id", return_value={
                 "id": "demo-starter", "title": "体验档", "amount_cents": 990
             }), \
             patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali, \
             patch("app.fastapi_routes.model_payment.mp_orders") as mock_orders, \
             patch.dict("os.environ", {}, clear=False):
            mock_ali.alipay_ui_ready.return_value = True
            mock_ali.warn_notify_url_path_once.return_value = None
            mock_ali.create_pay_order.return_value = {
                "success": True,
                "type": "page",
                "redirect_url": "https://pay.alipay.com/xxx",
                "qr_code": None,
                "raw": {},
            }
            mock_orders.record_checkout_pending.side_effect = OSError("disk full")
            r = client_mp.post("/api/model-payment/checkout", json={"plan_id": "demo-starter"})
            assert r.status_code == 200
            assert r.json()["success"] is True


# ========================= POST /api/model-payment/notify/alipay =========


class TestAlipayNotify:
    def test_notify_not_local_sot_returns_410(self, client_mp):
        with patch("app.fastapi_routes.model_payment.is_local_model_payment_sot", return_value=False):
            r = client_mp.post("/api/model-payment/notify/alipay")
            assert r.status_code == 410

    def test_notify_no_signature_returns_400(self, client_mp):
        with patch("app.fastapi_routes.model_payment.is_local_model_payment_sot", return_value=True):
            r = client_mp.post("/api/model-payment/notify/alipay", data={"trade_no": "T1"})
            assert r.status_code == 400

    def test_notify_credentials_not_ready_returns_503(self, client_mp):
        with patch("app.fastapi_routes.model_payment.is_local_model_payment_sot", return_value=True), \
             patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali:
            mock_ali.credentials_ready.return_value = False
            r = client_mp.post(
                "/api/model-payment/notify/alipay",
                data={"sign": "sig123", "trade_no": "T1"},
            )
            assert r.status_code == 503

    def test_notify_verify_fails_returns_400(self, client_mp):
        with patch("app.fastapi_routes.model_payment.is_local_model_payment_sot", return_value=True), \
             patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali:
            mock_ali.credentials_ready.return_value = True
            mock_ali.verify_notify.return_value = False
            r = client_mp.post(
                "/api/model-payment/notify/alipay",
                data={"sign": "sig123", "trade_no": "T1"},
            )
            assert r.status_code == 400

    def test_notify_verify_success_returns_success(self, client_mp):
        with patch("app.fastapi_routes.model_payment.is_local_model_payment_sot", return_value=True), \
             patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali, \
             patch("app.fastapi_routes.model_payment.mp_orders") as mock_orders:
            mock_ali.credentials_ready.return_value = True
            mock_ali.verify_notify.return_value = True
            mock_orders.apply_notify_paid.return_value = ("marked_paid", {"plan_id": "p1", "amount_cents": 990, "entitlement": {"purchase_count": 1}})
            r = client_mp.post(
                "/api/model-payment/notify/alipay",
                data={
                    "sign": "sig123",
                    "trade_status": "TRADE_SUCCESS",
                    "out_trade_no": "mp-123",
                    "trade_no": "T123",
                    "total_amount": "9.90",
                },
            )
            assert r.status_code == 200
            assert r.text == "success"

    def test_notify_amount_mismatch_returns_400(self, client_mp):
        with patch("app.fastapi_routes.model_payment.is_local_model_payment_sot", return_value=True), \
             patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali, \
             patch("app.fastapi_routes.model_payment.mp_orders") as mock_orders:
            mock_ali.credentials_ready.return_value = True
            mock_ali.verify_notify.return_value = True
            mock_orders.apply_notify_paid.return_value = ("amount_mismatch", None)
            r = client_mp.post(
                "/api/model-payment/notify/alipay",
                data={
                    "sign": "sig123",
                    "trade_status": "TRADE_SUCCESS",
                    "out_trade_no": "mp-123",
                    "trade_no": "T123",
                    "total_amount": "99.00",
                },
            )
            assert r.status_code == 400

    def test_notify_unknown_order_returns_success(self, client_mp):
        with patch("app.fastapi_routes.model_payment.is_local_model_payment_sot", return_value=True), \
             patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali, \
             patch("app.fastapi_routes.model_payment.mp_orders") as mock_orders:
            mock_ali.credentials_ready.return_value = True
            mock_ali.verify_notify.return_value = True
            mock_orders.apply_notify_paid.return_value = ("unknown_order", None)
            r = client_mp.post(
                "/api/model-payment/notify/alipay",
                data={
                    "sign": "sig123",
                    "trade_status": "TRADE_SUCCESS",
                    "out_trade_no": "mp-unknown",
                    "trade_no": "T999",
                    "total_amount": "9.90",
                },
            )
            assert r.status_code == 200
            assert r.text == "success"

    def test_notify_verify_raises_infra_transient_returns_500(self, client_mp):
        with patch("app.fastapi_routes.model_payment.is_local_model_payment_sot", return_value=True), \
             patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali:
            mock_ali.credentials_ready.return_value = True
            mock_ali.verify_notify.side_effect = OSError("network error")
            r = client_mp.post(
                "/api/model-payment/notify/alipay",
                data={"sign": "sig123", "trade_no": "T1"},
            )
            assert r.status_code == 500


# ========================= GET /api/model-payment/diagnostics ============


class TestDiagnostics:
    def test_diagnostics_returns_200(self, client_mp):
        with patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali, \
             patch("app.fastapi_routes.model_payment.mp_orders") as mock_orders, \
             patch("app.fastapi_routes.model_payment.model_payment_backend", return_value="json"), \
             patch("app.fastapi_routes.model_payment.is_fhd_postgres_payment_sot", return_value=False):
            mock_ali.diagnostics_snapshot.return_value = {"alipay_ready": False}
            mock_orders.order_store_path.return_value = "/tmp/orders.json"
            r = client_mp.get("/api/model-payment/diagnostics")
            assert r.status_code == 200
            body = r.json()
            assert body["success"] is True
            assert "data" in body

    def test_diagnostics_postgres_sot_includes_order_count(self, client_mp):
        with patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali, \
             patch("app.fastapi_routes.model_payment.mp_orders") as mock_orders, \
             patch("app.fastapi_routes.model_payment.model_payment_backend", return_value="postgres"), \
             patch("app.fastapi_routes.model_payment.is_fhd_postgres_payment_sot", return_value=True):
            mock_ali.diagnostics_snapshot.return_value = {"alipay_ready": True}
            mock_orders.order_store_path.return_value = "/tmp/orders.json"
            mock_orders.count_orders.return_value = 42
            mock_orders.json_store_has_unmigrated_orders.return_value = False
            r = client_mp.get("/api/model-payment/diagnostics")
            assert r.status_code == 200
            data = r.json()["data"]
            assert data["order_count"] == 42
            assert data["db_table"] == "model_payment_orders"

    def test_diagnostics_postgres_sot_order_count_error(self, client_mp):
        with patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali, \
             patch("app.fastapi_routes.model_payment.mp_orders") as mock_orders, \
             patch("app.fastapi_routes.model_payment.model_payment_backend", return_value="postgres"), \
             patch("app.fastapi_routes.model_payment.is_fhd_postgres_payment_sot", return_value=True):
            mock_ali.diagnostics_snapshot.return_value = {"alipay_ready": True}
            mock_orders.order_store_path.return_value = "/tmp/orders.json"
            mock_orders.count_orders.side_effect = RuntimeError("db down")
            r = client_mp.get("/api/model-payment/diagnostics")
            assert r.status_code == 200
            data = r.json()["data"]
            assert "order_count_error" in data


# ========================= GET /api/model-payment/entitlements ===========


class TestEntitlements:
    def test_entitlements_modstore_sot_returns_409(self, client_mp):
        with patch("app.fastapi_routes.model_payment.is_modstore_payment_sot", return_value=True), \
             patch("app.fastapi_routes.model_payment.modstore_payment_hint", return_value="hint"):
            r = client_mp.get("/api/model-payment/entitlements")
            assert r.status_code == 409

    def test_entitlements_local_sot_returns_list(self, client_mp):
        with patch("app.fastapi_routes.model_payment.is_modstore_payment_sot", return_value=False), \
             patch("app.fastapi_routes.model_payment.mp_orders") as mock_orders, \
             patch("app.fastapi_routes.model_payment.model_payment_backend", return_value="json"):
            mock_orders.list_entitlements.return_value = [{"plan_id": "demo-starter"}]
            r = client_mp.get("/api/model-payment/entitlements")
            assert r.status_code == 200
            body = r.json()
            assert body["success"] is True
            assert len(body["data"]["entitlements"]) == 1


# ========================= GET /api/model-payment/query/{out_trade_no} ===


class TestQueryTrade:
    def test_query_trade_success(self, client_mp):
        with patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali, \
             patch("app.fastapi_routes.model_payment.mp_orders") as mock_orders:
            mock_ali.query_order.return_value = {
                "success": True, "raw": {"trade_status": "TRADE_SUCCESS"}
            }
            mock_orders.get_order.return_value = {"status": "paid"}
            r = client_mp.get("/api/model-payment/query/mp-123")
            assert r.status_code == 200
            body = r.json()
            assert body["success"] is True
            assert body["data"]["trade"]["trade_status"] == "TRADE_SUCCESS"

    def test_query_trade_failure(self, client_mp):
        with patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali, \
             patch("app.fastapi_routes.model_payment.mp_orders") as mock_orders:
            mock_ali.query_order.return_value = {
                "success": False, "message": "查询失败"
            }
            mock_orders.get_order.return_value = None
            r = client_mp.get("/api/model-payment/query/mp-123")
            assert r.status_code == 200
            body = r.json()
            assert body["success"] is False


# ========================= POST /api/model-payment/refund ================


class TestRefund:
    def test_refund_missing_out_trade_no(self, client_mp):
        r = client_mp.post("/api/model-payment/refund", json={"refund_amount": "9.90"})
        assert r.status_code == 400
        assert "out_trade_no 必填" in r.json()["message"]

    def test_refund_missing_refund_amount(self, client_mp):
        r = client_mp.post("/api/model-payment/refund", json={"out_trade_no": "mp-123"})
        assert r.status_code == 400
        assert "refund_amount 必填" in r.json()["message"]

    def test_refund_success(self, client_mp):
        with patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali, \
             patch("app.fastapi_routes.model_payment.mp_orders") as mock_orders:
            mock_ali.refund_order.return_value = {
                "success": True, "raw": {"refund_status": "REFUND_SUCCESS"}
            }
            mock_orders.update_order_status.return_value = None
            r = client_mp.post("/api/model-payment/refund", json={
                "out_trade_no": "mp-123", "refund_amount": "9.90"
            })
            assert r.status_code == 200
            body = r.json()
            assert body["success"] is True

    def test_refund_alipay_failure(self, client_mp):
        with patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali:
            mock_ali.refund_order.return_value = {
                "success": False, "message": "退款失败"
            }
            r = client_mp.post("/api/model-payment/refund", json={
                "out_trade_no": "mp-123", "refund_amount": "9.90"
            })
            assert r.status_code == 200
            assert r.json()["success"] is False

    def test_refund_write_failure_still_returns_success(self, client_mp):
        with patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali, \
             patch("app.fastapi_routes.model_payment.mp_orders") as mock_orders:
            mock_ali.refund_order.return_value = {
                "success": True, "raw": {}
            }
            mock_orders.update_order_status.side_effect = OSError("disk full")
            r = client_mp.post("/api/model-payment/refund", json={
                "out_trade_no": "mp-123", "refund_amount": "9.90"
            })
            assert r.status_code == 200
            assert r.json()["success"] is True


# ========================= POST /api/model-payment/close =================


class TestClose:
    def test_close_missing_both_ids(self, client_mp):
        r = client_mp.post("/api/model-payment/close", json={})
        assert r.status_code == 400
        assert "至少提供一个" in r.json()["message"]

    def test_close_success_with_out_trade_no(self, client_mp):
        with patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali, \
             patch("app.fastapi_routes.model_payment.mp_orders") as mock_orders:
            mock_ali.close_order.return_value = {"success": True, "raw": {}}
            mock_orders.update_order_status.return_value = None
            r = client_mp.post("/api/model-payment/close", json={"out_trade_no": "mp-123"})
            assert r.status_code == 200
            assert r.json()["success"] is True

    def test_close_success_with_trade_no_only(self, client_mp):
        with patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali:
            mock_ali.close_order.return_value = {"success": True, "raw": {}}
            r = client_mp.post("/api/model-payment/close", json={"trade_no": "T123"})
            assert r.status_code == 200
            assert r.json()["success"] is True

    def test_close_alipay_failure(self, client_mp):
        with patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali:
            mock_ali.close_order.return_value = {"success": False, "message": "关闭失败"}
            r = client_mp.post("/api/model-payment/close", json={"out_trade_no": "mp-123"})
            assert r.status_code == 200
            assert r.json()["success"] is False

    def test_close_write_failure_still_returns_success(self, client_mp):
        with patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali, \
             patch("app.fastapi_routes.model_payment.mp_orders") as mock_orders:
            mock_ali.close_order.return_value = {"success": True, "raw": {}}
            mock_orders.update_order_status.side_effect = OSError("disk full")
            r = client_mp.post("/api/model-payment/close", json={"out_trade_no": "mp-123"})
            assert r.status_code == 200
            assert r.json()["success"] is True


# ========================= GET /api/model-payment/refund/query ===========


class TestRefundQuery:
    def test_refund_query_success(self, client_mp):
        with patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali:
            mock_ali.query_refund.return_value = {
                "success": True, "raw": {"refund_status": "REFUND_SUCCESS"}
            }
            r = client_mp.get("/api/model-payment/refund/query", params={"out_trade_no": "mp-123"})
            assert r.status_code == 200
            assert r.json()["success"] is True

    def test_refund_query_failure(self, client_mp):
        with patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali:
            mock_ali.query_refund.return_value = {
                "success": False, "message": "查询失败"
            }
            r = client_mp.get("/api/model-payment/refund/query", params={"out_trade_no": "mp-123"})
            assert r.status_code == 200
            assert r.json()["success"] is False
