"""Tests for the MODstore order event webhook route (order_event_webhook)."""

from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.order_event_webhook import router

_APP = FastAPI()
_APP.include_router(router)


def _client() -> TestClient:
    return TestClient(_APP)


def _envelope() -> dict:
    return {
        "id": "payment.paid:MOD123",
        "type": "payment.paid",
        "version": 1,
        "source": "modstore-python",
        "aggregate_id": "MOD123",
        "created_at": 1710000000,
        "data": {
            "out_trade_no": "MOD123",
            "user_id": 42,
            "subject": "企业版月费",
            "total_amount": "99.00",
            "order_kind": "plan",
        },
    }


class TestModstorePaymentWebhook:
    def test_success_returns_accepted(self) -> None:
        with patch(
            "app.fastapi_routes.order_event_webhook.ingest_paid_event",
            return_value={"accepted": True, "emitted": True, "out_trade_no": "MOD123"},
        ) as mock_ingest:
            resp = _client().post(
                "/api/xcmax/webhooks/modstore/payment",
                json=_envelope(),
                headers={"X-Modstore-Webhook-Id": "w1"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["out_trade_no"] == "MOD123"
        mock_ingest.assert_called_once()
        kwargs = mock_ingest.call_args.kwargs
        assert kwargs["event_id"] == "w1"

    def test_rejected_envelope_returns_400(self) -> None:
        with patch(
            "app.fastapi_routes.order_event_webhook.ingest_paid_event",
            return_value={"accepted": False, "reason": "invalid_signature"},
        ):
            resp = _client().post(
                "/api/xcmax/webhooks/modstore/payment",
                json=_envelope(),
                headers={"X-Modstore-Webhook-Signature": "sha256=bad"},
            )
        assert resp.status_code == 400
        body = resp.json()
        assert body["success"] is False
        assert body["reason"] == "invalid_signature"

    def test_headers_are_forwarded(self) -> None:
        with patch(
            "app.fastapi_routes.order_event_webhook.ingest_paid_event",
            return_value={"accepted": True},
        ) as mock_ingest:
            _client().post(
                "/api/xcmax/webhooks/modstore/payment",
                json=_envelope(),
                headers={
                    "X-Modstore-Webhook-Signature": "sha256=abc",
                    "X-Modstore-Webhook-Timestamp": "1710000000",
                    "X-Modstore-Webhook-Id": "w9",
                },
            )
        kwargs = mock_ingest.call_args.kwargs
        assert kwargs["hmac_signature"] == "sha256=abc"
        assert kwargs["timestamp"] == "1710000000"
        assert kwargs["event_id"] == "w9"
        assert kwargs["raw"] is not None
