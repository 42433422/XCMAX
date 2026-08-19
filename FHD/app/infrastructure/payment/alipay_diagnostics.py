"""Privacy-safe configuration diagnostics for the AliPay adapter."""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import urlparse


def private_key_source(
    *,
    pem_from_env: Callable[[str], str],
    env: Callable[[str], str],
    read_file_from_env: Callable[[str], str],
) -> str:
    if pem_from_env("ALIPAY_APP_PRIVATE_KEY"):
        return "env"
    if env("ALIPAY_APP_PRIVATE_KEY_PATH") and read_file_from_env("ALIPAY_APP_PRIVATE_KEY_PATH"):
        return "path"
    return "missing"


def public_key_source(
    *,
    pem_from_env: Callable[[str], str],
    env: Callable[[str], str],
    read_file_from_env: Callable[[str], str],
    bundled_public_key: Callable[[], str],
) -> str:
    if pem_from_env("ALIPAY_ALIPAY_PUBLIC_KEY"):
        return "env"
    if env("ALIPAY_ALIPAY_PUBLIC_KEY_PATH") and read_file_from_env(
        "ALIPAY_ALIPAY_PUBLIC_KEY_PATH"
    ):
        return "path"
    if bundled_public_key():
        return "bundled"
    return "missing"


def notify_url_path_ok(url: str | None) -> bool:
    if not url:
        return False
    return (urlparse(url).path or "").rstrip("/") == "/api/model-payment/notify/alipay"


def diagnostics_snapshot(
    *,
    ui_ready: Callable[[], bool],
    sdk_import_error: Callable[[], str | None],
    app_id: Callable[[], str],
    private_source: Callable[[], str],
    public_source: Callable[[], str],
    notify_url: Callable[[], str | None],
    debug_enabled: Callable[[], bool],
) -> dict[str, Any]:
    sdk_error = sdk_import_error()
    configured_notify_url = notify_url()
    return {
        "alipay_configured": ui_ready(),
        "sdk_installed": sdk_error is None,
        "sdk_import_error": sdk_error,
        "app_id_set": bool(app_id()),
        "private_key_source": private_source(),
        "public_key_source": public_source(),
        "notify_url": configured_notify_url,
        "notify_url_path_ok": notify_url_path_ok(configured_notify_url),
        "notify_url_path_expected": "/api/model-payment/notify/alipay",
        "debug_mode": debug_enabled(),
    }
