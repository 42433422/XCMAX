"""Request values and the narrow capabilities used by market LLM operations."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from logging import Logger
from typing import Any, Protocol

import httpx

Payload = dict[str, Any]
Messages = list[Payload]
Route = tuple[str, str]
CacheKey = tuple[str, str]


@dataclass(frozen=True)
class Connection:
    platform_url: str
    auth_token: str
    user_id: int | None
    timeout: float

    def headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers


@dataclass(frozen=True)
class ChatInput:
    messages: Messages
    temperature: float = 0.7
    max_tokens: int = 2000
    extra: Payload = field(default_factory=dict)

    def payload(
        self,
        connection: Connection,
        route: Route,
        messages: Messages,
        *,
        stream: bool = False,
        allow_failover: bool | None = None,
    ) -> Payload:
        payload: Payload = {
            "provider": route[0],
            "model": route[1],
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if stream:
            payload["stream"] = True
        if allow_failover is not None:
            payload["allow_failover"] = allow_failover
        payload.update(
            {
                key: value
                for key, value in self.extra.items()
                if key not in {"timeout", "_reviewed_excel_audit_response"}
            }
        )
        if connection.user_id:
            payload["user_id"] = connection.user_id
        return payload


class SyncClientFactory(Protocol):
    def __call__(self, **kwargs: Any) -> httpx.Client: ...


class PostCompletion(Protocol):
    def __call__(
        self,
        *,
        provider: str,
        model: str,
        messages: Messages,
        temperature: float,
        max_tokens: int,
        allow_failover: bool,
        extra: Payload | None = None,
    ) -> Payload: ...


class NotifyRoundtrip(Protocol):
    def __call__(
        self, *, model: str, latency_ms: float, token_count: int, user_id: str
    ) -> None: ...


@dataclass(frozen=True)
class ResponsePorts:
    normalize: Callable[[Payload, str, str], Payload]
    notify: NotifyRoundtrip
    clock: Callable[[], float]
    logger: Logger


@dataclass(frozen=True)
class CompletionPorts:
    candidates: Callable[[str, str], list[Route]]
    prepare_sync: Callable[[Messages, str, str], Messages]
    prepare_async: Callable[[Messages, str, str], Awaitable[Messages]]
    post_sync: PostCompletion
    client: Callable[[], Awaitable[httpx.AsyncClient]]
    failoverable: Callable[[int | None, str], bool]
    response: ResponsePorts
    status_code: Callable[[object, int], int]


@dataclass(frozen=True)
class StreamPorts:
    candidates: Callable[[str, str], list[Route]]
    prepare_sync: Callable[[Messages, str, str], Messages]
    prepare_async: Callable[[Messages, str, str], Awaitable[Messages]]
    sync_client: SyncClientFactory
    async_client: Callable[[], Awaitable[httpx.AsyncClient]]
    sync_payloads: Callable[[object], Iterator[str]]
    async_payloads: Callable[[httpx.Response], AsyncIterator[str]]
    failoverable: Callable[[int | None, str], bool]
    connect_timeout: Callable[[], float]
    status_code: Callable[[object, int], int]
    logger: Logger


class CompatibleCompletion(Protocol):
    def __call__(
        self,
        messages: Messages,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        provider: str | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> Payload: ...


class CompatibleStream(Protocol):
    def __call__(
        self,
        messages: Messages,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        provider: str | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> Iterator[str]: ...


@dataclass(frozen=True)
class OpenAIPorts:
    complete: CompatibleCompletion
    stream: CompatibleStream
    model_name: str
