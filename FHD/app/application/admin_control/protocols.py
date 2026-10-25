"""Typed caller boundaries for the admin control plane."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from logging import Logger
from typing import Any, Protocol

from fastapi import Request
from fastapi.responses import JSONResponse

JsonObject = dict[str, Any]
AdminResult = JsonObject | JSONResponse
AdminGate = Callable[[Request], JSONResponse | None]


@dataclass(frozen=True)
class ErrorPolicy:
    recoverable: Callable[[], tuple[type[Exception], ...]]
    logger: Logger


class MarketProxy(Protocol):
    def __call__(
        self,
        request: Request,
        method: str,
        path: str,
        *,
        json_body: JsonObject | None = None,
        require_admin_session: bool = True,
        authorization_override: str = "",
    ) -> Awaitable[AdminResult]: ...


class LocalProxy(Protocol):
    def __call__(
        self,
        request: Request,
        method: str,
        path: str,
        *,
        json_body: JsonObject | None = None,
    ) -> Awaitable[AdminResult | None]: ...


class UpstreamRequest(Protocol):
    def __call__(
        self,
        method: str,
        path: str,
        *,
        json_body: JsonObject | None,
        authorization: str,
        return_error_payload: bool,
    ) -> Awaitable[AdminResult]: ...


@dataclass(frozen=True)
class MarketTransport:
    authorization_header: Callable[[str], str]
    resolve_authorization: Callable[[Request, JsonObject], Awaitable[str]]
    request: UpstreamRequest
    error_message: Callable[[object, int], str]


class SyncStore(Protocol):
    """Each operation closes its own connection before returning to an SSE yield."""

    def get_status(self) -> JsonObject: ...
    def get_changes(self, *, since_cursor: int, limit: int) -> list[JsonObject]: ...
    def enqueue_inbox(self, items: list[JsonObject]) -> int: ...
    def mark_inbox_applied(self, inbox_id: int) -> None: ...


class RefreshEntitlements(Protocol):
    def __call__(
        self,
        session_id: str,
        market_user_id: int | None,
        *,
        username: str | None = None,
    ) -> Awaitable[None]: ...
