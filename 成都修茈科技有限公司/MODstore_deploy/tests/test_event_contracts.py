from __future__ import annotations

from modstore_server.eventing.contracts import (
    PAYMENT_ORDER_PAID_LEGACY,
    PAYMENT_PAID,
    canonical_event_name,
    event_version,
    validate_payload,
)
from modstore_server.webhook_dispatcher import build_event


def test_legacy_payment_event_alias_canonicalizes_to_payment_paid():
    assert canonical_event_name(PAYMENT_ORDER_PAID_LEGACY) == PAYMENT_PAID
    assert event_version(PAYMENT_ORDER_PAID_LEGACY) == 1


def test_payment_payload_contract_reports_missing_fields():
    missing = validate_payload(PAYMENT_PAID, {"out_trade_no": "MOD1"})

    assert "user_id" in missing
    assert "total_amount" in missing


def test_webhook_envelope_includes_canonical_type_and_version():
    event = build_event(PAYMENT_ORDER_PAID_LEGACY, "MOD1", {"out_trade_no": "MOD1"})

    assert event["id"] == "payment.paid:MOD1"
    assert event["type"] == PAYMENT_PAID
    assert event["version"] == 1
    assert event["aggregate_id"] == "MOD1"
