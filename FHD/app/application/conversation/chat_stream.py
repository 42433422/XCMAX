"""Conversation chat-stream use-case.

Decouples FastAPI conversation routes from ``app.legacy.chat`` imports.
Default implementation delegates to the legacy chat adapter (infra) until
that adapter is retired in phase-3.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any, cast

from app.domain.conversation.ports import ChatStreamPort, ChatToolResultPort

_port: ChatStreamPort | None = None
_tool_port: ChatToolResultPort | None = None


class _LegacyChatStreamAdapter:
    """Thin infrastructure adapter — sole production import of legacy chat."""

    def chat_stream_sse_events(
        self,
        message: str,
        *,
        runtime_context: Mapping[str, Any] | None = None,
        system_prompt: str | None = None,
        workspace_root: str | None = None,
        db_write_token: str | None = None,
        client: Any = None,
        model: str | None = None,
        max_iterations: int | None = None,
        **_extra: Any,
    ) -> Iterator[dict[str, Any]]:
        from app.legacy.chat.legacy_chat_adapter import (
            chat_stream_sse_events as _impl,
        )

        return cast(
            Iterator[dict[str, Any]],
            _impl(
                message,
                runtime_context=dict(runtime_context) if runtime_context is not None else None,
                system_prompt=system_prompt,
                workspace_root=workspace_root,
                db_write_token=db_write_token,
                client=client,
                model=model,
                max_iterations=max_iterations,
            ),
        )

    def get_last_tool_result(self) -> dict[str, Any]:
        from app.legacy.chat.legacy_chat_adapter import get_last_tool_result as _impl

        return cast(dict[str, Any], _impl())

    def clear_last_tool_result(self) -> None:
        from app.legacy.chat.legacy_chat_adapter import clear_last_tool_result as _impl

        _impl()


def _default_adapter() -> _LegacyChatStreamAdapter:
    return _LegacyChatStreamAdapter()


def get_chat_stream_port() -> ChatStreamPort:
    global _port
    if _port is None:
        _port = _default_adapter()
    return _port


def set_chat_stream_port(port: ChatStreamPort | None) -> None:
    """Test seam / DI."""
    global _port
    _port = port


def get_chat_tool_result_port() -> ChatToolResultPort:
    global _tool_port
    if _tool_port is None:
        _tool_port = _default_adapter()  # type: ignore[assignment]
    return _tool_port


def chat_stream_sse_events(
    message: str,
    *,
    runtime_context: Mapping[str, Any] | None = None,
    system_prompt: str | None = None,
    workspace_root: str | None = None,
    db_write_token: str | None = None,
    client: Any = None,
    model: str | None = None,
    max_iterations: int | None = None,
    **extra: Any,
) -> Iterator[dict[str, Any]]:
    return get_chat_stream_port().chat_stream_sse_events(
        message,
        runtime_context=runtime_context,
        system_prompt=system_prompt,
        workspace_root=workspace_root,
        db_write_token=db_write_token,
        client=client,
        model=model,
        max_iterations=max_iterations,
        **extra,
    )


def get_last_tool_result() -> dict[str, Any]:
    return get_chat_tool_result_port().get_last_tool_result()


def clear_last_tool_result() -> None:
    get_chat_tool_result_port().clear_last_tool_result()
