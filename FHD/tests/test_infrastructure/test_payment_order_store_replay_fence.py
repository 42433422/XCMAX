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


def test_refund_claim_must_precede_provider_and_confirm_exact_replay(paid_store):
    first, snap = order_store.reserve_refund_attempt(
        out_trade_no="merchant-1", out_request_no="refund-r1", amount_cents=500,
    )
    assert first == "refund_reserved"
    assert snap["state"] == "pending_provider_confirmation"
    assert order_store.get_order("merchant-1")["status"] == "refund_pending_reconciliation"
    assert order_store.observe_refund_provider_result(
        out_trade_no="merchant-1", out_request_no="refund-r1",
        provider_reported_success=True,
    )
    assert order_store.get_order("merchant-1")["status"] == "refund_pending_reconciliation"
    reason, _ = order_store.reserve_refund_attempt(
        out_trade_no="merchant-1", out_request_no="refund-r2", amount_cents=490,
    )
    assert reason == "refund_order_not_settled"
    reason, _ = order_store.confirm_refund_from_provider_query(
        out_trade_no="merchant-1", out_request_no="refund-r1", amount_cents=501,
    )
    assert reason == "refund_amount_mismatch"
    assert "refunded_amount_cents" not in order_store.get_order("merchant-1")
    reason, _ = order_store.confirm_refund_from_provider_query(
        out_trade_no="merchant-1", out_request_no="refund-r1", amount_cents=500,
    )
    assert reason == "refund_confirmed"
    assert order_store.get_order("merchant-1")["status"] == "partially_refunded"
    assert order_store.get_order("merchant-1")["refunded_amount_cents"] == 500
    assert order_store.confirm_refund_from_provider_query(
        out_trade_no="merchant-1", out_request_no="refund-r1", amount_cents=500,
    )[0] == "already_confirmed"
    assert order_store.reserve_refund_attempt(
        out_trade_no="merchant-1", out_request_no="refund-r1", amount_cents=500,
    )[0] == "refund_request_replay"
    assert order_store.reserve_refund_attempt(
        out_trade_no="merchant-1", out_request_no="refund-r2", amount_cents=491,
    )[0] == "refund_amount_exceeds_original"
    assert order_store.reserve_refund_attempt(
        out_trade_no="merchant-1", out_request_no="refund-r2", amount_cents=490,
    )[0] == "refund_reserved"
    assert order_store.confirm_refund_from_provider_query(
        out_trade_no="merchant-1", out_request_no="refund-r2", amount_cents=490,
    )[0] == "refund_confirmed"
    assert order_store.get_order("merchant-1")["status"] == "refunded"
    assert order_store.get_order("merchant-1")["refunded_amount_cents"] == 990


def test_refund_pending_claim_survives_disk_reload_and_blocks_new_gateway_call(paid_store):
    assert order_store.reserve_refund_attempt(
        out_trade_no="merchant-1", out_request_no="refund-r1", amount_cents=100,
    )[0] == "refund_reserved"
    original = paid_store.read_bytes()
    assert order_store.reserve_refund_attempt(
        out_trade_no="merchant-1", out_request_no="refund-r1", amount_cents=100,
    )[0] == "refund_order_not_settled"
    assert order_store.reserve_refund_attempt(
        out_trade_no="merchant-1", out_request_no="refund-r2", amount_cents=100,
    )[0] == "refund_order_not_settled"
    assert paid_store.read_bytes() == original


@pytest.mark.parametrize("amount", [0, -1, True, 991])
def test_refund_amount_fence(paid_store, amount):
    reason, _ = order_store.reserve_refund_attempt(
        out_trade_no="merchant-1", out_request_no="refund-1", amount_cents=amount,
    )
    assert reason == (
        "refund_amount_exceeds_original" if amount == 991 else "refund_request_invalid"
    )


def test_concurrent_refund_claim_admits_only_one_gateway_dispatch(paid_store):
    from concurrent.futures import ThreadPoolExecutor

    def reserve(i):
        return order_store.reserve_refund_attempt(
            out_trade_no="merchant-1", out_request_no=f"attempt-{i}", amount_cents=990,
        )[0]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(reserve, range(8)))
    assert results.count("refund_reserved") == 1
    assert len(order_store.get_order("merchant-1")["refund_attempts"]) == 1
