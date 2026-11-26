"""Order-owned model payment operations and receipts."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import ErrorCode, PaymentError
from app.fastapi_routes.model_payment import router
from tests.test_routes.test_model_payment_routes import (
    app_mp as app_mp,
)
from tests.test_routes.test_model_payment_routes import (
    client_mp as client_mp,
)


@pytest.fixture
def owned_order_business_branch():
    # Provider result contracts only; real object/RBAC rejection is tested separately.
    with patch(
        "app.fastapi_routes.model_payment.owned_payment_order",
        return_value={"status": "paid", "trade_no": "T123"},
    ):
        yield


# ========================= GET /api/model-payment/query/{out_trade_no} ===


@pytest.mark.usefixtures("owned_order_business_branch")
class TestQueryTrade:
    def test_query_trade_success(self, client_mp):
        with (
            patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali,
            patch("app.fastapi_routes.model_payment.mp_orders") as mock_orders,
        ):
            mock_ali.query_order.return_value = {
                "success": True,
                "raw": {"trade_status": "TRADE_SUCCESS"},
            }
            mock_orders.get_order.return_value = {"status": "paid"}
            r = client_mp.get("/api/model-payment/query/mp-123")
            assert r.status_code == 200
            body = r.json()
            assert body["success"] is True
            assert body["data"]["trade"]["trade_status"] == "TRADE_SUCCESS"

    def test_query_trade_identity_conflict_returns_409(self, client_mp):
        with (
            patch("app.fastapi_routes.model_payment.mp_ali") as provider,
            patch(
                "app.fastapi_routes.model_payment.owned_payment_order",
                return_value={
                    "out_trade_no": "mp-123",
                    "trade_no": "T123",
                    "amount_cents": 990,
                    "status": "paid",
                },
            ),
        ):
            provider.query_order.return_value = {
                "success": True,
                "raw": {
                    "out_trade_no": "mp-123",
                    "trade_no": "T999",
                    "trade_status": "TRADE_SUCCESS",
                    "total_amount": "9.90",
                },
            }
            response = client_mp.get("/api/model-payment/query/mp-123")
            assert response.status_code == 409
            assert response.json()["requires_reconciliation"] is True

    def test_query_trade_same_identity_and_amount_certifies_only_gateway(self, client_mp):
        with (
            patch("app.fastapi_routes.model_payment.mp_ali") as provider,
            patch(
                "app.fastapi_routes.model_payment.owned_payment_order",
                return_value={
                    "out_trade_no": "mp-123",
                    "trade_no": "T123",
                    "amount_cents": 990,
                    "status": "paid",
                },
            ),
        ):
            provider.query_order.return_value = {
                "success": True,
                "raw": {
                    "out_trade_no": "mp-123",
                    "trade_no": "T123",
                    "trade_status": "TRADE_SUCCESS",
                    "total_amount": "9.90",
                },
            }
            response = client_mp.get("/api/model-payment/query/mp-123")
            assert response.status_code == 200
            assert response.json()["gateway_payment_reconciled"] is True
            assert response.json()["bank_settlement_verified"] is False

    def test_query_trade_failure(self, client_mp):
        with (
            patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali,
            patch("app.fastapi_routes.model_payment.mp_orders") as mock_orders,
        ):
            mock_ali.query_order.return_value = {"success": False, "message": "查询失败"}
            mock_orders.get_order.return_value = None
            r = client_mp.get("/api/model-payment/query/mp-123")
            assert r.status_code == 200
            body = r.json()
            assert body["success"] is False


# ========================= POST /api/model-payment/refund ================


@pytest.mark.usefixtures("owned_order_business_branch")
class TestRefund:
    def test_refund_missing_out_trade_no(self, client_mp):
        r = client_mp.post("/api/model-payment/refund", json={"refund_amount": "9.90"})
        assert r.status_code == 400

    def test_refund_missing_refund_amount(self, client_mp):
        r = client_mp.post("/api/model-payment/refund", json={"out_trade_no": "mp-123"})
        assert r.status_code == 400

    @pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "0", "1.001"])
    def test_refund_invalid_amount_does_not_call_provider(self, client_mp, value):
        with patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali:
            r = client_mp.post(
                "/api/model-payment/refund",
                json={"out_trade_no": "mp-123", "refund_amount": value},
            )
        assert r.status_code == 400
        mock_ali.refund_order.assert_not_called()

    def test_provider_success_returns_pending_not_refunded(self, client_mp):
        with (
            patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali,
            patch("app.fastapi_routes.model_payment.mp_orders") as mock_orders,
        ):
            mock_orders.reserve_refund_attempt.return_value = (
                "refund_reserved",
                {"state": "pending_provider_confirmation"},
            )
            mock_orders.observe_refund_provider_result.return_value = True
            mock_ali.refund_order.return_value = {
                "success": True,
                "raw": {"refund_status": "REFUND_SUCCESS"},
            }
            r = client_mp.post(
                "/api/model-payment/refund",
                json={
                    "out_trade_no": "mp-123",
                    "refund_amount": "9.90",
                    "out_request_no": "original-refund-id",
                },
            )
            assert r.status_code == 202
            assert r.json()["success"] is False
            assert r.json()["accepted"] is True
            assert r.json()["requires_reconciliation"] is True
            mock_orders.reserve_refund_attempt.assert_called_once_with(
                out_trade_no="mp-123",
                out_request_no="original-refund-id",
                amount_cents=990,
            )
            mock_ali.refund_order.assert_called_once()
            assert mock_ali.refund_order.call_args.kwargs["refund_amount"] == "9.90"
            mock_orders.confirm_refund_from_provider_query.assert_not_called()

    def test_refund_replay_does_not_repeat_gateway_call(self, client_mp):
        with (
            patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali,
            patch("app.fastapi_routes.model_payment.mp_orders") as mock_orders,
        ):
            mock_orders.reserve_refund_attempt.return_value = (
                "refund_request_replay",
                {"state": "provider_reported_success"},
            )
            r = client_mp.post(
                "/api/model-payment/refund",
                json={"out_trade_no": "mp-123", "refund_amount": "9.90"},
            )
            assert r.status_code == 409
            mock_ali.refund_order.assert_not_called()

    def test_refund_provider_failure_keeps_original_pending_claim(self, client_mp):
        with (
            patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali,
            patch("app.fastapi_routes.model_payment.mp_orders") as mock_orders,
        ):
            mock_orders.reserve_refund_attempt.return_value = ("refund_reserved", {})
            mock_orders.observe_refund_provider_result.return_value = True
            mock_ali.refund_order.return_value = {"success": False, "message": "渠道未知"}
            r = client_mp.post(
                "/api/model-payment/refund",
                json={"out_trade_no": "mp-123", "refund_amount": "9.90"},
            )
            assert r.status_code == 503
            assert r.json()["requires_reconciliation"] is True

    def test_refund_receipt_write_failure_requires_manual_reconciliation(self, client_mp):
        with (
            patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali,
            patch("app.fastapi_routes.model_payment.mp_orders") as mock_orders,
        ):
            mock_orders.reserve_refund_attempt.return_value = ("refund_reserved", {})
            mock_orders.observe_refund_provider_result.side_effect = OSError("disk full")
            mock_ali.refund_order.return_value = {"success": True, "raw": {}}
            r = client_mp.post(
                "/api/model-payment/refund",
                json={"out_trade_no": "mp-123", "refund_amount": "9.90"},
            )
            assert r.status_code == 503
            assert r.json()["success"] is False
            assert r.json()["requires_reconciliation"] is True


# ========================= POST /api/model-payment/close =================


@pytest.mark.usefixtures("owned_order_business_branch")
class TestClose:
    def test_close_missing_both_ids(self, client_mp):
        r = client_mp.post("/api/model-payment/close", json={})
        assert r.status_code == 400
        assert "out_trade_no 必填" in r.json()["message"]

    def test_close_success_with_out_trade_no(self, client_mp):
        with (
            patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali,
            patch("app.fastapi_routes.model_payment.mp_orders") as mock_orders,
        ):
            mock_ali.close_order.return_value = {"success": True, "raw": {}}
            mock_orders.update_order_status.return_value = {"status": "closed"}
            r = client_mp.post("/api/model-payment/close", json={"out_trade_no": "mp-123"})
            assert r.status_code == 200
            assert r.json()["success"] is True

    def test_close_rejects_trade_no_only(self, client_mp):
        with patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali:
            mock_ali.close_order.return_value = {"success": True, "raw": {}}
            r = client_mp.post("/api/model-payment/close", json={"trade_no": "T123"})
            assert r.status_code == 400
            assert r.json()["success"] is False
            mock_ali.close_order.assert_not_called()

    def test_close_alipay_failure(self, client_mp):
        with patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali:
            mock_ali.close_order.return_value = {"success": False, "message": "关闭失败"}
            r = client_mp.post("/api/model-payment/close", json={"out_trade_no": "mp-123"})
            assert r.status_code == 200
            assert r.json()["success"] is False

    def test_close_write_failure_requires_reconciliation(self, client_mp):
        with (
            patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali,
            patch("app.fastapi_routes.model_payment.mp_orders") as mock_orders,
        ):
            mock_ali.close_order.return_value = {"success": True, "raw": {}}
            mock_orders.update_order_status.side_effect = OSError("disk full")
            r = client_mp.post("/api/model-payment/close", json={"out_trade_no": "mp-123"})
            assert r.status_code == 503
            assert r.json()["success"] is False
            assert r.json()["requires_reconciliation"] is True


# ========================= GET /api/model-payment/refund/query ===========


@pytest.mark.usefixtures("owned_order_business_branch")
class TestRefundQuery:
    def test_refund_query_confirms_only_independent_provider_amount_and_identity(self, client_mp):
        with (
            patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali,
            patch("app.fastapi_routes.model_payment.mp_orders") as mock_orders,
        ):
            mock_ali.query_refund.return_value = {
                "success": True,
                "raw": {
                    "refund_status": "REFUND_SUCCESS",
                    "refund_amount": "9.90",
                    "out_trade_no": "mp-123",
                    "out_request_no": "original-refund-id",
                },
            }
            mock_orders.confirm_refund_from_provider_query.return_value = (
                "refund_confirmed",
                {"state": "confirmed"},
            )
            r = client_mp.get(
                "/api/model-payment/refund/query",
                params={"out_trade_no": "mp-123", "out_request_no": "original-refund-id"},
            )
            assert r.status_code == 200
            assert r.json()["gateway_refund_confirmed"] is True
            assert r.json()["bank_settlement_verified"] is False
            mock_orders.confirm_refund_from_provider_query.assert_called_once_with(
                out_trade_no="mp-123",
                out_request_no="original-refund-id",
                amount_cents=990,
            )

    @pytest.mark.parametrize(
        "raw",
        [
            {},
            {"refund_status": "REFUND_SUCCESS", "refund_amount": "9.91"},
            {"refund_status": "REFUND_SUCCESS", "refund_amount": "9.90", "out_trade_no": "other"},
            {"refund_status": "WAITING", "refund_amount": "9.90"},
        ],
    )
    def test_refund_query_rejects_unverified_or_conflicting_result(self, client_mp, raw):
        with (
            patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali,
            patch("app.fastapi_routes.model_payment.mp_orders") as mock_orders,
        ):
            mock_ali.query_refund.return_value = {"success": True, "raw": raw}
            mock_orders.confirm_refund_from_provider_query.return_value = (
                "refund_amount_mismatch",
                {},
            )
            r = client_mp.get("/api/model-payment/refund/query", params={"out_trade_no": "mp-123"})
            assert r.status_code == 409
            if raw.get("refund_amount") == "9.91" and raw.get("out_trade_no") != "other":
                mock_orders.confirm_refund_from_provider_query.assert_called_once_with(
                    out_trade_no="mp-123", out_request_no="mp-123", amount_cents=991
                )
            else:
                mock_orders.confirm_refund_from_provider_query.assert_not_called()

    def test_refund_query_failure(self, client_mp):
        with patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali:
            mock_ali.query_refund.return_value = {
                "success": False,
                "message": "查询失败",
            }
            r = client_mp.get("/api/model-payment/refund/query", params={"out_trade_no": "mp-123"})
            assert r.status_code == 503
            assert r.json()["requires_reconciliation"] is True
