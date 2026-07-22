"""Turn fulfilled catalog-item payments into customer-value receipts."""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable

from modstore_server.customer_value_evidence import (
    append_customer_value_receipt,
    classify_payment_order,
    load_authoritative_payment_orders,
    payment_amount_cents,
)

UTC = timezone.utc  # noqa: UP017 - MODstore CI and production still support Python 3.10


def _digest(value: Any) -> str:
    return hashlib.sha256(str(value or "").strip().encode("utf-8")).hexdigest()[:32]


def _receipt_payloads(order: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    order_no = str(order.get("out_trade_no") or order.get("order_no") or "").strip()
    identity = _digest(order_no)
    provider_identity = _digest(order.get("provider_trade_no") or order.get("trade_no") or order_no)
    artifact_id = str(order.get("fulfillment_artifact_id") or "").strip()
    artifact_sha256 = str(order.get("fulfillment_artifact_sha256") or "").strip().lower()
    goal_id = f"purchase-fulfillment:{identity}"
    common = {
        "verification_status": "verified",
        "customer_ref": f"payment-customer:{provider_identity}",
        "customer_goal_id": goal_id,
        "order_no": order_no,
        "source_employee_id": "delivery-receipt-officer",
        "occurred_at": order.get("fulfilled_at") or datetime.now(UTC).isoformat(),
        "amount_cents": payment_amount_cents(order),
        "currency": order.get("currency") or "CNY",
        "payment_provider": order.get("payment_provider") or "",
        "provider_trade_no": order.get("provider_trade_no") or order.get("trade_no") or "",
        "provider_verification": order.get("provider_verification") or "",
        "environment": order.get("payment_environment") or order.get("environment") or "",
        "evidence": {
            "source": "authoritative_payment_fulfillment",
            "order_kind": str(order.get("order_kind") or "")[:32],
            "fulfilled": True,
            "fulfillment_verified": True,
            "artifact_id": artifact_id,
            "artifact_sha256": artifact_sha256,
            "identity_sha256_prefix": identity,
        },
    }
    goal = {
        **common,
        "receipt_kind": "goal",
        "source_event_id": f"payment-fulfillment-goal:{identity}",
    }
    delivery = {
        **common,
        "receipt_kind": "delivery",
        "source_event_id": f"payment-fulfillment-delivery:{identity}",
        "artifact_id": artifact_id,
    }
    return goal, delivery


def reconcile_paid_customer_value(
    *,
    window_days: int = 90,
    orders: list[dict[str, Any]] | None = None,
    session_factory: Callable[..., Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Append goal and delivery proof for each eligible, fulfilled payment."""

    if orders is None:
        source = load_authoritative_payment_orders(window_days)
        source_owner = str(source.get("source_owner") or "unavailable")
        source_ready = bool(
            source.get("source_available") is True and source.get("source_authoritative") is True
        )
        rows = [dict(row) for row in source.get("orders") or [] if isinstance(row, dict)]
    else:
        source_owner = "injected"
        source_ready = True
        rows = [dict(row) for row in orders if isinstance(row, dict)]

    if not source_ready:
        return {
            "ok": False,
            "source_owner": source_owner,
            "source_ready": False,
            "checked": 0,
            "created": 0,
            "existing": 0,
            "skipped": {},
        }

    created = 0
    existing = 0
    skipped: Counter[str] = Counter()
    for order in rows:
        eligible, reason = classify_payment_order(order)
        if not eligible:
            skipped[reason] += 1
            continue
        if order.get("fulfilled") is not True:
            skipped["not_fulfilled"] += 1
            continue
        order_kind = str(order.get("order_kind") or "").strip().lower()
        try:
            item_id = int(order.get("item_id") or 0)
        except (TypeError, ValueError):
            item_id = 0
        if order_kind != "item" or item_id <= 0:
            skipped["non_deliverable_order_kind"] += 1
            continue
        if order.get("fulfillment_verified") is not True:
            skipped["fulfillment_unverified"] += 1
            continue
        artifact_id = str(order.get("fulfillment_artifact_id") or "").strip()
        artifact_sha256 = str(order.get("fulfillment_artifact_sha256") or "").strip().lower()
        if not artifact_id or not artifact_sha256 or len(artifact_sha256) != 64:
            skipped["artifact_proof_missing"] += 1
            continue
        if any(char not in "0123456789abcdef" for char in artifact_sha256):
            skipped["artifact_proof_invalid"] += 1
            continue
        if not str(order.get("fulfilled_at") or "").strip():
            skipped["fulfilled_at_missing"] += 1
            continue
        for payload in _receipt_payloads(order):
            result = append_customer_value_receipt(
                payload,
                payment_order=order,
                session_factory=session_factory,
                now=now,
            )
            if result.get("created") is True:
                created += 1
            else:
                existing += 1
    return {
        "ok": True,
        "source_owner": source_owner,
        "source_ready": True,
        "checked": len(rows),
        "created": created,
        "existing": existing,
        "skipped": dict(sorted(skipped.items())),
    }


__all__ = ["reconcile_paid_customer_value"]
