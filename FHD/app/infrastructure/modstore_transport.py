"""Network transport policy for synchronous MODstore streaming calls."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import httpx


def safe_route_metadata(payload: Any) -> dict[str, str | int]:
    """Copy only public route identity, never credentials or credential hints."""
    if not isinstance(payload, dict):
        return {}
    nested = payload.get("route_metadata")
    source = nested if isinstance(nested, dict) else payload
    return {
        field: source[field]
        for field in ("provider", "model", "route_source", "key_source", "config_revision")
        if isinstance(source.get(field), (str, int)) and not isinstance(source[field], bool)
    }


class MarketModelError(ValueError):
    """An explicit gateway failure, distinct from a successful empty completion."""

    code: str | None = None
    recovery: str | None = None

    def __init__(self, payload: dict[str, Any]):
        # Gateway/provider error text may contain credentials, URLs or request data.
        # Only the status is suitable for the durable, user-visible chat history.
        try:
            status = int(payload.get("status") or 502)
        except (TypeError, ValueError):
            status = 502
        self.status_code = status if 400 <= status <= 599 else 502
        super().__init__(
            {
                400: "模型服务未接受请求，请查看模型状态；平台模型配置请联系管理员核对。",
                401: "模型服务鉴权失败，请查看模型状态；平台模型授权请联系管理员核对。",
                402: "修茈市场模型余额不足，请在「模型支付」充值后重试。",
                403: "当前模型访问未获授权，请查看模型状态；平台模型权限请联系管理员核对。",
                404: "当前模型或模型服务入口不可用，请查看模型状态并联系管理员核对平台配置。",
                408: "模型服务响应超时，请检查连接后重试。",
                409: "本轮模型配置已失效或发生变化，请重新发送本次请求。",
                429: "模型服务请求受限，请稍后重试并检查可用额度。",
                503: "模型服务暂不可用，请查看模型状态后重试。",
                504: "模型服务响应超时，请检查连接后重试。",
            }.get(self.status_code, "模型服务请求失败，请查看模型状态后重试。")
        )


def market_connect_timeout() -> float:
    """Allow slow desktop TUN/TLS handshakes while remaining configurable."""
    try:
        return max(5.0, float(os.environ.get("XCAGI_MARKET_CONNECT_TIMEOUT", "20")))
    except ValueError:
        return 20.0


def market_connect_attempts() -> int:
    try:
        return max(1, min(int(os.environ.get("XCAGI_MARKET_CONNECT_ATTEMPTS", "3")), 6))
    except ValueError:
        return 3


def market_fallback_proxy() -> str | None:
    """Return the optional local proxy used after direct connection failures."""
    raw = (os.environ.get("XCAGI_MARKET_FALLBACK_PROXY") or "").strip()
    return raw or None


MARKET_TRANSPORT_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.RemoteProtocolError,
)


def iter_market_transport_plans() -> Iterator[tuple[str | None, int, int]]:
    """Yield direct and fallback-proxy attempts for flaky desktop TUN/TLS."""
    attempts = market_connect_attempts()
    proxies: list[str | None] = [None]
    fallback = market_fallback_proxy()
    if fallback:
        proxies.append(fallback)
    for proxy in proxies:
        for attempt in range(1, attempts + 1):
            yield proxy, attempt, attempts


def httpx_sync_client(**kwargs: Any) -> httpx.Client:
    """Ignore inherited proxies; an explicit fallback proxy remains supported."""
    kwargs.setdefault("trust_env", False)
    proxy = kwargs.pop("proxy", None)
    if proxy:
        kwargs["proxy"] = proxy
    return httpx.Client(**kwargs)


class MarketSSEDecoder:
    """Decode market data lines while tracking event boundaries and final content."""

    def __init__(self, payload_has_content: Callable[[str], bool], *, accept_raw: bool = True):
        self.payload_has_content = payload_has_content
        self.accept_raw = accept_raw
        self.current_event = ""
        self.saw_delta_content = False
        self.done = False

    def feed(self, line: str) -> str | None:
        line_text = (line or "").strip()
        if not line_text:
            self.current_event = ""
            return None
        if line_text.startswith("event:"):
            self.current_event = line_text[6:].strip().lower()
            return None
        if line_text.startswith("data:"):
            line_text = line_text[5:].strip()
        elif line_text.startswith((":", "id:", "retry:")) or not self.accept_raw:
            return None
        if line_text == "[DONE]":
            self.done = True
            return None
        if self.current_event == "error":
            # The gateway puts the event kind in the SSE header, not body.type.
            try:
                error = json.loads(line_text)
            except json.JSONDecodeError:
                error = {"error": line_text}
            raise MarketModelError(error if isinstance(error, dict) else {"error": error})
        if self.current_event in {"meta", "done"}:
            self.done = self.current_event == "done"
            try:
                raw = json.loads(line_text)
            except json.JSONDecodeError:
                return None
            public: dict[str, Any] = {}
            if route := safe_route_metadata(raw):
                public["route_metadata"] = route
            if self.done and not self.saw_delta_content and isinstance(raw, dict):
                content = raw.get("content") or raw.get("text") or raw.get("delta") or ""
                if content:
                    public["delta"] = str(content)
            return json.dumps(public, ensure_ascii=False) if public else None
        if self.payload_has_content(line_text):
            self.saw_delta_content = True
        return line_text


def iter_market_sse_data_payloads(
    response: Any,
    *,
    payload_has_content: Callable[[str], bool],
) -> Iterator[str]:
    """Yield public route metadata and deltas, avoiding duplicate done content."""
    decoder = MarketSSEDecoder(payload_has_content)
    for line in response.iter_lines():
        data = decoder.feed(line)
        if data is not None:
            yield data
        if decoder.done:
            break


async def aiter_market_sse_data_payloads(
    response: httpx.Response,
    *,
    payload_has_content: Callable[[str], bool],
) -> AsyncIterator[str]:
    """Apply the same event and completion rules to an async HTTP response."""
    decoder = MarketSSEDecoder(payload_has_content, accept_raw=False)
    async for line in response.aiter_lines():
        data = decoder.feed(line)
        if data is not None:
            yield data
        if decoder.done:
            break
