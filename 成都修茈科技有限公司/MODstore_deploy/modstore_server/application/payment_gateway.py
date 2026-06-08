"""Payment gateway use case boundary."""

from __future__ import annotations

import os

from modstore_server.payment_contract import PROXY_PREFIXES


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0.1, float(raw))
    except ValueError:
        return default


class PaymentGatewayService:
    def __init__(self, backend: str | None = None, java_url: str | None = None):
        self.backend = (backend or os.environ.get("PAYMENT_BACKEND") or "python").strip().lower()
        self.java_url = (
            (java_url or os.environ.get("JAVA_PAYMENT_SERVICE_URL") or "http://127.0.0.1:8080")
            .strip()
            .rstrip("/")
        )
        self.connect_timeout_seconds = _float_env("PAYMENT_PROXY_CONNECT_TIMEOUT_SECONDS", 5.0)
        self.read_timeout_seconds = _float_env("PAYMENT_PROXY_READ_TIMEOUT_SECONDS", 30.0)

    def should_proxy_to_java(self, path: str) -> bool:
        if self.backend != "java":
            return False
        return any(path.startswith(prefix) for prefix in PROXY_PREFIXES)

    def target_base_url(self) -> str:
        return self.java_url


def java_payment_unreachable_message(exc: BaseException) -> str:
    """502 等场景下带回 ``JAVA_PAYMENT_SERVICE_URL`` 实际解析值，便于排障（本机连不上 8080 时最常见）。"""
    base = PaymentGatewayService().target_base_url()
    return f"Java 支付服务不可用: {exc} (JAVA_PAYMENT_SERVICE_URL={base})"
