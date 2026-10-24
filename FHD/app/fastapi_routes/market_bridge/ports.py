"""Typed effects at the market HTTP, credential and local-session boundaries."""

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from fastapi import Request

JsonObject = dict[str, Any]


class ProxyJSON(Protocol):
    def __call__(
        self,
        method: str,
        path: str,
        *,
        json_body: JsonObject | None = None,
        authorization: str = "",
        extra_headers: dict[str, str] | None = None,
        return_error_payload: bool = False,
        sensitive: bool = False,
        timeout: float | None = None,
        retries: int | None = None,
    ) -> Awaitable[Any]: ...


class SaveToken(Protocol):
    def __call__(self, session_id: str, token: str, refresh_token: str | None = None) -> None: ...


class LatestToken(Protocol):
    def __call__(self, user_id: int | None = None) -> str: ...


class NormalizeAuth(Protocol):
    def __call__(
        self, payload: Any, *, market_base: str | None = None
    ) -> Awaitable[JsonObject]: ...


class DemoPayload(Protocol):
    def __call__(self, shim: JsonObject, *, market_base_url: str) -> JsonObject: ...


class LocalUser(Protocol):
    @property
    def id(self) -> int: ...

    @property
    def is_active(self) -> bool: ...


class EnsureEnterprise(Protocol):
    def __call__(
        self,
        market_user_id: int | str | None,
        *,
        username: str = "",
        company: str = "",
        mod_ids: list[str] | tuple[str, ...] | None = None,
    ) -> Awaitable[JsonObject]: ...


class RefreshWallet(Protocol):
    def __call__(
        self,
        data: JsonObject,
        authorization: str,
        sync_warning: str,
        *,
        proxy_json: ProxyJSON,
        error_message: Callable[[Any, int], str],
    ) -> Awaitable[str]: ...


RequestAuthorization = Callable[[Request, JsonObject], Awaitable[str]]
CheckoutAuthorization = Callable[
    [Request, JsonObject], Awaitable[tuple[str, JsonObject | None] | str]
]
