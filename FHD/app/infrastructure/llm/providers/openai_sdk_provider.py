"""包装 infrastructure.llm.client OpenAI SDK 单例。"""

from __future__ import annotations

import asyncio
import json
import math
import time
from contextlib import ExitStack, aclosing
from types import SimpleNamespace
from typing import Any, cast

import httpx
import httpx2

from app.application.tool_execution_deadline import (
    check_invocation_deadline,
    remaining_invocation_seconds,
)
from app.infrastructure.chat_stream_lifetime import (
    StreamLifetime,
    StreamWorker,
    owned_model_read,
)
from app.utils.metrics import record_ai_call
from app.utils.operational_errors import RECOVERABLE_ERRORS

from ..reasoning_stream import publish_reasoning, reasoning_from_message


def _bounded_sdk_timeout(timeout: Any, remaining: float) -> httpx.Timeout | httpx2.Timeout:
    """Cap each SDK timeout phase without changing its HTTP transport family.

    OpenAI 3.x uses httpx2.Timeout, which legacy httpx.Timeout treats as an
    opaque scalar. Preserve the native timeout type so the SDK can enforce
    bounded connect/read/write/pool phases rather than failing requests.
    """
    configured = (
        timeout
        if isinstance(timeout, (httpx.Timeout, httpx2.Timeout))
        else httpx2.Timeout(timeout)
    )
    phases: dict[str, float] = {}
    for name, value in configured.as_dict().items():
        if isinstance(value, (httpx.Timeout, httpx2.Timeout)):
            value = value.as_dict()[name]
        if value is None:
            phases[name] = remaining
        elif isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
            phases[name] = min(float(value), remaining)
        else:
            raise ValueError(f"invalid {name} timeout for SDK request")
    return type(configured)(**phases)

async def _sdk_responses(client: Any, request: dict[str, Any], *, stream: bool):
    """Bridge sync SDK I/O without leaving an asyncio executor job on cancellation."""
    reads = StreamLifetime()

    def produce():
        try:
            check_invocation_deadline()
            native = False
            if getattr(client.chat.completions, "with_streaming_response", None) is not None:
                from openai import NotGiven, OpenAI

                native = isinstance(client, OpenAI)
            with ExitStack() as stack:
                if native:
                    scoped = client
                    remaining = remaining_invocation_seconds(math.inf)
                    if math.isfinite(remaining):
                        # Clone options only; the shared client/pool remains borrowed.
                        scoped = client.with_options(max_retries=0)
                        timeout = request.get("timeout", client.timeout)
                        if isinstance(timeout, NotGiven):
                            timeout = client.timeout
                        request["timeout"] = _bounded_sdk_timeout(timeout, remaining)
                    check_invocation_deadline()
                    raw = stack.enter_context(
                        scoped.chat.completions.with_streaming_response.create(**request)
                    )
                    # Enter ownership before parse() starts reading the body.
                    stack.enter_context(owned_model_read(raw.http_response))
                    stack.enter_context(reads.reading(raw.http_response))
                    response = raw.parse()
                else:
                    response = client.chat.completions.create(**request)
                    if stream:
                        stack.enter_context(owned_model_read(response))
                        stack.enter_context(reads.reading(response))
                if stream:
                    yield from response
                else:
                    yield response
        except asyncio.CancelledError as exc:
            # A compatible client may itself cancel its producer iterator.
            yield exc

    worker = StreamWorker(produce)
    try:
        while True:
            item = await worker.receive()
            if item is worker.END:
                return
            if isinstance(item, BaseException):
                raise item
            check_invocation_deadline()
            yield item
    finally:
        worker.close()
        # Cancel only this request's reads, never the borrowed client or pool.
        reads.cancel()


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

        request = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **{k: v for k, v in kwargs.items() if k not in ("model",)},
        }
        try:
            async with aclosing(_sdk_responses(client, request, stream=False)) as source:
                resp = await anext(source)
            if hasattr(resp, "model_dump"):
                result = cast("dict[str, Any]", resp.model_dump())
            elif isinstance(resp, SimpleNamespace):
                result = cast("dict[str, Any]", json.loads(json.dumps(resp, default=vars)))
            else:
                result = dict(resp)
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
        request = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            **{k: v for k, v in kwargs.items() if k not in ("model", "stream")},
        }
        reasoning: list[str] = []
        try:
            async with aclosing(_sdk_responses(client, request, stream=True)) as source:
                async for chunk in source:
                    reasoning_text = _chunk_delta_reasoning(chunk)
                    if reasoning_text:
                        reasoning.append(reasoning_text)
                    text = _chunk_delta_text(chunk)
                    if text:
                        yield text
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
