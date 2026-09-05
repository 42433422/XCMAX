"""卫星调用点统一入口 — 避免硬编码 api.deepseek.com。"""

from __future__ import annotations

import logging
from typing import Any

from app.infrastructure.llm.providers.registry import get_active_provider

logger = logging.getLogger(__name__)


async def chat_completion_openai_format(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    profile: str = "default",
    request: Any | None = None,
    reasoning_enabled: bool | None = None,
    conversation_service: Any | None = None,
    provider: Any | None = None,
    **kwargs: Any,
) -> dict[str, Any] | None:
    """按 LLM_ROUTING_ORDER / LLM_PROVIDER 解析 Provider 并调用 chat/completions。"""
    # An owner-bound provider must stay bound to that owner through structured
    # output and retries; it must never fall back to another account's default.
    if provider is None:
        routing: dict[str, Any] = {"request": request, "profile": profile}
        if conversation_service is not None:
            routing["conversation_service"] = conversation_service
        provider = get_active_provider(**routing)
    if provider is None:
        logger.error("No configured LLM provider (profile=%s)", profile)
        return None
    # MiMo V2.5 is a reasoning model.  For short structured-output flows its
    # reasoning can consume the entire completion budget before any JSON body
    # is emitted.  Keep this provider-specific compatibility parameter at the
    # shared invocation boundary so other OpenAI-compatible providers never
    # receive an unsupported ``thinking`` field.
    if reasoning_enabled is False and provider.provider_id == "xiaomi":
        kwargs.setdefault("thinking", {"type": "disabled"})
    return await provider.chat_completion(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )
