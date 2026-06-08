"""Cross-service payment contract surface.

This module is the single source of truth that ``payment_api``, ``webhook_api``,
``refund_api``, ``application/payment_gateway`` and the Java payment service
must agree with. Changes here MUST be mirrored in:

- ``docs/PAYMENT_CONTRACT.md``
- ``modstore_server/payment_api.canonical_checkout_sign_data`` /
  ``modstore_server/payment_api._amount_sign_str``
- ``com.modstore.service.SecurityService.canonicalCheckoutData``
- ``com.modstore.event.EventContracts``
- ``MODstore_deploy/market/src/api.ts`` and
  ``MODstore_deploy/market/src/application/paymentApi.ts``

``tests/test_payment_contract.py`` enforces these invariants and will fail if
either side drifts.
"""

from __future__ import annotations

from typing import Final

from modstore_server.eventing.contracts import (
    EVENT_CONTRACTS,
    PAYMENT_PAID,
    REFUND_APPROVED,
    REFUND_FAILED,
    REFUND_REJECTED,
    WALLET_BALANCE_CHANGED,
)

PROXY_PREFIXES: Final[tuple[str, ...]] = (
    "/api/payment",
    "/api/wallet",
    "/api/refunds",
)
"""Path prefixes that ``PaymentGatewayService`` proxies to Java when
``PAYMENT_BACKEND=java``. Adding routes outside these prefixes will silently
bypass the Java backend in production."""


SIGN_FIELDS: Final[tuple[str, ...]] = (
    "item_id",
    "plan_id",
    "request_id",
    "subject",
    "timestamp",
    "total_amount",
    "wallet_recharge",
)
"""Canonical key set for ``/api/payment/sign-checkout`` HMAC. Order matches the
sorted form used by both Python and Java to build the signing string."""


REPLAY_WINDOW_SECONDS: Final[int] = 300
"""Replay protection time window. Must equal Python ``REPLAY_WINDOW`` and Java
``SecurityService.REPLAY_WINDOW_SECONDS``."""


NOTIFY_IDEMPOTENCY_SECONDS: Final[int] = 86_400
"""Alipay async notify idempotency lock TTL on the Java side."""


PAYMENT_PAID_PAYLOAD_FIELDS: Final[tuple[str, ...]] = tuple(
    EVENT_CONTRACTS[PAYMENT_PAID].required_payload
)
WALLET_BALANCE_CHANGED_PAYLOAD_FIELDS: Final[tuple[str, ...]] = tuple(
    EVENT_CONTRACTS[WALLET_BALANCE_CHANGED].required_payload
)
REFUND_PAYLOAD_FIELDS: Final[tuple[str, ...]] = tuple(
    EVENT_CONTRACTS[REFUND_APPROVED].required_payload
)


# ---- Endpoint registry ---------------------------------------------------
# Tuples of ``(method, path, requires_auth, requires_admin)``. Tests pin both
# the Python routers and the frontend client to this registry; Java
# controllers are validated by name in the docs and by integration tests.

PAYMENT_ENDPOINTS: Final[tuple[tuple[str, str, bool, bool], ...]] = (
    ("GET", "/api/payment/plans", False, False),
    ("GET", "/api/payment/my-plan", True, False),
    ("POST", "/api/payment/sign-checkout", True, False),
    ("POST", "/api/payment/checkout", True, False),
    ("POST", "/api/payment/notify/alipay", False, False),
    # GET 支持 ?reconcile=true：Java 对账，拉支付宝交易查询以补发 notify 未达时的权益
    ("GET", "/api/payment/query/{out_trade_no}", False, False),
    ("GET", "/api/payment/orders", True, False),
    ("POST", "/api/payment/cancel/{order_no}", True, False),
    ("GET", "/api/payment/diagnostics", True, True),
    ("GET", "/api/payment/entitlements", True, False),
    ("GET", "/api/payment/usage-metrics", True, False),
    ("POST", "/api/payment/refund", True, True),
)

REFUND_ENDPOINTS: Final[tuple[tuple[str, str, bool, bool], ...]] = (
    ("POST", "/api/refunds/apply", True, False),
    ("GET", "/api/refunds/my", True, False),
    ("GET", "/api/refunds/admin/pending", True, True),
    ("POST", "/api/refunds/admin/{refund_id}/review", True, True),
)

WEBHOOK_ENDPOINTS: Final[tuple[tuple[str, str, bool, bool], ...]] = (
    ("POST", "/api/webhooks/admin/replay", True, True),
)


# Frontend path snippets that the contract test will look for verbatim in
# ``market/src/api.ts`` and ``market/src/application/paymentApi.ts``.
FRONTEND_PAYMENT_PATHS: Final[tuple[str, ...]] = (
    "/api/payment/plans",
    "/api/payment/my-plan",
    "/api/payment/sign-checkout",
    "/api/payment/checkout",
    "/api/payment/query/",
    "/api/payment/orders",
    "/api/payment/cancel/",
    "/api/payment/diagnostics",
    "/api/payment/entitlements",
    "/api/wallet/balance",
    "/api/wallet/transactions",
    "/api/refunds/apply",
    "/api/refunds/my",
    "/api/refunds/admin/pending",
    "/api/refunds/admin/",
)


__all__ = [
    "PROXY_PREFIXES",
    "SIGN_FIELDS",
    "REPLAY_WINDOW_SECONDS",
    "NOTIFY_IDEMPOTENCY_SECONDS",
    "PAYMENT_PAID_PAYLOAD_FIELDS",
    "WALLET_BALANCE_CHANGED_PAYLOAD_FIELDS",
    "REFUND_PAYLOAD_FIELDS",
    "PAYMENT_ENDPOINTS",
    "REFUND_ENDPOINTS",
    "WEBHOOK_ENDPOINTS",
    "FRONTEND_PAYMENT_PATHS",
    "PAYMENT_PAID",
    "WALLET_BALANCE_CHANGED",
    "REFUND_APPROVED",
    "REFUND_REJECTED",
    "REFUND_FAILED",
]
