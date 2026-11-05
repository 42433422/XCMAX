"""Optional platform I/O adapters, bound by the public composition root."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx


def http_get(url: str, **kwargs: Any) -> httpx.Response:
    import httpx

    return httpx.get(url, **kwargs)
