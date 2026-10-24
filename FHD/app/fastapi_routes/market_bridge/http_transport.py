"""Market HTTP transport, CSRF negotiation and stable error envelopes."""

import json
import re
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from logging import Logger
from typing import Any

import httpx
from fastapi.responses import JSONResponse

from app.utils.operational_errors import RECOVERABLE_ERRORS


def _auth_header(raw: str) -> str:
    token = (raw or "").strip()
    if token.lower().startswith("authorization:"):
        token = token.split(":", 1)[1].strip()
    if token and not token.lower().startswith("bearer "):
        token = f"Bearer {token}"
    return token


def _normalize_bearer_token(raw: str) -> str:
    token = (raw or "").strip()
    return token[7:].strip() if token.lower().startswith("bearer ") else token


def _proxy_error_http_status(payload: Any) -> int | None:
    if not isinstance(payload, dict) or not payload.get("__proxy_error__"):
        return None
    value = payload.get("status_code")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _body_snippet(payload: Any, limit: int = 240) -> str:
    if isinstance(payload, dict):
        try:
            text = json.dumps(payload, ensure_ascii=False)
        except RECOVERABLE_ERRORS:
            text = str(payload)
    else:
        text = str(payload or "")
    text = text.replace("\n", " ").strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def error_message(payload: Any, status_code: int, *, base_url: str) -> str:
    if status_code == 429:
        return "市场服务请求过于频繁，请稍后再试"
    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("message") or payload.get("error")
        if isinstance(detail, list):
            message = "; ".join(str(x.get("msg") if isinstance(x, dict) else x) for x in detail)
        else:
            message = str(detail) if detail else ""
        if status_code >= 500:
            hint = f"请检查 XCAGI_MARKET_BASE_URL={base_url}"
            if message and not re.match("^internal server error$", message, re.I):
                return f"市场服务返回 {status_code}：{message}。{hint}"
            return f"市场服务返回 {status_code}（服务器内部错误）。{hint}"
        if message:
            return message
    if status_code >= 500:
        return (
            f"市场服务返回 {status_code}（服务器内部错误）。请检查 XCAGI_MARKET_BASE_URL={base_url}"
        )
    return f"HTTP {status_code}"


def transport_error(exc: Exception, *, base_url: str) -> tuple[str, int]:
    label = str(exc).strip() or type(exc).__name__
    if isinstance(exc, httpx.ReadTimeout):
        return (
            f"连接修茈市场超时（{label}）。请检查网络或增大 XCAGI_MARKET_HTTP_TIMEOUT；当前 XCAGI_MARKET_BASE_URL={base_url}",
            503,
        )
    return (
        f"无法连接修茈市场服务器：{label}。请确认 XCAGI_MARKET_BASE_URL={base_url} 可达，且 FHD 后端已启动。",
        502,
    )


@dataclass
class MarketHTTP:
    client: Callable[[float], AbstractAsyncContextManager[httpx.AsyncClient]]
    api_base_url: Callable[[], str]
    base_url: Callable[[], str]
    auth_header: Callable[[str], str]
    timeout: Callable[[], float]
    attempts: Callable[[], int]
    error_message: Callable[[Any, int], str]
    transport_error: Callable[[Exception], tuple[str, int]]
    body_snippet: Callable[[Any], str]
    logger: Logger

    def unavailable(self, exc: Exception) -> JSONResponse:
        message, status = self.transport_error(exc)
        return JSONResponse(
            {
                "success": False,
                "message": message,
                "error": {"code": "MARKET_AUTH_UNAVAILABLE", "message": message},
                "data": {"market_base_url": self.base_url()},
            },
            status_code=status,
        )

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        authorization: str = "",
        extra_headers: dict[str, str] | None = None,
        return_error_payload: bool = False,
        sensitive: bool = False,
        timeout: float | None = None,
        retries: int | None = None,
    ) -> Any:
        api_base = self.api_base_url()
        url = f"{api_base}{path}"
        headers = {"Accept": "application/json"}
        if authorization:
            headers["Authorization"] = self.auth_header(authorization)
        for key, value in (extra_headers or {}).items():
            if key and value:
                headers[str(key)] = str(value)
        timeout = self.timeout() if timeout is None else float(timeout)
        # This public legacy argument is the complete attempt budget. In
        # particular, preserve the existing budget for mutating requests.
        attempts = self.attempts() if retries is None else max(0, int(retries))
        mutating = str(method).upper() in {"POST", "PUT", "PATCH", "DELETE"}
        for attempt in range(attempts):
            try:
                async with self.client(timeout) as client:
                    request_headers = dict(headers)
                    if mutating:
                        try:
                            await client.get(f"{api_base}/api/csrf")
                            csrf = client.cookies.get("csrf_token")
                            if csrf:
                                request_headers["X-CSRF-Token"] = csrf
                        except httpx.HTTPError:
                            pass
                    response = await client.request(
                        method, url, json=json_body, headers=request_headers
                    )
                break
            except httpx.HTTPError as exc:
                if attempt + 1 >= attempts:
                    return self.unavailable(exc)
            except RECOVERABLE_ERRORS as exc:
                if sensitive:
                    self.logger.warning("market authentication transport unavailable")
                else:
                    self.logger.warning("_proxy_json transport error to %s: %s", url, exc)
                return self.unavailable(exc)
        else:
            return JSONResponse({"success": False, "message": "市场请求失败"}, status_code=502)
        try:
            payload = response.json()
        except ValueError:
            payload = {"detail": response.text}
        if response.status_code >= 400:
            if response.status_code >= 500:
                if sensitive:
                    self.logger.warning(
                        "market authentication request failed status=%s", response.status_code
                    )
                else:
                    self.logger.warning(
                        "market proxy %s %s -> %s body=%s",
                        method,
                        url,
                        response.status_code,
                        self.body_snippet(payload),
                    )
            if return_error_payload:
                return {
                    "__proxy_error__": True,
                    "status_code": response.status_code,
                    "payload": payload,
                }
            return JSONResponse(
                {
                    "success": False,
                    "message": str(self.error_message(payload, response.status_code)),
                    "data": {
                        **(payload if isinstance(payload, dict) else {}),
                        "market_base_url": self.base_url(),
                    },
                },
                status_code=response.status_code,
            )
        return payload
