"""Isolate AI context between smart chat and business docking surfaces."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, Iterator, Mapping

SMART_CHAT = "smart_chat"
BUSINESS_DOCKING = "business_docking"
CHANNELS = frozenset({SMART_CHAT, BUSINESS_DOCKING})
_CHAT_ALIASES = frozenset({"chat", "smart_chat", "conversation", "ai_chat"})
_DOCK_ALIASES = frozenset(
    {
        "dock",
        "docking",
        "business_docking",
        "data_docking",
        "elt",
        "elt",
        "reviewed_excel",
        "office_docking",
    }
)
_CHANNEL: ContextVar[str | None] = ContextVar("ai_feature_channel", default=None)


def normalize_channel(value: object | None) -> str | None:
    text = str(value or "").strip().lower().replace("-", "_")
    if text in _CHAT_ALIASES:
        return SMART_CHAT
    if text in _DOCK_ALIASES:
        return BUSINESS_DOCKING
    return text if text in CHANNELS else None


def current_ai_feature_channel() -> str | None:
    return _CHANNEL.get()


def bind_ai_feature_channel(channel: str) -> Token[str | None]:
    normalized = normalize_channel(channel)
    if normalized is None:
        raise ValueError("unsupported ai feature channel")
    return _CHANNEL.set(normalized)


def reset_ai_feature_channel(token: Token[str | None]) -> None:
    _CHANNEL.reset(token)


@contextmanager
def ai_feature_channel(channel: str) -> Iterator[str]:
    token = bind_ai_feature_channel(channel)
    try:
        yield normalize_channel(channel) or SMART_CHAT
    finally:
        reset_ai_feature_channel(token)


def tag_mapping(
    payload: Mapping[str, Any] | None = None, *, channel: str | None = None
) -> dict[str, Any]:
    data = dict(payload or {})
    resolved = normalize_channel(channel) or current_ai_feature_channel()
    if resolved:
        data["ai_feature_channel"] = resolved
    return data


def channel_of(payload: Mapping[str, Any] | None) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    return normalize_channel(
        payload.get("ai_feature_channel")
        or payload.get("feature_channel")
        or payload.get("channel")
        or payload.get("source_channel")
    )


def allows_channel(payload: Mapping[str, Any] | None, channel: str | None) -> bool:
    wanted = normalize_channel(channel) or current_ai_feature_channel()
    if wanted is None:
        return True
    found = channel_of(payload)
    return found is None or found == wanted
