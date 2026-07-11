"""本地 MODstore（:8788）统一客户端 — 日更邮件 / 员工大会 / Vibe / 派发 不再代理远端服务器。"""

from __future__ import annotations

import logging
import os
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)


def _is_private_service_url(value: str) -> bool:
    """Return whether an internal credential may safely be sent to ``value``."""

    try:
        parsed = urlsplit(str(value or "").strip())
        hostname = str(parsed.hostname or "").strip().lower()
        if parsed.scheme not in {"http", "https"} or not hostname:
            return False
        if parsed.username is not None or parsed.password is not None:
            return False
        if hostname == "localhost":
            return True
        address = ip_address(hostname)
        return bool(address.is_loopback or address.is_private)
    except ValueError:
        # A public or unresolved DNS name is not a safe destination for a
        # machine credential.  Operators must configure a literal private IP
        # (or localhost) for management/internal traffic.
        return False


def _async_client(*, timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, trust_env=False)


def modstore_base_url() -> str:
    return (
        (
            os.environ.get("MODSTORE_LOCAL_BASE_URL")
            or os.environ.get("MODSTORE_DIGEST_BASE_URL")
            or os.environ.get("MODSTORE_ALL_HANDS_BASE_URL")
            or os.environ.get("XCAGI_MARKET_BASE_URL")
            or "http://127.0.0.1:8788"
        )
        .strip()
        .rstrip("/")
    )


def modstore_digest_base_url() -> str:
    """日更 digest / action-items / artifacts — 默认 :8788，勿与轻量 MODstore :8765 混用。"""
    return (
        (
            os.environ.get("MODSTORE_DIGEST_BASE_URL")
            or os.environ.get("MODSTORE_LOCAL_BASE_URL")
            or "http://127.0.0.1:8788"
        )
        .strip()
        .rstrip("/")
    )


def modstore_management_base_url() -> str:
    """Authoritative local ledger for the platform owner's management employees.

    Do not inherit ``XCAGI_MARKET_BASE_URL``/digest URLs here: packaged desktop
    environments often point those at the public market, while this ledger and
    its scheduler deliberately live on the local daily runtime.
    """

    base = (
        (os.environ.get("MODSTORE_MANAGEMENT_WORK_BASE_URL") or "http://127.0.0.1:8788")
        .strip()
        .rstrip("/")
    )
    if not _is_private_service_url(base):
        raise RuntimeError(
            "MODSTORE_MANAGEMENT_WORK_BASE_URL must use localhost or a private IP address"
        )
    return base


def internal_api_key() -> str:
    from app.security.local_runtime_secret import local_runtime_secret

    return local_runtime_secret(
        "MODSTORE_INTERNAL_API_KEY",
        "XCAGI_MARKET_INTERNAL_API_KEY",
    )


def internal_auth_headers() -> dict[str, str]:
    key = internal_api_key()
    return {"X-Internal-Api-Key": key} if key else {}


def prefer_local_modstore() -> bool:
    """本地自动化默认开启；设 MODSTORE_LOCAL_AUTOMATION=0 可强制走远端代理。"""
    raw = os.environ.get("MODSTORE_LOCAL_AUTOMATION", "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    base = modstore_base_url()
    return "127.0.0.1" in base or "localhost" in base


async def local_modstore_admin_login(client: httpx.AsyncClient, base: str) -> tuple[str, str]:
    login = await client.post(
        f"{base}/api/auth/login",
        json={
            "username": os.environ.get("MODSTORE_DIGEST_ADMIN_USER", "admin"),
            "password": os.environ.get("MODSTORE_DIGEST_ADMIN_PASSWORD", "admin123"),
        },
    )
    login.raise_for_status()
    body = login.json()
    token = str(body.get("access_token") or body.get("token") or "").strip()
    if not token:
        raise RuntimeError("MODstore login missing access_token")
    csrf = login.headers.get("x-csrf-token") or login.headers.get("X-CSRF-Token") or ""
    if not csrf:
        csrf_resp = await client.get(f"{base}/api/auth/csrf")
        if csrf_resp.is_success:
            csrf_body = csrf_resp.json()
            csrf = str(csrf_body.get("csrf_token") or csrf_body.get("token") or "").strip()
    return token, str(csrf or "")


async def auth_headers(
    client: httpx.AsyncClient,
    base: str,
    authorization: str | None,
) -> dict[str, str]:
    headers: dict[str, str] = {}
    if authorization:
        headers["Authorization"] = authorization
        csrf_resp = await client.get(f"{base}/api/auth/csrf", headers=headers)
        if csrf_resp.is_success:
            csrf_body = csrf_resp.json()
            csrf = str(csrf_body.get("csrf_token") or csrf_body.get("token") or "").strip()
            if csrf:
                headers["X-CSRF-Token"] = csrf
        return headers
    token, csrf = await local_modstore_admin_login(client, base)
    headers["Authorization"] = f"Bearer {token}"
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return headers


async def modstore_get(
    path: str,
    *,
    authorization: str | None = None,
    timeout: float = 60.0,
    query: str = "",
    base_url: str | None = None,
    strict_internal_auth: bool = False,
) -> dict[str, Any]:
    base = (base_url or modstore_base_url()).strip().rstrip("/")
    url = f"{base}{path}"
    if query:
        url = f"{url}?{query.lstrip('?')}"
    async with _async_client(timeout=timeout) as client:
        if strict_internal_auth and authorization:
            raise RuntimeError("strict internal MODstore calls do not accept user authorization")
        private_destination = _is_private_service_url(base)
        if strict_internal_auth and not private_destination:
            raise RuntimeError("refusing to send MODstore internal credentials to a public URL")
        internal_headers = (
            internal_auth_headers() if not authorization and private_destination else {}
        )
        if strict_internal_auth and not internal_headers:
            raise RuntimeError("MODstore internal API key is not configured")
        if internal_headers:
            resp = await client.get(url, headers=internal_headers)
            if strict_internal_auth or resp.status_code not in (401, 403):
                resp.raise_for_status()
                data = resp.json()
                return data if isinstance(data, dict) else {"success": True, "data": data}
        if strict_internal_auth:
            raise RuntimeError("MODstore strict internal request failed")
        headers = await auth_headers(client, base, authorization)
        resp = await client.get(url, headers=headers)
        if resp.status_code == 401 and prefer_local_modstore() and authorization:
            headers = await auth_headers(client, base, None)
            resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {"success": True, "data": data}


async def modstore_post(
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    authorization: str | None = None,
    timeout: float = 120.0,
    base_url: str | None = None,
    strict_internal_auth: bool = False,
) -> dict[str, Any]:
    base = (base_url or modstore_base_url()).strip().rstrip("/")
    payload = dict(json_body) if isinstance(json_body, dict) else {}
    async with _async_client(timeout=timeout) as client:
        if strict_internal_auth and authorization:
            raise RuntimeError("strict internal MODstore calls do not accept user authorization")
        private_destination = _is_private_service_url(base)
        if strict_internal_auth and not private_destination:
            raise RuntimeError("refusing to send MODstore internal credentials to a public URL")
        internal_headers = (
            internal_auth_headers() if not authorization and private_destination else {}
        )
        if strict_internal_auth and not internal_headers:
            raise RuntimeError("MODstore internal API key is not configured")
        if internal_headers:
            resp = await client.post(f"{base}{path}", headers=internal_headers, json=payload)
            if strict_internal_auth or resp.status_code not in (401, 403):
                resp.raise_for_status()
                data = resp.json()
                return data if isinstance(data, dict) else {"success": True, "data": data}
        if strict_internal_auth:
            raise RuntimeError("MODstore strict internal request failed")
        headers = await auth_headers(client, base, authorization)
        resp = await client.post(f"{base}{path}", headers=headers, json=payload)
        if resp.status_code == 401 and prefer_local_modstore() and authorization:
            headers = await auth_headers(client, base, None)
            resp = await client.post(f"{base}{path}", headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {"success": True, "data": data}
