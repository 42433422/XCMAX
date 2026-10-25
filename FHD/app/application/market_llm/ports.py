"""Compat module path: debt19 renamed ports.py → protocols.py."""

from __future__ import annotations

from .protocols import (  # noqa: F401
    CacheKey,
    ChatInput,
    CompatibleCompletion,
    CompatibleStream,
    CompletionPorts,
    Connection,
    Messages,
    NotifyRoundtrip,
    OpenAIPorts,
    Payload,
    PostCompletion,
    ResponsePorts,
    Route,
    StreamPorts,
    SyncClientFactory,
)

__all__ = [
    "CacheKey",
    "ChatInput",
    "CompatibleCompletion",
    "CompatibleStream",
    "CompletionPorts",
    "Connection",
    "Messages",
    "NotifyRoundtrip",
    "OpenAIPorts",
    "Payload",
    "PostCompletion",
    "ResponsePorts",
    "Route",
    "StreamPorts",
    "SyncClientFactory",
]
