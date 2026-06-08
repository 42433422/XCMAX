"""本地 MODstore（:8788）统一客户端 — 日更邮件 / 员工大会 / Vibe / 派发 不再代理远端服务器。"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


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
) -> dict[str, Any]:
    base = (base_url or modstore_base_url()).strip().rstrip("/")
    url = f"{base}{path}"
    if query:
        url = f"{url}?{query.lstrip('?')}"
    async with _async_client(timeout=timeout) as client:
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
) -> dict[str, Any]:
    base = (base_url or modstore_base_url()).strip().rstrip("/")
    payload = dict(json_body) if isinstance(json_body, dict) else {}
    async with _async_client(timeout=timeout) as client:
        headers = await auth_headers(client, base, authorization)
        resp = await client.post(f"{base}{path}", headers=headers, json=payload)
        if resp.status_code == 401 and prefer_local_modstore() and authorization:
            headers = await auth_headers(client, base, None)
            resp = await client.post(f"{base}{path}", headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {"success": True, "data": data}
