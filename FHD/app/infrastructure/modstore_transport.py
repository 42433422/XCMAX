"""Network transport policy for synchronous MODstore streaming calls."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
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


def iter_market_sse_data_payloads(
    response: Any,
    *,
    payload_has_content: Callable[[str], bool],
) -> Iterator[str]:
    """Yield data payloads, ignoring meta and avoiding duplicate done content."""
    current_event = ""
    saw_delta_content = False
    for line in response.iter_lines():
        line_text = (line or "").strip()
        if not line_text:
            continue
        if line_text.startswith("event:"):
            current_event = line_text[6:].strip().lower()
            continue
        if line_text.startswith("data:"):
            line_text = line_text[5:].strip()
        if line_text == "[DONE]":
            break
        if current_event == "meta":
            continue
        if current_event == "done":
            if not saw_delta_content:
                try:
                    raw = json.loads(line_text)
                except json.JSONDecodeError:
                    raw = None
                if isinstance(raw, dict):
                    content = raw.get("content") or raw.get("text") or raw.get("delta") or ""
                    if content:
                        yield json.dumps({"delta": str(content)}, ensure_ascii=False)
            break
        if payload_has_content(line_text):
            saw_delta_content = True
        yield line_text
