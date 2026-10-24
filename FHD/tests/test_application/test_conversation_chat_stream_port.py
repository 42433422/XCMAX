"""Conversation sample-domain port wiring (no live LLM)."""

from __future__ import annotations

from app.application.conversation.chat_stream import (
    _LegacyChatStreamAdapter,
    get_chat_stream_port,
    set_chat_stream_port,
)
from app.domain.conversation.ports import ChatStreamPort


def test_default_port_is_legacy_adapter() -> None:
    set_chat_stream_port(None)
    port = get_chat_stream_port()
    assert isinstance(port, _LegacyChatStreamAdapter)
    assert isinstance(port, ChatStreamPort)


def test_set_chat_stream_port_injection() -> None:
    class Stub:
        def chat_stream_sse_events(self, message: str, **kwargs):
            yield {"type": "text", "text": message}

    stub = Stub()
    set_chat_stream_port(stub)  # type: ignore[arg-type]
    try:
        events = list(get_chat_stream_port().chat_stream_sse_events("hi"))
        assert events == [{"type": "text", "text": "hi"}]
    finally:
        set_chat_stream_port(None)
