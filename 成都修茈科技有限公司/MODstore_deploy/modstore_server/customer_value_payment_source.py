"""Authoritative payment evidence readers and gateway proof markers."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable

import httpx

from modstore_server import payment_orders
from modstore_server.customer_value_classification import text as _text
from modstore_server.customer_value_classification import truthy as _truthy

UTC = timezone.utc  # noqa: UP017 - MODstore CI and production still support Python 3.10
_JAVA_PAGE_SIZE = 1000
_JAVA_MAX_ORDERS = 100_000


def _internal_api_key() -> str:
    return _text(
        os.environ.get("MODSTORE_INTERNAL_API_KEY")
        or os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY"),
        4096,
    )


def load_java_payment_orders(window_days: int) -> list[dict[str, Any]]:
    """Read minimal payment proof from the Java/PostgreSQL source of truth."""

    key = _internal_api_key()
    if not key:
        raise RuntimeError("java_payment_internal_key_unavailable")
    base_url = _text(
        os.environ.get("JAVA_PAYMENT_SERVICE_URL") or "http://127.0.0.1:8080",
        2048,
    ).rstrip("/")
    if not base_url:
        raise RuntimeError("java_payment_service_url_unavailable")

    orders: list[dict[str, Any]] = []
    offset = 0
    max_pages = (_JAVA_MAX_ORDERS // _JAVA_PAGE_SIZE) + 1
    with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
        for _page_number in range(max_pages):
            response = client.get(
                f"{base_url}/api/internal/payment/value-evidence",
                params={
                    "window_days": window_days,
                    "limit": _JAVA_PAGE_SIZE,
                    "offset": offset,
                },
                headers={"X-Internal-Api-Key": key},
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError("java_payment_evidence_payload_invalid")
            if payload.get("ok") is not True or payload.get("source") != "java_postgresql":
                raise RuntimeError("java_payment_evidence_source_untrusted")
            page = payload.get("orders")
            if not isinstance(page, list) or any(not isinstance(item, dict) for item in page):
                raise RuntimeError("java_payment_evidence_orders_invalid")
            total = int(payload.get("total") or 0)
            if total < 0 or total > _JAVA_MAX_ORDERS:
                raise RuntimeError("java_payment_evidence_total_out_of_bounds")
            orders.extend(dict(item) for item in page)
            if len(orders) >= total:
                break
            if not page or len(orders) > _JAVA_MAX_ORDERS:
                raise RuntimeError("java_payment_evidence_pagination_incomplete")
            offset += _JAVA_PAGE_SIZE
        else:
            raise RuntimeError("java_payment_evidence_pagination_incomplete")
    return orders


def load_authoritative_payment_orders(
    window_days: int,
    *,
    java_loader: Callable[[int], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Return payment rows plus explicit source availability and ownership."""

    days = max(1, min(int(window_days), 3650))
    if payment_orders.is_local_source_of_truth():
        try:
            found, _ = payment_orders.list_orders(status="paid", limit=_JAVA_MAX_ORDERS)
            rows = [dict(item) for item in found if isinstance(item, dict)]
        except (OSError, ValueError, TypeError):
            return {
                "orders": [],
                "source_owner": "python_payment_orders",
                "source_available": False,
                "source_authoritative": False,
            }
        return {
            "orders": rows,
            "source_owner": "python_payment_orders",
            "source_available": True,
            "source_authoritative": True,
        }

    loader = java_loader or load_java_payment_orders
    try:
        rows = loader(days)
    except (httpx.HTTPError, RuntimeError, TypeError, ValueError):
        return {
            "orders": [],
            "source_owner": "java_postgresql_internal_api",
            "source_available": False,
            "source_authoritative": False,
        }
    return {
        "orders": rows,
        "source_owner": "java_postgresql_internal_api",
        "source_available": True,
        "source_authoritative": True,
    }


def payment_evidence_marker(*, provider: str, verification: str, trade_no: str) -> dict[str, Any]:
    """Canonical fields written only after a gateway verification succeeds."""

    deploy_tier = _text(os.environ.get("MODSTORE_DEPLOY_TIER") or "local", 32).lower()
    test_mode = _truthy(os.environ.get("ALIPAY_DEBUG")) or _truthy(
        os.environ.get("MODSTORE_PAYMENT_TEST_MODE")
    )
    return {
        "payment_provider": _text(provider, 32).lower(),
        "provider_trade_no": _text(trade_no, 128),
        "provider_verification": _text(verification, 64).lower(),
        "provider_verified_at": datetime.now(UTC).isoformat(),
        "provider_test_mode": test_mode,
        "payment_environment": deploy_tier,
    }
