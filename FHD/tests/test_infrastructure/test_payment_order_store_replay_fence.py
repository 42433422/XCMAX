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


def test_unknown_order_is_quarantined_and_survives_ledger_reload(paid_store):
    reason, receipt = order_store.apply_notify_paid(
        out_trade_no="missing-merchant",
        trade_no="orphan-trade",
        total_amount="9.90",
    )
    assert reason == "unknown_order" and receipt is None
    persisted = json.loads(paid_store.read_text(encoding="utf-8"))
    assert "missing-merchant" not in persisted["orders"]
    assert persisted["entitlements"] == {}
    quarantine = order_store.list_unmatched_notifications()
    assert len(quarantine) == 1
    assert quarantine[0]["out_trade_no"] == "missing-merchant"
    assert quarantine[0]["state"] == "requires_reconciliation"
    assert quarantine[0]["retry_count"] == 1

    reason, receipt = order_store.apply_notify_paid(
        out_trade_no="missing-merchant",
        trade_no="orphan-trade",
        total_amount="9.90",
    )
    assert reason == "unknown_order" and receipt is None
    assert len(order_store.list_unmatched_notifications()) == 1
    assert order_store.list_unmatched_notifications()[0]["retry_count"] == 2


def test_quarantined_order_identity_cannot_be_reused(paid_store):
    order_store.apply_notify_paid(
        out_trade_no="missing-merchant",
        trade_no="orphan-trade",
        total_amount="9.90",
    )
    original = paid_store.read_bytes()
    with pytest.raises(ValueError, match="requires_manual_identity_reconciliation"):
        order_store.record_checkout_pending(
            out_trade_no="missing-merchant",
            plan_id="plan-test",
            amount_cents=990,
            amount_yuan="9.90",
        )
    assert paid_store.read_bytes() == original


def test_unknown_notification_missing_trade_identity_never_writes(paid_store):
    before = paid_store.read_bytes()
    reason, _ = order_store.apply_notify_paid(
        out_trade_no="missing-merchant", trade_no="", total_amount="9.90",
    )
    assert reason == "invalid_notify"
    assert paid_store.read_bytes() == before


def test_two_orders_cannot_share_same_provider_trade(paid_store):
    order_store.record_checkout_pending(
        out_trade_no="merchant-2", plan_id="plan-test", amount_cents=990, amount_yuan="9.90",
    )
    before = paid_store.read_bytes()
    reason, _ = order_store.apply_notify_paid(
        out_trade_no="merchant-2", trade_no="alipay-original", total_amount="9.90",
    )
    assert reason == "trade_mismatch"
    assert paid_store.read_bytes() == before


def test_paid_order_cannot_be_replaced_by_checkout_retry(paid_store):
    before = paid_store.read_bytes()
    with pytest.raises(ValueError, match="requires_manual_identity_reconciliation"):
        order_store.record_checkout_pending(
            out_trade_no="merchant-1", plan_id="plan-test", amount_cents=990, amount_yuan="9.90",
        )
    assert paid_store.read_bytes() == before


def test_corrupt_order_file_is_never_silently_replaced(paid_store):
    paid_store.write_text("{truncated", encoding="utf-8")
    before = paid_store.read_bytes()
    with pytest.raises(ValueError):
        order_store.apply_notify_paid(
            out_trade_no="orphan", trade_no="gateway-trade", total_amount="9.90",
        )
    assert paid_store.read_bytes() == before


@pytest.mark.parametrize("status", ["refunded", "closed", "refund_pending_reconciliation"])
def test_delayed_verified_paid_notify_cannot_reopen_terminal_order(paid_store, status):
    state = json.loads(paid_store.read_text(encoding="utf-8"))
    state["orders"]["merchant-1"]["status"] = status
    paid_store.write_text(json.dumps(state), encoding="utf-8")
    previous = paid_store.read_bytes()
    reason, receipt = order_store.apply_notify_paid(
        out_trade_no="merchant-1",
        trade_no="alipay-original",
        total_amount="9.90",
    )
    assert reason == "terminal_order_conflict"
    assert receipt["status"] == status
    assert paid_store.read_bytes() == previous
