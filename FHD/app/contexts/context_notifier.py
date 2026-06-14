"""对话上下文变更通知器（懒加载；无 SSE 时返回 None）。"""

from __future__ import annotations

from typing import Any, Protocol


class ContextNotifier(Protocol):
    def notify_pending_preserved(
        self, user_id: str, pending_data: dict[str, Any], action: str
    ) -> None: ...


def get_context_notifier() -> ContextNotifier | None:
    return None
