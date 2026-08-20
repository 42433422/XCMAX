"""Normalization, redaction and production-payment classification."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

UTC = timezone.utc  # noqa: UP017 - MODstore CI and production still support Python 3.10

PROVIDER_VERIFICATIONS = frozenset(
    {
        "alipay_signed_callback",
        "alipay_remote_query",
        "wechat_signed_callback",
        "wechat_remote_query",
        "java_gateway_verified",
        "bank_statement_reconciled",
    }
)
PAYMENT_PROVIDERS = frozenset({"alipay", "wechat", "wechatpay", "bank"})
PRODUCTION_ENVIRONMENTS = frozenset({"production", "prod"})

_TEST_MARKERS = ("pilot", "pytest", "smoke", "sandbox", "试点", "沙箱", "测试")
_INTERNAL_MARKERS = ("internal", "auto-renew", "auto_renew", "内部", "自动续费")
_SENSITIVE_KEY = re.compile(r"secret|token|password|authorization|api[_-]?key", re.I)


def text(value: Any, limit: int = 512) -> str:
    return str(value or "").strip()[:limit]


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return text(value).lower() in {"1", "true", "yes", "on"}


def parse_datetime(value: Any) -> datetime | None:
    raw = text(value, 128)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def amount_cents(order: dict[str, Any]) -> int:
    direct = order.get("amount_cents")
    if direct not in (None, ""):
        try:
            return int(direct)
        except (TypeError, ValueError):
            return 0
    try:
        amount = Decimal(str(order.get("total_amount") or "0"))
    except (InvalidOperation, ValueError):
        return 0
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def payment_amount_cents(order: dict[str, Any]) -> int:
    return amount_cents(order)


def _has_marker(order: dict[str, Any], markers: tuple[str, ...]) -> bool:
    haystack = " ".join(
        text(order.get(key), 512).lower()
        for key in (
            "out_trade_no",
            "order_no",
            "subject",
            "description",
            "trade_no",
            "provider_trade_no",
        )
    )
    return any(marker in haystack for marker in markers)


def classify_payment_order(
    order: dict[str, Any], *, cutoff: datetime | None = None
) -> tuple[bool, str]:
    """Return whether an order is acceptable production-payment evidence."""
    if text(order.get("status")).lower() != "paid":
        return False, "not_paid"
    if truthy(order.get("provider_test_mode")) or _has_marker(order, _TEST_MARKERS):
        return False, "test_record"
    order_no = text(order.get("out_trade_no") or order.get("order_no"), 96).lower()
    if order_no.startswith("renew_") or _has_marker(order, _INTERNAL_MARKERS):
        return False, "internal_order"
    if truthy(order.get("refunded")) or text(order.get("refund_status")).lower() in {
        "refunded",
        "approved",
    }:
        return False, "refunded"
    if amount_cents(order) <= 0:
        return False, "nonpositive_amount"
    paid_at = parse_datetime(order.get("paid_at"))
    if paid_at is None:
        return False, "missing_paid_at"
    verification = text(order.get("provider_verification"), 64).lower()
    provider = text(order.get("payment_provider") or order.get("provider"), 32).lower()
    trade_no = text(order.get("provider_trade_no") or order.get("trade_no"), 128)
    if (
        verification not in PROVIDER_VERIFICATIONS
        or provider not in PAYMENT_PROVIDERS
        or not trade_no
    ):
        return False, "missing_provider_proof"
    environment = text(
        order.get("payment_environment") or order.get("environment") or order.get("deploy_tier"),
        32,
    ).lower()
    if environment not in PRODUCTION_ENVIRONMENTS:
        return False, "nonproduction"
    if cutoff is not None and paid_at < cutoff:
        return False, "outside_window"
    return True, "eligible"


def sanitize_evidence(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        return "<truncated>"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for raw_key, child in list(value.items())[:50]:
            key = text(raw_key, 96)
            result[key] = (
                "<redacted>"
                if _SENSITIVE_KEY.search(key)
                else sanitize_evidence(child, depth=depth + 1)
            )
        return result
    if isinstance(value, list):
        return [sanitize_evidence(item, depth=depth + 1) for item in value[:50]]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return text(value, 2000)
