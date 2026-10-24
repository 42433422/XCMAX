"""Scheduler HTTP transport, credential caching, and best-effort task polling."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

import httpx

from .common import DEFAULT_PARA_API_URL
from .ports import JsonObject, ParaPorts
from .profiles import SuperEmployeeToolProfile


class ParaClient:
    def __init__(
        self,
        profile: SuperEmployeeToolProfile,
        ports: ParaPorts,
        decode: Callable[[httpx.Response], JsonObject],
        token_cache: dict[tuple[str, str], tuple[str, float]],
        token_ttl: Callable[[], float],
    ) -> None:
        self._p, self._ports, self._decode = profile, ports, decode
        self._token_cache, self._token_ttl = token_cache, token_ttl

    def default_http_client(self) -> httpx.Client:
        timeout = float(
            os.environ.get(f"{self._p.env_tool_prefix}_DISPATCH_TIMEOUT_SEC")
            or os.environ.get(f"{self._p.env_tool_prefix}_WEBHOOK_TIMEOUT_SEC")
            or "30"
        )
        return httpx.Client(timeout=timeout)

    def para_api_url(self) -> str:
        value = (
            (
                os.environ.get(f"{self._p.env_super_prefix}_PARA_API_URL")
                or os.environ.get("MODSTORE_PARA_API_URL")
                or os.environ.get("DEVFLEET_API_URL")
                or DEFAULT_PARA_API_URL
            )
            .strip()
            .rstrip("/")
        )
        if value.lower() in {"", "0", "false", "off", "none", "disabled"}:
            return ""
        return value

    def para_token(self, client: httpx.Client, api_url: str) -> str:
        token = (
            os.environ.get(f"{self._p.env_super_prefix}_PARA_TOKEN")
            or os.environ.get("MODSTORE_PARA_TOKEN")
            or os.environ.get("DEVFLEET_TOKEN")
            or ""
        ).strip()
        if token:
            return token
        cache_key = (api_url, self._p.env_super_prefix)
        cached = self._token_cache.get(cache_key)
        if cached and cached[1] > time.time():
            return cached[0]
        resp = client.post(f"{api_url}/api/auth/guest", json={})
        body = self._decode(resp)
        if resp.status_code >= 400:
            self._token_cache.pop(cache_key, None)
            raise RuntimeError(
                self.error_message(body, f"Para guest 登录失败 ({resp.status_code})")
            )
        token = str(body.get("token") or body.get("access_token") or "").strip()
        if not token:
            self._token_cache.pop(cache_key, None)
            raise RuntimeError("Para guest 登录未返回 token")
        self._token_cache[cache_key] = (
            token,
            time.time() + self._token_ttl(),
        )
        return token

    def para_request(
        self,
        client: httpx.Client,
        api_url: str,
        token: str,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resp = client.request(
            method,
            f"{api_url}{path}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=json_body,
        )
        body = self._decode(resp)
        if resp.status_code >= 400:
            raise RuntimeError(self.error_message(body, f"Para API 请求失败 ({resp.status_code})"))
        return body

    def json_response(self, resp: httpx.Response) -> dict[str, Any]:
        try:
            body = resp.json() if resp.content else {}
        except ValueError:
            body = {"raw": resp.text[:1000]}
        return body if isinstance(body, dict) else {"data": body}

    def error_message(self, body: dict[str, Any], fallback: str) -> str:
        return str(body.get("error") or body.get("message") or fallback)[:500]

    def fetch_para_task(self, task_id: str) -> dict[str, Any] | None:
        api_url = self._ports.api_url()
        if not api_url or not task_id:
            return None
        try:
            with self._ports.client() as client:
                token = self._ports.token(client, api_url)
                body = self._ports.request(client, api_url, token, "GET", f"/api/tasks/{task_id}")
            task = body.get("task") if isinstance(body, dict) else None
            return task if isinstance(task, dict) else None
        except (httpx.HTTPError, RuntimeError, ValueError, KeyError, TypeError):
            return None
