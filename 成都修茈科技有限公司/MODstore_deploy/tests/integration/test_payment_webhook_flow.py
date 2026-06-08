"""Payment webhook integration: deterministic event id, HMAC sign, replay idempotency."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from modstore_server import webhook_dispatcher


@pytest.fixture(autouse=True)
def _isolated_webhook_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_WEBHOOK_EVENTS_DIR", str(tmp_path / "events"))
    monkeypatch.delenv("MODSTORE_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("MODSTORE_WEBHOOK_SECRET", raising=False)
    yield


@pytest.mark.integration
def test_payment_event_id_stable_across_alias():
    """Same aggregate must map to one event id (idempotent dispatch key)."""
    a = webhook_dispatcher.stable_event_id("payment.order_paid", "ORDER-42")
    b = webhook_dispatcher.stable_event_id("payment.paid", "ORDER-42")
    assert a == b == "payment.paid:ORDER-42"


@pytest.mark.integration
def test_payment_webhook_sign_and_replay_roundtrip(monkeypatch):
    monkeypatch.setenv("MODSTORE_WEBHOOK_URL", "https://example.test/hook")
    monkeypatch.setenv("MODSTORE_WEBHOOK_SECRET", "integration-secret")
    monkeypatch.setenv("MODSTORE_WEBHOOK_RETRIES", "0")

    captured: dict = {}

    class _Resp:
        status_code = 200
        text = "ok"

    class _Client:
        def __init__(self, *args, **kwargs):
            captured["kwargs"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, content, headers):
            captured["url"] = url
            captured["content"] = content
            captured["headers"] = headers
            return _Resp()

    monkeypatch.setattr(webhook_dispatcher.httpx, "Client", _Client)

    event = webhook_dispatcher.build_event(
        "payment.order_paid",
        "ORDER-42",
        {"out_trade_no": "ORDER-42", "total_amount": "9.90"},
    )
    first = webhook_dispatcher.dispatch_event(event)
    assert first["ok"] is True

    ts = captured["headers"]["X-Modstore-Webhook-Timestamp"]
    sig = captured["headers"]["X-Modstore-Webhook-Signature"]
    expected = hmac.new(
        b"integration-secret",
        ts.encode() + b"." + event["id"].encode() + b"." + captured["content"],
        hashlib.sha256,
    ).hexdigest()
    assert sig == f"sha256={expected}"

    replay = webhook_dispatcher.replay_event(event["id"])
    assert replay.get("ok") is True or "echoed" in replay

    stored_path = webhook_dispatcher._event_path(event["id"])
    assert stored_path.exists()
    envelope = json.loads(stored_path.read_text(encoding="utf-8"))
    assert envelope["event"]["id"] == event["id"]
