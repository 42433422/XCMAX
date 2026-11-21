"""包装 infrastructure.llm.client OpenAI SDK 单例。"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any, cast

from app.utils.metrics import record_ai_call
from app.utils.operational_errors import RECOVERABLE_ERRORS

from ..reasoning_stream import publish_reasoning, reasoning_from_message
from ..response_completion import normal_finish_reason


class OpenAISdkProvider:
    provider_id = "openai_sdk"

    @property
    def is_configured(self) -> bool:
        from app.infrastructure.llm.client import get_llm_client

        return get_llm_client() is not None

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        model: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        import asyncio

        from app.infrastructure.llm.client import (
            get_llm_client,
            require_api_key,
            resolve_chat_model,
        )

        require_api_key()
        client = get_llm_client()
        if client is None:
            return None
        model_name = model or resolve_chat_model()
        t0 = time.perf_counter()

        def _sync_call() -> dict[str, Any]:
            resp = client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **{k: v for k, v in kwargs.items() if k not in ("model",)},
            )
            if hasattr(resp, "model_dump"):
                return cast("dict[str, Any]", resp.model_dump())
            if isinstance(resp, SimpleNamespace):
                return cast("dict[str, Any]", json.loads(json.dumps(resp, default=vars)))
            return dict(resp)

        try:
            result = await asyncio.to_thread(_sync_call)
            record_ai_call(self.provider_id, "chat", "success", time.perf_counter() - t0)
            publish_reasoning(reasoning_from_message(result))
            return result
        except RECOVERABLE_ERRORS:
            record_ai_call(self.provider_id, "chat", "error", time.perf_counter() - t0)
            raise

    async def stream_chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        model: str | None = None,
        **kwargs: Any,
    ):
        """逐段产出正文增量；客户端不支持流式时静默结束，由调用方回退。"""
        import asyncio

        from app.infrastructure.llm.client import (
            get_llm_client,
            require_api_key,
            resolve_chat_model,
        )

        require_api_key()
        client = get_llm_client()
        if client is None:
            return
        model_name = model or resolve_chat_model()
        stream = await asyncio.to_thread(
            lambda: client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                **{k: v for k, v in kwargs.items() if k not in ("model", "stream")},
            )
        )
        iterator = iter(stream)
        reasoning: list[str] = []
        finished = False
        try:
            while True:
                chunk = await asyncio.to_thread(next, iterator, None)
                if chunk is None:
                    break
                choices = (
                    chunk.get("choices")
                    if isinstance(chunk, dict)
                    else getattr(chunk, "choices", None)
                )
                first = choices[0] if isinstance(choices, (list, tuple)) and choices else None
                finish = (
                    first.get("finish_reason")
                    if isinstance(first, dict)
                    else getattr(first, "finish_reason", None)
                )
                if finish is not None and not normal_finish_reason(finish):
                    raise ValueError("模型回复未完整结束")
                if normal_finish_reason(finish):
                    finished = True
                reasoning_text = _chunk_delta_reasoning(chunk)
                if reasoning_text:
                    reasoning.append(reasoning_text)
                text = _chunk_delta_text(chunk)
                if text:
                    yield text
            if not finished:
                raise ValueError("模型回复缺少结束状态")
        finally:
            publish_reasoning("".join(reasoning))


def _chunk_delta_text(chunk: Any) -> str:
    choices = chunk.get("choices") if isinstance(chunk, dict) else getattr(chunk, "choices", None)
    if not isinstance(choices, (list, tuple)) or not choices:
        return ""
    first = choices[0]
    delta = first.get("delta") if isinstance(first, dict) else getattr(first, "delta", None)
    if delta is None:
        return ""
    content = delta.get("content") if isinstance(delta, dict) else getattr(delta, "content", None)
    return str(content or "")


def _chunk_delta_reasoning(chunk: Any) -> str:
    """取 OpenAI 兼容流里的推理增量，不混入正文。"""
    choices = chunk.get("choices") if isinstance(chunk, dict) else getattr(chunk, "choices", None)
    if not isinstance(choices, (list, tuple)) or not choices:
        return ""
    first = choices[0]
    delta = first.get("delta") if isinstance(first, dict) else getattr(first, "delta", None)
    if isinstance(delta, dict):
        return str(delta.get("reasoning_content") or delta.get("reasoning") or "")
    if delta is None:
        return ""
    return str(getattr(delta, "reasoning_content", "") or getattr(delta, "reasoning", "") or "")
