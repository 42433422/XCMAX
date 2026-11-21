"""包装 ModstorePlatformAdapter。"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from typing import Any, cast

from app.utils.metrics import record_ai_call
from app.utils.operational_errors import RECOVERABLE_ERRORS

from ..reasoning_stream import publish_reasoning, reasoning_from_message
from ..response_completion import normal_finish_reason
from .providers_base import raise_for_stream_failure


class ModstoreProvider:
    provider_id = "modstore"

    def __init__(self, adapter: Any | None = None):
        self._adapter = adapter

    @property
    def is_configured(self) -> bool:
        return self._adapter is not None

    @property
    def supports_streaming(self) -> bool:
        return callable(getattr(self._adapter, "stream_chat_completion", None))

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

    @property
    def stream_chat_completion(self) -> Callable[..., AsyncIterator[str]] | None:
        if not callable(getattr(self._adapter, "stream_chat_completion", None)):
            return None
        return self._stream_chat_completion

    async def _stream_chat_completion(
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
        from ..modstore_response_normalize import absorb_stream_payload

        stream = getattr(self._adapter, "stream_chat_completion", None)
        if stream is None:
            return
        reasoning: list[str] = []
        ending: dict[str, Any] = {}
        finished = False
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
                    if not payload or payload.strip() == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(payload)
                    except ValueError:
                        continue
                    raise_for_stream_failure(chunk)
                    pieces: list[str] = []
                    absorb_stream_payload(
                        payload,
                        None,
                        pieces,
                        ending,
                        reasoning,
                        payload_has_content=lambda _: False,
                    )
                    finish = ending.get("finish_reason")
                    if finish is not None and not normal_finish_reason(finish):
                        raise ValueError("模型回复未完整结束")
                    if normal_finish_reason(finish):
                        finished = True
                    for text in pieces:
                        yield text
            if not finished:
                raise ValueError("模型回复缺少结束状态")
        finally:
            publish_reasoning("".join(reasoning))
