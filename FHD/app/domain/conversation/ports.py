"""Conversation domain ports (one-ctx-one-ports).

Phase-2 sample domain: new contracts live here; application/ports must not grow.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any, Protocol


class ChatStreamPort(Protocol):
    """Streaming chat used by conversation HTTP adapters (SSE events)."""

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
        **extra: Any,
    ) -> Iterator[dict[str, Any]]: ...


class ChatToolResultPort(Protocol):
    """Last tool-result probe used by reply enrichment."""

    def get_last_tool_result(self) -> dict[str, Any]: ...

    def clear_last_tool_result(self) -> None: ...
