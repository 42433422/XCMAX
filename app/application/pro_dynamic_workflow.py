"""专业版动态工作流分支（从 ai_chat_app_service._try_handle_dynamic_workflow 拆出门面）。"""

from __future__ import annotations

from typing import Any


def try_handle_dynamic_workflow(
    service: Any,
    *,
    user_id: str,
    message: str,
    source: str | None,
    context: dict[str, Any],
    file_context: dict[str, Any],
) -> dict[str, Any] | None:
    return service._try_handle_dynamic_workflow(
        user_id,
        message,
        source,
        context,
        file_context,
    )
