"""Resolve the UI tool profile without classifying or executing a chat turn."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def resolve_tool_execution_profile(runtime_context: Mapping[str, Any] | None) -> str:
    context = runtime_context or {}
    explicit = str(context.get("tool_execution_profile") or "").strip().lower()
    if explicit == "normal":
        return "normal"
    if explicit in {"pro_default", "pro", "professional"}:
        return "pro_default"
    surface = str(context.get("ui_surface") or "").strip().lower()
    channel = str(context.get("intent_channel") or "pro").strip().lower()
    return "normal" if surface == "normal" and channel == "pro" else "pro_default"
