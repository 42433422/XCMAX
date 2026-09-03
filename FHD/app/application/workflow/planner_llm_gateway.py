from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, cast

from app.infrastructure.llm.providers.credentials import default_chat_completions_url
from app.services.conversation.modstore_adapter import ModstorePlatformAdapter
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _meter_planner_completion(payload: dict[str, Any] | None, *, model: str) -> None:
    """统一 Agent Runtime 计量接缝：planner LLM 用量入账（best-effort，不受 hooks 开关限制）。"""
    if not isinstance(payload, dict):
        return
    try:
        from app.application.agent_runtime.pipeline import completion_usage, meter_llm_call

        usage = completion_usage(payload)
        if not usage.get("total_tokens"):
            return
        meta = payload.get("_xcagi_billing")
        provider = ""
        provider_id = ""
        if isinstance(meta, dict):
            provider = str(meta.get("provider") or "")
            provider_id = str(meta.get("provider_id") or "")
        meter_llm_call(
            source="agent_planner",
            model=str(payload.get("model") or model),
            usage=usage,
            provider=provider,
            provider_id=provider_id,
            metadata={"channel": "planner_llm_gateway"},
        )
    except RECOVERABLE_ERRORS:
        logger.debug("planner LLM metering skipped", exc_info=True)


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
        if response.status_code >= 400:
            return None
        payload = cast("dict[str, Any]", response.json())
        _meter_planner_completion(payload, model=model)
        return payload

    session_id = str(
        (context or {}).get("session_id") or (context or {}).get("conversation_id") or ""
    ).strip()
    if session_id:
        try:
            session_adapter = ModstorePlatformAdapter.from_session(session_id=session_id)
            if session_adapter.is_configured:
                result = cast(
                    "dict[str, Any] | None",
                    session_adapter.chat_completion_sync(
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    ),
                )
                _meter_planner_completion(result, model="")
                return result
        except RECOVERABLE_ERRORS as exc:
            logger.warning("从 Session 构建规划市场适配器失败: %s", exc)

    configured_adapter = getattr(ai_service, "modstore_adapter", None)
    if configured_adapter is None or not getattr(configured_adapter, "is_configured", False):
        return None
    logger.info("LLM 规划走修茈市场平台通道 (modstore_adapter)")
    result = cast(
        "dict[str, Any]",
        configured_adapter.chat_completion_sync(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        ),
    )
    _meter_planner_completion(result, model="")
    return result
