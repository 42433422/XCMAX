"""Synchronous ASGI transport with policy checks and bounded client ownership."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from typing import Any

from starlette.types import ASGIApp

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .protocols import InternalHttpClient
from .route_policy import canonical_api_target


class InternalApiGateway:
    def __init__(
        self,
        client: Callable[[ASGIApp], InternalHttpClient],
        allowed: Callable[[str], bool],
        methods: Callable[[], frozenset[str]],
    ) -> None:
        self._client = client
        self._allowed = allowed
        self._methods = methods

    def call(self, app: ASGIApp, args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("path") or "").strip()
        method = str(args.get("method") or "GET").upper()
        body = args.get("body") if isinstance(args.get("body"), dict) else {}
        if not raw_path:
            return {"success": False, "message": "path 不能为空"}
        if method not in self._methods():
            return {
                "success": False,
                "message": f"不支持的 method：{method}",
                "code": "METHOD_NOT_ALLOWED",
            }
        target = canonical_api_target(raw_path)
        if target is None or not self._allowed(target.request_url):
            denied_path = target.policy_path if target else raw_path
            return {
                "success": False,
                "message": f"路由 {denied_path} 未在 AIOPEN 白名单启用",
                "code": "ROUTE_NOT_WHITELISTED",
            }
        try:
            # Closing does not start/stop the host ASGI app's lifespan.
            with closing(self._client(app)) as client:
                headers: dict[str, str] = {"X-AIOPEN-Internal": "1"}
                if method in {"POST", "PUT", "PATCH", "DELETE"}:
                    try:
                        client.get("/api/aiopen/manifest")
                    except RECOVERABLE_ERRORS:
                        pass
                    csrf = client.cookies.get("csrf_token")
                    if csrf:
                        headers["X-CSRF-Token"] = str(csrf)
                if method == "GET":
                    response = client.get(target.request_url, headers=headers)
                elif method == "DELETE":
                    response = client.delete(target.request_url, headers=headers)
                else:
                    payload = dict(body or {})
                    payload.setdefault("source", "aiopen")
                    response = client.request(
                        method, target.request_url, json=payload, headers=headers
                    )
                try:
                    data = response.json()
                except (ValueError, TypeError):
                    data = {"raw": response.text[:2000]}
                try:
                    status = int(response.status_code)
                except (TypeError, ValueError):
                    status = 599
                # 4xx (including 499) remain a completed API call in this contract.
                return {
                    "success": status < 500,
                    "path": raw_path,
                    "method": method,
                    "status_code": status,
                    "data": data,
                }
        except RECOVERABLE_ERRORS:
            return {"success": False, "path": raw_path, "method": method, "message": "请求执行失败"}
