"""Network transport policy for synchronous MODstore streaming calls."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import httpx


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
        if self.current_event == "meta":
            return None
        if self.current_event == "done":
            self.done = True
            if not self.saw_delta_content:
                try:
                    raw = json.loads(line_text)
                except json.JSONDecodeError:
                    raw = None
                if isinstance(raw, dict):
                    content = raw.get("content") or raw.get("text") or raw.get("delta") or ""
                    if content:
                        return json.dumps({"delta": str(content)}, ensure_ascii=False)
            return None
        if self.payload_has_content(line_text):
            self.saw_delta_content = True
        return line_text


def iter_market_sse_data_payloads(
    response: Any,
    *,
    payload_has_content: Callable[[str], bool],
) -> Iterator[str]:
    """Yield data payloads, ignoring meta and avoiding duplicate done content."""
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
