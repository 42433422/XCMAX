"""Detect real model deltas without accepting keepalive as answer progress."""

from __future__ import annotations

from typing import Any

_KEEPALIVE_STATES = frozenset({"processing", "accepted", "heartbeat", "ping", "keepalive"})
_KEEPALIVE_EVENTS = frozenset({"heartbeat", "ping", "keepalive", "keep-alive", "processing"})


def _delta_fields_have_content(holder: dict) -> bool:
    for key in ("content", "reasoning_content"):
        value = holder.get(key)
        if isinstance(value, str) and value:
            return True
    return bool(holder.get("tool_calls"))


def _stream_payload_carries_delta(payload: dict) -> bool:
    delta = payload.get("delta")
    if isinstance(delta, str) and delta:
        return True
    if isinstance(delta, dict) and _delta_fields_have_content(delta):
        return True
    if isinstance(payload.get("content"), str) and payload["content"]:
        return True
    if isinstance(payload.get("reasoning_content"), str) and payload["reasoning_content"]:
        return True
    if payload.get("tool_calls"):
        return True
    for choice in payload.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        for holder in (choice.get("delta"), choice.get("message")):
            if isinstance(holder, dict) and _delta_fields_have_content(holder):
                return True
    return False


def _stream_payload_has_content(payload: Any) -> bool:
    """True only for real answer events; keepalive/status events never count as progress."""
    if not isinstance(payload, dict) or not payload:
        return False
    if _stream_payload_carries_delta(payload):
        return True
    for key in ("status", "state"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip().lower() in _KEEPALIVE_STATES:
            return False
    if any(payload.get(key) for key in ("heartbeat", "ping", "keepalive", "keep_alive")):
        return False
    event = payload.get("event") or payload.get("type")
    if isinstance(event, str) and event.strip().lower() in _KEEPALIVE_EVENTS:
        return False
    return True
