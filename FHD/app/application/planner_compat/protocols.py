"""Explicit backend and response contracts shared by JSON and batch chat."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from fastapi import HTTPException, Request

from app.fastapi_routes.xcagi_compat_chat_models import (
    XcagiCompatChatBatchBody,
    XcagiCompatChatBody,
)

Payload = dict[str, Any]
Context = dict[str, Any]
ChatBody = XcagiCompatChatBody | XcagiCompatChatBatchBody
T = TypeVar("T")


class AwaitTimeout(Protocol):
    async def __call__(self, awaitable: Awaitable[T], *, timeout: float) -> T: ...


class ReplyFormatter(Protocol):
    def __call__(
        self,
        reply: str | Payload,
        *,
        runtime_context_update: Context | None = None,
        kitten_attachments: Payload | None = None,
    ) -> Payload: ...


class MainlineChat(Protocol):
    async def __call__(
        self,
        body: ChatBody,
        runtime_context: Context,
        *,
        message: str | None = None,
        kitten_extra: Payload | None = None,
    ) -> Payload: ...


class AttachTrace(Protocol):
    def __call__(
        self,
        payload: Payload,
        body: ChatBody,
        *,
        message: str,
        runtime_context: Context | None,
        channel: str,
    ) -> Payload: ...


class ReadAuthorization(Protocol):
    def __call__(
        self, request: Request, *, message: str, provided_token: str | None
    ) -> tuple[bool, Payload | None]: ...


@dataclass(frozen=True)
class ChatResponses:
    timeout: Callable[[float], Payload]
    http_error: Callable[[BaseException], HTTPException]


@dataclass(frozen=True)
class ChatBackends:
    mainline: MainlineChat


@dataclass(frozen=True)
class ChatTrace:
    attach: AttachTrace


@dataclass(frozen=True)
class ChatTurn:
    body: ChatBody
    message: str
    context: Context
    channel: str
    kitten_extra: Payload | None = None

    @property
    def is_batch(self) -> bool:
        return self.channel == "compat_chat_batch"

    def planner_context(self) -> Context:
        context = dict(self.context or {})
        if self.body.system_prompt:
            context["system_prompt"] = self.body.system_prompt
        if self.body.db_write_token:
            context["db_write_token_present"] = True
        return context
