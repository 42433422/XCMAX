"""Unit tests for ``modstore_server.webhook_dispatcher``.

These focus on the cross-service event delivery path, which is part of the
Python -> Java payment migration's critical surface.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from modstore_server import webhook_dispatcher


@pytest.fixture(autouse=True)
def _isolated_events_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_WEBHOOK_EVENTS_DIR", str(tmp_path / "events"))
    monkeypatch.delenv("MODSTORE_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("MODSTORE_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("MODSTORE_WEBHOOK_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("MODSTORE_WEBHOOK_RETRIES", raising=False)
    yield


def test_webhook_enabled_reflects_environment(monkeypatch):
    assert webhook_dispatcher.webhook_enabled() is False
    monkeypatch.setenv("MODSTORE_WEBHOOK_URL", "https://example.com/hook")
    assert webhook_dispatcher.webhook_enabled() is True


def test_stable_event_id_is_deterministic_for_aggregate():
    a = webhook_dispatcher.stable_event_id("payment.order_paid", "MOD1")
    b = webhook_dispatcher.stable_event_id("payment.paid", "MOD1")
    assert a == b == "payment.paid:MOD1"


def test_stable_event_id_falls_back_when_aggregate_missing():
    eid = webhook_dispatcher.stable_event_id("payment.paid", "")
    assert eid.startswith("payment.paid:")
    assert len(eid) > len("payment.paid:")


def test_build_event_canonicalises_legacy_alias():
    event = webhook_dispatcher.build_event("payment.order_paid", "MOD42", {"out_trade_no": "MOD42"})
    assert event["type"] == "payment.paid"
    assert event["version"] == 1
    assert event["aggregate_id"] == "MOD42"
    assert event["id"] == "payment.paid:MOD42"
    assert event["data"] == {"out_trade_no": "MOD42"}


def test_dispatch_event_skipped_without_url():
    event = webhook_dispatcher.build_event("payment.paid", "MOD1", {"x": 1})
    result = webhook_dispatcher.dispatch_event(event)
    assert result["ok"] is False
    assert result.get("skipped") is True


def test_dispatch_event_signs_with_hmac(monkeypatch):
    monkeypatch.setenv("MODSTORE_WEBHOOK_URL", "https://example.com/hook")
    monkeypatch.setenv("MODSTORE_WEBHOOK_SECRET", "topsecret")
    monkeypatch.setenv("MODSTORE_WEBHOOK_RETRIES", "0")

    captured: dict = {}

    class _FakeResponse:
        status_code = 200
        text = "ok"

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            captured["client_args"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, content, headers):
            captured["url"] = url
            captured["content"] = content
            captured["headers"] = headers
            return _FakeResponse()

    monkeypatch.setattr(webhook_dispatcher.httpx, "Client", _FakeClient)

    event = webhook_dispatcher.build_event("payment.paid", "MOD1", {"out_trade_no": "MOD1"})
    result = webhook_dispatcher.dispatch_event(event)

    assert result["ok"] is True
    headers = captured["headers"]
    assert headers["X-Modstore-Webhook-Id"] == event["id"]
    assert headers["X-Modstore-Webhook-Event"] == "payment.paid"
    timestamp = headers["X-Modstore-Webhook-Timestamp"]
    sig_header = headers["X-Modstore-Webhook-Signature"]
    assert sig_header.startswith("sha256=")
    expected = hmac.new(
        b"topsecret",
        timestamp.encode() + b"." + event["id"].encode() + b"." + captured["content"],
        hashlib.sha256,
    ).hexdigest()
    assert sig_header == f"sha256={expected}"


def test_dispatch_event_retries_on_http_error(monkeypatch):
    monkeypatch.setenv("MODSTORE_WEBHOOK_URL", "https://example.com/hook")
    monkeypatch.setenv("MODSTORE_WEBHOOK_RETRIES", "1")

    attempts = {"count": 0}

    class _Boom:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **kw):
            attempts["count"] += 1
            raise webhook_dispatcher.httpx.HTTPError("boom")

    monkeypatch.setattr(webhook_dispatcher.httpx, "Client", _Boom)
    monkeypatch.setattr(webhook_dispatcher.time, "sleep", lambda *_: None)

    event = webhook_dispatcher.build_event("payment.paid", "MOD2", {"x": 1})
    result = webhook_dispatcher.dispatch_event(event)

    assert result["ok"] is False
    assert result["attempts"] == 2  # 1 retry + initial
    assert attempts["count"] == 2


def test_dispatch_event_rejects_non_2xx(monkeypatch):
    monkeypatch.setenv("MODSTORE_WEBHOOK_URL", "https://example.com/hook")
    monkeypatch.setenv("MODSTORE_WEBHOOK_RETRIES", "0")

    class _Resp:
        status_code = 500
        text = "boom"

    class _Client:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **kw):
            return _Resp()

    monkeypatch.setattr(webhook_dispatcher.httpx, "Client", _Client)
    monkeypatch.setattr(webhook_dispatcher.time, "sleep", lambda *_: None)
    event = webhook_dispatcher.build_event("payment.paid", "MOD3", {"x": 1})
    result = webhook_dispatcher.dispatch_event(event)
    assert result["ok"] is False
    assert "HTTP 500" in (result.get("message") or "")


def test_replay_event_returns_not_found_when_missing():
    result = webhook_dispatcher.replay_event("does-not-exist")
    assert result["ok"] is False
    assert result["message"] == "webhook event not found"


def test_replay_event_loads_persisted_envelope(monkeypatch, tmp_path):
    event = webhook_dispatcher.build_event("payment.paid", "MODR", {"x": 1})
    webhook_dispatcher._store_event(event, {"ok": False})

    captured: dict = {}

    def fake_dispatch(e):
        captured["event"] = e
        return {"ok": True, "echoed": True}

    monkeypatch.setattr(webhook_dispatcher, "dispatch_event", fake_dispatch)

    result = webhook_dispatcher.replay_event(event["id"])
    assert result == {"ok": True, "echoed": True}
    assert captured["event"]["id"] == event["id"]


def test_publish_event_dispatches_and_emits_to_neuro_bus(monkeypatch):
    captured = {}

    def fake_dispatch(event):
        captured["dispatched"] = event
        return {"ok": True}

    seen_neuro = []

    class FakeBus:
        def publish(self, envelope):
            seen_neuro.append(envelope)

    monkeypatch.setattr(webhook_dispatcher, "dispatch_event", fake_dispatch)
    monkeypatch.setattr(webhook_dispatcher, "neuro_bus", FakeBus())

    result = webhook_dispatcher.publish_event(
        "payment.order_paid",
        "MODP",
        {
            "out_trade_no": "MODP",
            "user_id": 7,
            "subject": "x",
            "total_amount": "9.90",
            "order_kind": "plan",
        },
    )
    # ``publish_event`` 自 PR-D 起还会扇出到 ``webhook_subscriptions``，
    # 没有订阅时返回 0；只断言 ok 与 dispatcher 投递成功。
    assert result.get("ok") is True
    assert result.get("subscriptions_delivered", 0) == 0
    assert captured["dispatched"]["type"] == "payment.paid"
    assert seen_neuro, "publish_event must also notify the in-process NeuroBus"


def test_publish_event_logs_missing_required_fields(monkeypatch, caplog):
    monkeypatch.setattr(webhook_dispatcher, "dispatch_event", lambda e: {"ok": True})

    class _Bus:
        def publish(self, *a, **kw):
            return None

    monkeypatch.setattr(webhook_dispatcher, "neuro_bus", _Bus())

    with caplog.at_level("WARNING", logger="modstore_server.webhook_dispatcher"):
        webhook_dispatcher.publish_event("payment.paid", "MODX", {"out_trade_no": "MODX"})
    assert any("event payload missing" in r.message for r in caplog.records)
