"""Credential loading and SDK client construction for the Python Alipay fallback."""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)
_warned_notify_url = False


def env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def pem_from_env(name: str) -> str:
    raw = env(name)
    return raw.replace("\\n", "\n") if raw else ""


def read_file_from_env(name: str) -> str:
    path = env(name)
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as file_handle:
            return file_handle.read().strip()
    except OSError:
        logger.warning("无法读取 %s=%s", name, path)
        return ""


def default_bundled_alipay_public_key() -> str:
    path = Path(__file__).resolve().parent / "alipayPublicKey_RSA2.txt"
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        logger.warning("无法读取默认支付宝公钥文件: %s", path)
        return ""


def alipay_app_id() -> str:
    return env("ALIPAY_APP_ID") or env("ALIPAY_PID")


def app_private_key_pem() -> str:
    return pem_from_env("ALIPAY_APP_PRIVATE_KEY") or read_file_from_env(
        "ALIPAY_APP_PRIVATE_KEY_PATH"
    )


def alipay_public_key_pem() -> str:
    return (
        pem_from_env("ALIPAY_ALIPAY_PUBLIC_KEY")
        or read_file_from_env("ALIPAY_ALIPAY_PUBLIC_KEY_PATH")
        or default_bundled_alipay_public_key()
    )


def alipay_debug() -> bool:
    return env("ALIPAY_DEBUG").lower() in ("1", "true", "yes")


def notify_url_default() -> str | None:
    return env("ALIPAY_NOTIFY_URL") or None


def warn_notify_url_path_once() -> None:
    global _warned_notify_url
    if _warned_notify_url:
        return
    _warned_notify_url = True
    url = notify_url_default()
    if not url:
        return
    from urllib.parse import urlparse

    path = (urlparse(url).path or "").rstrip("/")
    expected = "/api/payment/notify/alipay"
    if path != expected:
        logger.warning(
            "ALIPAY_NOTIFY_URL 的 path 应为「%s」，当前为「%s」。",
            expected,
            urlparse(url).path or "/",
        )


def sdk_import_error() -> str | None:
    try:
        from alipay import AliPay  # noqa: F401
    except ImportError:
        return "未安装 python-alipay-sdk，请执行: pip install python-alipay-sdk"
    return None


def credentials_ready() -> bool:
    return bool(alipay_app_id() and app_private_key_pem() and alipay_public_key_pem())


def alipay_ui_ready() -> bool:
    return credentials_ready() and sdk_import_error() is None


def build_client():
    missing_sdk = sdk_import_error()
    if missing_sdk:
        raise RuntimeError(missing_sdk)
    if not credentials_ready():
        raise RuntimeError(
            "支付宝配置不完整：需要 ALIPAY_APP_ID、ALIPAY_APP_PRIVATE_KEY（或 ALIPAY_APP_PRIVATE_KEY_PATH）、"
            "以及 ALIPAY_ALIPAY_PUBLIC_KEY / ALIPAY_ALIPAY_PUBLIC_KEY_PATH"
        )
    from alipay import AliPay

    return AliPay(
        appid=alipay_app_id(),
        app_notify_url=notify_url_default(),
        app_private_key_string=app_private_key_pem(),
        alipay_public_key_string=alipay_public_key_pem(),
        sign_type="RSA2",
        debug=alipay_debug(),
    )
