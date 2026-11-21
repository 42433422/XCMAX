"""包装 ModstorePlatformAdapter。"""

from __future__ import annotations

import time
from contextlib import aclosing
from typing import Any, cast

from app.utils.metrics import record_ai_call
from app.utils.operational_errors import RECOVERABLE_ERRORS

from ..reasoning_stream import publish_reasoning, reasoning_from_message
from .providers_base import raise_for_stream_failure


class ModstoreProvider:
    provider_id = "modstore"

    def __init__(self, adapter: Any | None = None):
        self._adapter = adapter

    @property
    def is_configured(self) -> bool:
        return self._adapter is not None

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        if self._adapter is None:
            return None
        t0 = time.perf_counter()
        try:
            result = await self._adapter.chat_completion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            record_ai_call(self.provider_id, "chat", "success", time.perf_counter() - t0)
            if isinstance(result, dict):
                publish_reasoning(reasoning_from_message(result))
            return cast("dict[str, Any] | None", result)
        except RECOVERABLE_ERRORS:
            record_ai_call(self.provider_id, "chat", "error", time.perf_counter() - t0)
            raise

    async def stream_chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ):
        """逐段产出平台模型的正文增量（OpenAI SSE），供 SSE 生产者实时下发。"""
        if self._adapter is None:
            return
        import json

        stream = getattr(self._adapter, "stream_chat_completion", None)
        if stream is None:
            return
        reasoning: list[str] = []
        try:
            async with aclosing(
                stream(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
            ) as chunks:
                async for payload in chunks:
                    if not payload:
                        continue
                    if payload.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except ValueError:
                        continue
                    raise_for_stream_failure(chunk)
                    choices = chunk.get("choices") if isinstance(chunk, dict) else None
                    if not isinstance(choices, list) or not choices:
                        continue
                    delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
                    if isinstance(delta, dict):
                        for key in ("reasoning_content", "reasoning"):
                            value = delta.get(key)
                            if isinstance(value, str) and value:
                                reasoning.append(value)
                                break
                    text = delta.get("content") if isinstance(delta, dict) else None
                    if text:
                        yield str(text)
        finally:
            publish_reasoning("".join(reasoning))
