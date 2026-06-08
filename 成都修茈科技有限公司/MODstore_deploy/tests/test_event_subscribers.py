"""Cross-cutting subscriber tests.

The subscribers turn raw domain events into notifications, audit log lines
and Prometheus counter ticks. The tests here pin the contract so payment /
refund publishers don't have to know about those side-effects.
"""

from __future__ import annotations

import logging

import pytest

from modstore_server.eventing import subscribers
from modstore_server.eventing.bus import InMemoryNeuroBus
from modstore_server.eventing.events import new_event


@pytest.fixture(autouse=True)
def _reset_subscriber_registration():
    subscribers.reset_for_tests()
    yield
    subscribers.reset_for_tests()


@pytest.fixture
def fresh_bus():
    return InMemoryNeuroBus()


def test_install_default_subscribers_is_idempotent(fresh_bus):
    subscribers.install_default_subscribers(fresh_bus)
    handler_counts_first = {k: len(v) for k, v in fresh_bus._handlers.items()}
    subscribers.install_default_subscribers(fresh_bus)
    handler_counts_second = {k: len(v) for k, v in fresh_bus._handlers.items()}
    assert handler_counts_first == handler_counts_second


def test_audit_logger_emits_record_for_every_event(fresh_bus, caplog):
    subscribers.install_default_subscribers(fresh_bus)
    with caplog.at_level(logging.INFO, logger="modstore_server.eventing.subscribers"):
        fresh_bus.publish(
            new_event(
                "payment.paid",
                producer="payment-test",
                subject_id="ORDERAUDIT",
                payload={"user_id": 0, "subject": "x", "total_amount": "1.00"},
            )
        )
    assert any("domain-event payment.paid" in r.message for r in caplog.records)


def test_payment_paid_creates_notification(fresh_bus, monkeypatch):
    captured: list[dict] = []

    def fake_create_notification(**kwargs):
        captured.append(kwargs)
        return None

    from modstore_server import notification_service

    monkeypatch.setattr(notification_service, "create_notification", fake_create_notification)

    subscribers.install_default_subscribers(fresh_bus)
    fresh_bus.publish(
        new_event(
            "payment.paid",
            producer="payment-test",
            subject_id="ORDERPAY",
            payload={
                "out_trade_no": "ORDERPAY",
                "user_id": 42,
                "subject": "VIP",
                "total_amount": "9.90",
                "order_kind": "plan",
            },
        )
    )
    assert len(captured) == 1
    call = captured[0]
    assert call["user_id"] == 42
    assert call["title"] == "支付成功"
    assert "9.90" in call["content"]
    assert call["data"]["order_no"] == "ORDERPAY"
    assert call["data"]["event_id"]


def test_payment_paid_skips_when_user_id_missing(fresh_bus, monkeypatch):
    captured: list[dict] = []

    from modstore_server import notification_service

    monkeypatch.setattr(
        notification_service,
        "create_notification",
        lambda **kw: captured.append(kw),
    )

    subscribers.install_default_subscribers(fresh_bus)
    fresh_bus.publish(
        new_event(
            "payment.paid",
            producer="payment-test",
            subject_id="NOUSER",
            payload={"out_trade_no": "NOUSER"},
        )
    )
    assert captured == []


def test_refund_outcome_dispatches_distinct_messages(fresh_bus, monkeypatch):
    captured: list[dict] = []

    from modstore_server import notification_service

    monkeypatch.setattr(
        notification_service,
        "create_notification",
        lambda **kw: captured.append(kw),
    )

    subscribers.install_default_subscribers(fresh_bus)
    for status, expected_title in (
        ("refund.approved", "退款成功"),
        ("refund.rejected", "退款被拒绝"),
        ("refund.failed", "退款执行失败"),
    ):
        # Fresh idempotency key per event so the bus actually delivers each.
        fresh_bus.publish(
            new_event(
                status,
                producer="refund-test",
                subject_id=f"R-{status}",
                payload={
                    "refund_id": status,
                    "order_no": f"ORD-{status}",
                    "user_id": 7,
                    "amount": "1.00",
                    "status": status.split(".", 1)[1],
                },
            )
        )

    titles = [c["title"] for c in captured]
    assert titles == ["退款成功", "退款被拒绝", "退款执行失败"]


def test_subscriber_failures_increment_error_counter(fresh_bus, monkeypatch):
    from modstore_server import notification_service

    def boom(**_kw):
        raise RuntimeError("notification db down")

    monkeypatch.setattr(notification_service, "create_notification", boom)

    subscribers.install_default_subscribers(fresh_bus)

    before = subscribers.EVENT_PUBLISHED_TOTAL.labels(
        "payment.paid", "subscriber_error"
    )._value.get()

    fresh_bus.publish(
        new_event(
            "payment.paid",
            producer="payment-test",
            subject_id="ORDERFAIL",
            payload={
                "out_trade_no": "ORDERFAIL",
                "user_id": 8,
                "subject": "VIP",
                "total_amount": "9.90",
            },
        )
    )

    after = subscribers.EVENT_PUBLISHED_TOTAL.labels(
        "payment.paid", "subscriber_error"
    )._value.get()
    assert after - before == 1
