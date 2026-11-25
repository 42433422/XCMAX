"""Verified callbacks may never silently rebind a paid merchant order."""

from __future__ import annotations

import json

import pytest

from app.infrastructure.payment import order_store


@pytest.fixture
def paid_store(tmp_path, monkeypatch):
    path = tmp_path / "payment-orders.json"
    monkeypatch.setenv("MODEL_PAYMENT_ORDER_STORE_PATH", str(path))
    order = {
        "out_trade_no": "merchant-1",
        "plan_id": "plan-test",
        "amount_cents": 990,
        "status": "paid",
        "trade_no": "alipay-original",
        "notify_count": 1,
    }
    payload = {"orders": {"merchant-1": order}, "entitlements": {}}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.mark.parametrize("status", ["paid", "paid_pending_fulfillment"])
def test_wrong_provider_trade_does_not_mutate_existing_payment(paid_store, status):
    payload = json.loads(paid_store.read_text(encoding="utf-8"))
    payload["orders"]["merchant-1"]["status"] = status
    paid_store.write_text(json.dumps(payload), encoding="utf-8")
    original = paid_store.read_bytes()

    reason, receipt = order_store.apply_notify_paid(
        out_trade_no="merchant-1",
        trade_no="alipay-different",
        total_amount="9.90",
    )

    assert reason == "trade_mismatch"
    assert receipt["trade_no"] == "alipay-original"
    assert paid_store.read_bytes() == original


def test_exact_trade_replay_remains_idempotent(paid_store):
    first = json.loads(paid_store.read_text(encoding="utf-8"))
    reason, receipt = order_store.apply_notify_paid(
        out_trade_no="merchant-1",
        trade_no="alipay-original",
        total_amount="9.90",
    )
    assert reason == "already_paid"
    assert receipt["trade_no"] == "alipay-original"
    assert receipt["notify_count"] == first["orders"]["merchant-1"]["notify_count"] + 1
    after = json.loads(paid_store.read_text(encoding="utf-8"))
    assert after["entitlements"] == first["entitlements"]
    assert after["orders"]["merchant-1"]["status"] == "paid"


def test_unknown_order_is_not_inserted_or_silently_marked_paid(paid_store):
    original = paid_store.read_bytes()
    reason, receipt = order_store.apply_notify_paid(
        out_trade_no="missing-merchant",
        trade_no="orphan-trade",
        total_amount="9.90",
    )
    assert reason == "unknown_order" and receipt is None
    assert paid_store.read_bytes() == original
