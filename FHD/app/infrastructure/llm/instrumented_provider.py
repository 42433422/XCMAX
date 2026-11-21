"""InstrumentedProvider — 在 LLMProvider 外包遥测 + Guardrails 的装饰层。

包裹点：``LLMProviderRegistry.get()/resolve()`` 返回处（见 registry.py）。
顺序（spec §3.1）：开 span → 输入检查 → 真实调用 → 输出检查 → 落盘。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from app.infrastructure.llm import genai_telemetry as telemetry
from app.infrastructure.llm import guardrails
from app.infrastructure.llm.providers.providers_base import LLMProvider
from app.infrastructure.llm.trace_store import get_trace_store
from app.neuro_bus.tracer import TraceContext, get_trace_context
from app.security.log_redaction import redact_log_text
from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _telemetry_call(operation: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """An observation failure must neither replay a model call nor replace its result."""
    try:
        return operation(*args, **kwargs)
    except BOUNDARY_ERRORS:
        logger.warning("genai telemetry unavailable")
        return None


def _infer_caller() -> str | None:
    """best-effort 推断业务调用方模块名。"""
    try:
        for frame in inspect.stack()[2:]:
            module = inspect.getmodule(frame.frame)
            name = getattr(module, "__name__", "") or ""
            if name.startswith("app.") and not name.startswith("app.infrastructure.llm"):
                return name
    except RECOVERABLE_ERRORS:
        pass
    return None


class InstrumentedProvider:
    """包裹任意 LLMProvider，叠加 GenAI 遥测与 Guardrails。"""

    _xcagi_instrumented = True

    def __init__(self, inner: LLMProvider, *, profile: str | None = None) -> None:
        self._inner = inner
        self._profile = profile or "default"

    @property
    def _xcagi_rate_limited(self) -> bool:
        return bool(getattr(self._inner, "_xcagi_rate_limited", False))

    @property
    def provider_id(self) -> str:
        return self._inner.provider_id

    @property
    def is_configured(self) -> bool:
        return self._inner.is_configured

    @property
    def supports_streaming(self) -> bool:
        from app.infrastructure.llm.response_completion import provider_supports_streaming

        return provider_supports_streaming(self._inner)

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        with self._observe(
            messages, temperature=temperature, max_tokens=max_tokens, **kwargs
        ) as span:
            input_result = guardrails.check_input(messages)
            _telemetry_call(self._record_guardrail, span, "input", input_result)
            if input_result.action == "block":
                return None

            with self._span_context(span):
                result = await self._inner.chat_completion(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
            if result is None:
                if span is not None:
                    _telemetry_call(span.add_event, "gen_ai.provider.empty_result")
                return None

            choices = result.get("choices") or []
            content = str((choices[0].get("message") or {}).get("content") or "") if choices else ""
            if content:
                masked, output_result = guardrails.check_output(content)
                _telemetry_call(self._record_guardrail, span, "output", output_result)
                if output_result.action == "block":
                    return None
                if masked != content:
                    try:
                        result["choices"][0]["message"]["content"] = masked
                    except (IndexError, KeyError, TypeError):
                        pass

            if span is not None:
                _telemetry_call(telemetry.record_response, span, result, request_messages=messages)
        try:
            from app.infrastructure.llm.platform_billing_pass import record_platform_billing

            record_platform_billing(
                result,
                source=f"instrumented:{self.provider_id}",
                user_id=str(kwargs.get("user_id") or ""),
                run_id=str(kwargs.get("run_id") or ""),
            )
        except RECOVERABLE_ERRORS:
            pass
        return result

    async def stream_chat_completion(self, messages: list[dict[str, str]], **kwargs: Any):
        """增量透传给内层 provider；流式路径不重复做输出 guardrails。"""
        inner = getattr(self._inner, "stream_chat_completion", None)
        if inner is None:
            return
        with self._observe(messages, **kwargs) as span:
            stream = None
            chunks = characters = 0
            try:
                with self._span_context(span):
                    stream = aiter(inner(messages, **kwargs))
                while True:
                    try:
                        # Never hold context tokens across a yield to the consumer.
                        with self._span_context(span):
                            delta = await anext(stream)
                    except StopAsyncIteration:
                        break
                    chunks += 1
                    characters += len(delta) if isinstance(delta, str) else 0
                    yield delta
                if not chunks and span is not None:
                    _telemetry_call(span.add_event, "gen_ai.provider.empty_result")
            finally:
                if span is not None:
                    _telemetry_call(
                        span.attributes.update,
                        {
                            "gen_ai.request.stream": True,
                            "xcagi.stream.chunks": chunks,
                            "xcagi.stream.characters": characters,
                        },
                    )
                original_error = sys.exc_info()[1]
                close = getattr(stream, "aclose", None)
                if callable(close):
                    try:
                        with self._span_context(span):
                            await close()
                    except BOUNDARY_ERRORS + (asyncio.CancelledError,) as cleanup_error:
                        if original_error is None or (
                            isinstance(original_error, GeneratorExit)
                            and isinstance(cleanup_error, asyncio.CancelledError)
                        ):
                            raise
                        logger.warning("genai stream cleanup failed")

    @staticmethod
    @contextmanager
    def _span_context(span: telemetry.GenAISpan | None) -> Iterator[None]:
        scope = None
        try:
            if span is not None:
                scope = TraceContext(
                    span.trace_id,
                    span.span_id,
                    request_id=span.attributes.get("request_id"),
                    trace_flags=span.trace_flags,
                    trace_state=span.trace_state,
                )
                scope.__enter__()
        except BOUNDARY_ERRORS:
            if scope is not None:
                _telemetry_call(scope.__exit__, *sys.exc_info())
            scope = None
            logger.warning("genai context unavailable")
        try:
            yield
        finally:
            if scope is not None:
                _telemetry_call(scope.__exit__, *sys.exc_info())

    @contextmanager
    def _observe(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> Iterator[telemetry.GenAISpan | None]:
        def start():
            captured = (
                [
                    {**message, "content": redact_log_text(str(message.get("content") or ""))}
                    for message in messages
                ]
                if telemetry.capture_content()
                else messages
            )
            span = telemetry.start_genai_span(
                provider_id=self.provider_id,
                model=kwargs.get("model"),
                temperature=temperature,
                max_tokens=max_tokens,
                profile=self._profile,
                caller=_infer_caller(),
                tenant_id=kwargs.get("tenant_id"),
                messages=captured,
            )
            if request_id := get_trace_context().get("request_id"):
                span.attributes["request_id"] = request_id
            return span

        span = _telemetry_call(start)
        status = "ok"
        try:
            yield span
        except (asyncio.CancelledError, GeneratorExit) as exc:
            status = "cancelled"
            if span is not None:
                _telemetry_call(
                    span.attributes.update,
                    {
                        "error.type": type(exc).__name__,
                        "error.code": "llm_cancelled",
                        "xcagi.cancelled": True,
                    },
                )
            raise
        except BOUNDARY_ERRORS as exc:
            status = "error"
            if span is not None:
                _telemetry_call(span.attributes.update, {"error.code": "llm_call_failed"})
                _telemetry_call(telemetry.record_error, span, exc)
            raise
        finally:
            if span is not None:
                _telemetry_call(span.finish, status)
                self._persist(span)

    @staticmethod
    def _record_guardrail(span, phase: str, result) -> None:
        if span is None:
            return
        if result.action == "block":
            span.attributes["guardrail.blocked"] = True
        if result.hits:
            span.add_event(
                f"guardrail.{phase}",
                {
                    "guardrail.action": result.action,
                    "guardrail.score": result.score,
                    "guardrail.rules": [h["rule_id"] for h in result.hits],
                },
            )

    @staticmethod
    def _persist(span) -> None:
        try:
            if (
                span.end_time is not None
                and telemetry.trace_enabled()
                and telemetry.should_record(span)
            ):
                get_trace_store().record(span.to_dict())
        except BOUNDARY_ERRORS:
            logger.warning("genai trace persistence unavailable")


def wrap_provider(provider: LLMProvider, *, profile: str | None = None) -> LLMProvider:
    """按开关包裹 provider；双开关全关或已包裹时原样返回。"""
    if getattr(provider, "_xcagi_instrumented", False):
        return provider
    if not telemetry.trace_enabled() and not guardrails.guardrails_enabled():
        return provider
    return InstrumentedProvider(provider, profile=profile)
