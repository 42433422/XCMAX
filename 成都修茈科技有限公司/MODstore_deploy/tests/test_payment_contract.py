"""Cross-service payment contract regression tests.

If this file fails, you have either silently changed a public payment route,
the sign-checkout canonical form, the webhook payload contract, the proxy
prefix list, or the frontend payment client. Update
``docs/PAYMENT_CONTRACT.md`` and the corresponding Python/Java/frontend
implementation together, NEVER weaken a single side.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from modstore_server import payment_contract
from modstore_server.application.payment_gateway import PaymentGatewayService
from modstore_server.eventing.contracts import (
    EVENT_CONTRACTS,
    PAYMENT_PAID,
    REFUND_APPROVED,
    REFUND_FAILED,
    REFUND_REJECTED,
    WALLET_BALANCE_CHANGED,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---- Proxy prefix pinning -------------------------------------------------


@pytest.mark.parametrize("prefix", payment_contract.PROXY_PREFIXES)
def test_payment_gateway_proxies_every_contract_prefix(monkeypatch, prefix):
    """All prefixes declared in the contract MUST be proxied to Java when
    ``PAYMENT_BACKEND=java``. Adding a contract prefix without updating
    ``PaymentGatewayService.should_proxy_to_java`` would silently break
    production traffic, so we fail loudly here."""

    monkeypatch.setenv("PAYMENT_BACKEND", "java")
    gateway = PaymentGatewayService()
    assert gateway.should_proxy_to_java(prefix + "/something") is True


def test_payment_gateway_only_proxies_contract_prefixes(monkeypatch):
    monkeypatch.setenv("PAYMENT_BACKEND", "java")
    gateway = PaymentGatewayService()
    assert gateway.should_proxy_to_java("/api/market/catalog") is False
    assert gateway.should_proxy_to_java("/api/auth/login") is False


def test_payment_gateway_default_python_does_not_proxy(monkeypatch):
    monkeypatch.delenv("PAYMENT_BACKEND", raising=False)
    gateway = PaymentGatewayService()
    for prefix in payment_contract.PROXY_PREFIXES:
        assert gateway.should_proxy_to_java(prefix + "/anything") is False


# ---- Sign canonical form pinning -----------------------------------------


def _sign_dto(**overrides):
    from modstore_server.payment_api import CheckoutDTO

    base = dict(
        plan_id="",
        item_id=0,
        total_amount=0,
        subject="",
        wallet_recharge=False,
        request_id="req-1",
        timestamp=1710000000,
        signature="-",
    )
    base.update(overrides)
    return CheckoutDTO(**base)


def test_canonical_sign_data_keys_match_contract():
    from modstore_server.payment_api import canonical_checkout_sign_data

    canonical = canonical_checkout_sign_data(_sign_dto(plan_id="plan_basic"))
    assert tuple(sorted(canonical.keys())) == payment_contract.SIGN_FIELDS


def test_canonical_sign_data_string_normalisation_matches_java():
    """The string form must equal what
    ``com.modstore.service.SecurityService.canonicalCheckoutData`` builds:

    - ``item_id``: ``str(int(item_id))``
    - ``plan_id`` / ``subject``: ``.strip()``
    - ``timestamp``: ``str(int(timestamp))``
    - ``total_amount``: integer when whole, else trim trailing zeros
    - ``wallet_recharge``: ``"true"`` / ``"false"``
    """

    from modstore_server.payment_api import canonical_checkout_sign_data

    canonical = canonical_checkout_sign_data(
        _sign_dto(
            plan_id="  plan_basic  ",
            item_id=0,
            total_amount=9.9,
            subject="  基础版  ",
            wallet_recharge=False,
        )
    )

    assert canonical == {
        "item_id": "0",
        "plan_id": "plan_basic",
        "request_id": "req-1",
        "subject": "基础版",
        "timestamp": "1710000000",
        "total_amount": "9.9",
        "wallet_recharge": "false",
    }


@pytest.mark.parametrize(
    "amount, expected",
    [
        (0, "0"),
        (0.0, "0"),
        (9, "9"),
        (9.0, "9"),
        (9.9, "9.9"),
        (9.99, "9.99"),
        (0.10, "0.1"),
        (10.000001, "10.000001"),
        (None, "0"),
    ],
)
def test_amount_sign_str_matches_contract(amount, expected):
    from modstore_server.payment_common import _amount_sign_str

    assert _amount_sign_str(amount) == expected


def test_replay_window_matches_contract():
    from modstore_server import payment_api

    assert payment_api.REPLAY_WINDOW == payment_contract.REPLAY_WINDOW_SECONDS


def test_notify_idempotency_ttl_matches_java_security_service():
    """Java ``SecurityService.NOTIFY_IDEMPOTENCY_SECONDS`` must stay aligned."""
    assert payment_contract.NOTIFY_IDEMPOTENCY_SECONDS == 86_400


# ---- Event contract pinning ----------------------------------------------


def test_event_registry_contains_canonical_set():
    """Removing or downgrading any of these events would silently break Java,
    Python or business webhook consumers."""

    expected = {
        PAYMENT_PAID,
        WALLET_BALANCE_CHANGED,
        REFUND_APPROVED,
        REFUND_REJECTED,
        REFUND_FAILED,
    }
    assert expected.issubset(EVENT_CONTRACTS.keys())
    for name in expected:
        assert EVENT_CONTRACTS[name].version == 1


def test_payment_paid_payload_required_fields_match_contract():
    assert (
        tuple(EVENT_CONTRACTS[PAYMENT_PAID].required_payload)
        == payment_contract.PAYMENT_PAID_PAYLOAD_FIELDS
    )


def test_webhook_payment_payload_contains_all_required_fields():
    """``webhook_api._payment_payload`` is what the admin replay endpoint
    publishes for ``payment.paid``. It MUST cover every required key."""

    from modstore_server.webhook_api import _payment_payload

    payload = _payment_payload(
        {
            "out_trade_no": "MOD1",
            "trade_no": "T1",
            "buyer_id": "B1",
            "user_id": 7,
            "subject": "基础版",
            "total_amount": "9.90",
            "order_kind": "plan",
            "item_id": 0,
            "plan_id": "plan_basic",
            "paid_at": "2026-01-01T00:00:00Z",
        }
    )

    for required in payment_contract.PAYMENT_PAID_PAYLOAD_FIELDS:
        assert required in payload, f"payment.paid payload missing required field: {required}"


def test_refund_payload_contains_all_required_fields():
    from types import SimpleNamespace

    from modstore_server.webhook_api import _refund_payload

    refund = SimpleNamespace(
        id=1,
        user_id=7,
        order_no="MOD1",
        amount=9.9,
        reason="x",
        status="rejected",
        admin_note="",
        created_at=None,
        updated_at=None,
    )
    payload = _refund_payload(refund)
    for required in payment_contract.REFUND_PAYLOAD_FIELDS:
        assert required in payload, f"refund payload missing required field: {required}"


# ---- Frontend client pinning ----------------------------------------------


def test_frontend_api_client_uses_contract_paths():
    """The market frontend MUST keep using the contract paths verbatim. If any
    of them disappear from the frontend API modules the FastAPI/Java backends
    and frontend have drifted.

    Note: ``api.ts`` is now a re-export barrel; actual paths live in
    ``api/wallet.ts``, ``api/legacyMonolith.ts``, and
    ``application/paymentApi.ts``.  We search across all three.
    """
    api_dir = REPO_ROOT / "market" / "src" / "api"
    app_dir = REPO_ROOT / "market" / "src" / "application"
    combined = ""
    for ts_file in [
        api_dir / "wallet.ts",
        api_dir / "legacyMonolith.ts",
        app_dir / "paymentApi.ts",
    ]:
        if ts_file.is_file():
            combined += ts_file.read_text(encoding="utf-8")
    for path in payment_contract.FRONTEND_PAYMENT_PATHS:
        assert path in combined, (
            f"None of market/src/api/wallet.ts, api/legacyMonolith.ts, "
            f"or application/paymentApi.ts references {path!r}"
        )


def test_frontend_payment_api_module_uses_contract_paths():
    payment_api_ts = (REPO_ROOT / "market" / "src" / "application" / "paymentApi.ts").read_text(
        encoding="utf-8"
    )

    for must_exist in (
        "/api/payment/plans",
        "/api/payment/query/",
        "/api/payment/entitlements",
        "/api/wallet/balance",
        "/api/wallet/transactions",
    ):
        assert must_exist in payment_api_ts


# ---- Java side static checks ---------------------------------------------


def test_java_security_service_canonical_keys_match_contract():
    """We cannot run the Java service from pytest, but we statically assert
    that ``SecurityService.canonicalCheckoutData`` references the exact same
    canonical field names. Any reorder or rename will break HMAC parity."""

    java_path = (
        REPO_ROOT
        / "java_payment_service"
        / "src"
        / "main"
        / "java"
        / "com"
        / "modstore"
        / "service"
        / "SecurityService.java"
    )
    if not java_path.is_file():
        pytest.skip("java_payment_service is not present in this checkout")

    text = java_path.read_text(encoding="utf-8")
    for field in payment_contract.SIGN_FIELDS:
        assert (
            f'"{field}"' in text
        ), f"SecurityService.canonicalCheckoutData no longer references {field!r}"


def test_java_event_contracts_mirror_python():
    java_path = (
        REPO_ROOT
        / "java_payment_service"
        / "src"
        / "main"
        / "java"
        / "com"
        / "modstore"
        / "event"
        / "EventContracts.java"
    )
    if not java_path.is_file():
        pytest.skip("java_payment_service is not present in this checkout")

    text = java_path.read_text(encoding="utf-8")
    for event_name in (
        PAYMENT_PAID,
        WALLET_BALANCE_CHANGED,
        REFUND_APPROVED,
        REFUND_REJECTED,
        REFUND_FAILED,
    ):
        assert (
            f'"{event_name}"' in text
        ), f"EventContracts.java is missing event constant {event_name!r}"


# ---- Endpoint registry presence ------------------------------------------


def _all_routes(app) -> set[tuple[str, str]]:
    """Return (METHOD, /path) pairs from the live FastAPI app.

    Uses app.openapi() which is version-independent (Starlette 0.x and 1.x).
    Falls back to recursive route traversal for apps without an OpenAPI schema.
    """
    routes: set[tuple[str, str]] = set()
    try:
        schema = app.openapi()
        for path, methods_dict in schema.get("paths", {}).items():
            for method in methods_dict:
                if method.upper() in {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}:
                    routes.add((method.upper(), path))
        return routes
    except Exception:
        pass
    # Fallback: recursive traversal (handles _IncludedRouter in Starlette 1.x)
    from fastapi.routing import APIRoute

    def collect(obj: object) -> None:
        for route in getattr(obj, "routes", []):
            if isinstance(route, APIRoute):
                for method in route.methods or []:
                    routes.add((method.upper(), route.path))
            elif hasattr(route, "routes"):
                collect(route)

    collect(app)
    return routes


@pytest.mark.parametrize(
    "method, path, _auth, _admin",
    payment_contract.PAYMENT_ENDPOINTS
    + payment_contract.REFUND_ENDPOINTS
    + payment_contract.WEBHOOK_ENDPOINTS,
)
def test_fastapi_app_exposes_contract_endpoint(method, path, _auth, _admin):
    """Each contract endpoint must still be mounted on the FastAPI app."""

    pytest.importorskip("fastapi")
    from modstore_server.app import app

    assert (method, path) in _all_routes(
        app
    ), f"FastAPI app no longer exposes {method} {path}; the contract is broken"
