"""httpx AsyncClient helpers — env proxy / SOCKS / TLS CA bundle."""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

_SSL_VERIFY_ENV_KEYS = ("XCAGI_MARKET_SSL_VERIFY", "XCAGI_HTTPX_SSL_VERIFY")

_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def _env_has_socks_proxy() -> bool:
    for key in _PROXY_ENV_KEYS:
        val = (os.environ.get(key) or "").strip().lower()
        if val.startswith("socks4://") or val.startswith("socks5://") or val.startswith("socks://"):
            return True
    return False


def _socksio_available() -> bool:
    try:
        import socksio  # noqa: F401

        return True
    except ImportError:
        return False


def _certifi_ca_bundle() -> str | None:
    try:
        import certifi

        path = certifi.where()
        return path if path and os.path.isfile(path) else None
    except ImportError:
        return None


def resolve_http_ssl_verify() -> bool | str:
    """TLS 校验：默认 certifi CA；可用环境变量关闭或指定 CA 文件（本地调试）。"""
    raw = ""
    for key in _SSL_VERIFY_ENV_KEYS:
        val = (os.environ.get(key) or "").strip()
        if val:
            raw = val
            break
    if raw:
        low = raw.lower()
        if low in ("0", "false", "no", "off"):
            logger.warning(
                "%s=0：已关闭对外 HTTPS 证书校验，仅用于本地调试，勿用于生产。",
                _SSL_VERIFY_ENV_KEYS[0],
            )
            return False
        if low in ("1", "true", "yes", "on"):
            bundle = _certifi_ca_bundle()
            return bundle if bundle is not None else True
        if os.path.isfile(raw):
            return raw
    bundle = _certifi_ca_bundle()
    return bundle if bundle is not None else True


def async_client_respecting_env_proxy(**kwargs: object) -> httpx.AsyncClient:
    """Honor HTTP(S)_PROXY / ALL_PROXY when possible; skip SOCKS if socksio is missing."""
    client_kwargs = dict(kwargs)
    if client_kwargs.get("verify") is None:
        client_kwargs["verify"] = resolve_http_ssl_verify()
    if _env_has_socks_proxy() and not _socksio_available():
        logger.warning(
            "环境变量配置了 SOCKS 代理但未安装 socksio，本次请求将不走系统代理。"
            "若需代理访问外网，请执行: pip install 'httpx[socks]'"
        )
        return httpx.AsyncClient(trust_env=False, **client_kwargs)  # type: ignore[arg-type]
    return httpx.AsyncClient(**client_kwargs)  # type: ignore[arg-type]
