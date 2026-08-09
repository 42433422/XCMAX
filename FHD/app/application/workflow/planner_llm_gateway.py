from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.infrastructure.llm.providers.credentials import default_chat_completions_url
from app.services.conversation.modstore_adapter import ModstorePlatformAdapter
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def request_planner_completion(
    *,
    ai_service: Any,
    context: dict[str, Any] | None,
    messages: list[dict[str, str]],
    http_client_factory: Callable[[], Any],
    temperature: float = 0.1,
    max_tokens: int = 1200,
) -> dict[str, Any] | None:
    """Call the direct LLM when configured, otherwise reuse the authenticated market channel."""
    api_key = str(getattr(ai_service, "api_key", "") or "")
    if api_key:
        api_url = getattr(ai_service, "api_url", "") or default_chat_completions_url()
        model = getattr(ai_service, "model", "") or "deepseek-chat"
        response = http_client_factory().post(
            api_url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        return None if response.status_code >= 400 else response.json()

    session_id = str(
        (context or {}).get("session_id") or (context or {}).get("conversation_id") or ""
    ).strip()
    if session_id:
        try:
            adapter = ModstorePlatformAdapter.from_session(session_id=session_id)
            if adapter.is_configured:
                return adapter.chat_completion_sync(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
        except RECOVERABLE_ERRORS as exc:
            logger.warning("从 Session 构建规划市场适配器失败: %s", exc)

    adapter = getattr(ai_service, "modstore_adapter", None)
    if adapter is None or not getattr(adapter, "is_configured", False):
        return None
    logger.info("LLM 规划走修茈市场平台通道 (modstore_adapter)")
    return adapter.chat_completion_sync(
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
