"""Narrow interfaces for HTTP, cursor sessions, and tool execution."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.request import Request

from starlette.types import ASGIApp

JsonObject = dict[str, Any]
ToolCall = Callable[[ASGIApp, JsonObject], JsonObject]


class HttpResponse(Protocol):
    @property
    def status_code(self) -> int: ...
    @property
    def text(self) -> str: ...
    def json(self) -> object: ...


class CookieJar(Protocol):
    def get(self, name: str, default: str | None = None) -> str | None: ...


class InternalHttpClient(Protocol):
    """A per-call ASGI client that does not follow redirects or start app lifespan."""

    @property
    def cookies(self) -> CookieJar: ...
    def get(self, url: str, *, headers: dict[str, str] | None = None) -> HttpResponse: ...
    def delete(self, url: str, *, headers: dict[str, str] | None = None) -> HttpResponse: ...
    def request(
        self, method: str, url: str, *, json: JsonObject, headers: dict[str, str]
    ) -> HttpResponse: ...
    def close(self) -> None: ...


class CursorHub(Protocol):
    def session_ids(self) -> list[str]: ...
    def sessions_info(self) -> list[JsonObject]: ...
    async def dispatch(
        self,
        action: str,
        params: JsonObject | None = None,
        *,
        session_id: str | None = None,
        timeout: float = 10.0,
    ) -> JsonObject: ...


class UpstreamResponse(Protocol):
    def read(self) -> bytes: ...


class UpstreamOpener(Protocol):
    def __call__(
        self, request: Request, *, timeout: float
    ) -> AbstractContextManager[UpstreamResponse]: ...


@dataclass(frozen=True)
class InstallationBuilders:
    url: Callable[[str, str], JsonObject]
    stdio: Callable[[str, str], JsonObject]
    remote: Callable[[str, str], JsonObject]
    deeplink: Callable[[str, JsonObject], str]
