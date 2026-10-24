"""Conversation application use-cases (sample domain).

HTTP routes should import from here — not from ``app.legacy.chat``.
The legacy adapter remains the temporary infrastructure implementation
until phase-3 retirement (refs → 0).
"""

from __future__ import annotations

from app.application.conversation.chat_stream import (
    chat_stream_sse_events,
    clear_last_tool_result,
    get_chat_stream_port,
    get_last_tool_result,
    set_chat_stream_port,
)

__all__ = [
    "chat_stream_sse_events",
    "clear_last_tool_result",
    "get_last_tool_result",
    "get_chat_stream_port",
    "set_chat_stream_port",
]
