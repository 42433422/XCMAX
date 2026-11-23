"""Project authenticated native wallet credits into one append-only order refund.

The existing Java refund/transaction ledger is the producer. This module neither
initiates refunds nor treats a missing payment, approval or webhook as settlement.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable

from modstore_server.customer_value_classification import (
    _INTERNAL_MARKERS,
    _TEST_MARKERS,
    _has_marker,
)

_READER_SEAL = object()
REFUND_SOURCE = "java_postgresql_wallet_refunds_v1"


class RefundNotCustomer(ValueError):
    """The native ledger fact is valid but excluded from customer business evidence."""


def _instant(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("wallet refund timestamp missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("wallet refund timestamp has no timezone")
    return parsed.astimezone(UTC)


@dataclass(frozen=True)
class WalletRefundEvidence:
    """An in-process capability issued only by the authenticated source reader."""

    _payload_json: str = field(repr=False)
    _reader_seal: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._reader_seal is not _READER_SEAL:
            raise ValueError("wallet refund requires the authenticated ledger reader")

    def receipt_payload(self) -> dict[str, Any]:
        row = json.loads(self._payload_json)
        return {
            "receipt_kind": "refund",
            "verification_status": "verified",
            "source_event_id": f"java-wallet-refund:{row['refund_no']}",
            "customer_ref": f"paid-user:{row['user_id']}",
            "customer_goal_id": "",
            "order_no": row["order_no"],
            "amount_cents": row["amount_cents"],
            "currency": row["currency"],
            "payment_provider": row["payment_provider"],
            "provider_trade_no": row["provider_trade_no"],
            "provider_verification": row["verification"],
            "environment": row["payment_environment"],
            "occurred_at": row["refunded_at"],
            "evidence": {
                "source": REFUND_SOURCE,
                **{
                    key: value
                    for key, value in row.items()
                    if key not in {"order_subject", "order_kind"}
                },
            },
        }

    def require_payload(self, payload: dict[str, Any]) -> None:
        if self._reader_seal is not _READER_SEAL or payload != self.receipt_payload():
            raise ValueError("wallet refund differs from its authenticated native ledger receipt")


def _from_authenticated_row(row: dict[str, Any], as_of: str) -> WalletRefundEvidence:
    """Called after internal-key HTTP authentication and complete-page validation."""
    fields = {
        "verified",
        "refund_id",
        "refund_no",
        "order_no",
        "user_id",
        "wallet_transaction_id",
        "amount_cents",
        "currency",
        "refunded_at",
        "credited_at",
        "paid_at",
        "order_total_amount_cents",
        "order_status",
        "payment_provider",
        "provider_trade_no",
        "payment_environment",
        "provider_test_mode",
        "verification",
        "order_subject",
        "order_kind",
    }
    if set(row) != fields or row["verified"] is not True or row["provider_test_mode"] is not False:
        raise ValueError("wallet refund evidence contract incomplete")
    if not isinstance(row["order_subject"], str) or not isinstance(row["order_kind"], str):
        raise ValueError("wallet refund original order classification missing")
    for key in (
        "refund_id",
        "user_id",
        "wallet_transaction_id",
        "amount_cents",
        "order_total_amount_cents",
    ):
        if type(row[key]) is not int or not 0 < row[key] <= 2_147_483_647:
            raise ValueError("wallet refund identity or amount invalid")
    for key, limit in (("refund_no", 64), ("order_no", 96), ("provider_trade_no", 128)):
        if not isinstance(row[key], str) or not re.fullmatch(
            rf"[A-Za-z0-9_.:-]{{1,{limit}}}", row[key]
        ):
            raise ValueError("wallet refund native identity invalid")
    if (
        row["currency"] != "CNY"
        or row["payment_provider"] not in {"alipay", "wechat"}
        or row["payment_environment"] not in {"production", "prod"}
        or row["verification"] != "java_wallet_credit_confirmed"
        or row["order_status"] not in {"refunded", "partial_refunded"}
        or row["amount_cents"] > row["order_total_amount_cents"]
        or not _instant(row["paid_at"])
        <= _instant(row["credited_at"])
        <= _instant(row["refunded_at"])
        <= _instant(as_of)
    ):
        raise ValueError("wallet refund is not a confirmed production CNY credit")
    original = {
        "out_trade_no": row["order_no"],
        "subject": row["order_subject"],
        "provider_trade_no": row["provider_trade_no"],
    }
    if (
        row["order_no"].lower().startswith("renew_")
        or _has_marker(original, _TEST_MARKERS)
        or _has_marker(original, _INTERNAL_MARKERS)
    ):
        raise RefundNotCustomer("wallet refund belongs to an excluded test or internal order")
    return WalletRefundEvidence(
        json.dumps(row, sort_keys=True, separators=(",", ":")), _READER_SEAL
    )


def reconcile_wallet_refunds(
    *,
    window_days: int,
    session_factory: Callable[..., Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    from modstore_server.customer_value_evidence import append_customer_value_receipt
    from modstore_server.customer_value_payment_source import load_authoritative_wallet_refunds

    source = load_authoritative_wallet_refunds(window_days)
    result: dict[str, Any] = {
        "source_owner": source["source_owner"],
        "source_ready": source["source_available"] is True
        and source["source_authoritative"] is True,
        "created": 0,
        "existing": 0,
        "unknown": source.get("unknown", 0),
        "excluded": source.get("excluded", 0),
    }
    if not result["source_ready"]:
        return result
    for proof in source["refunds"]:
        stored = append_customer_value_receipt(
            proof.receipt_payload(), refund_evidence=proof, session_factory=session_factory, now=now
        )
        key = "created" if stored["created"] else "existing"
        result[key] += 1
    return result
