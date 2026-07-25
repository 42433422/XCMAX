"""InstrumentedProvider — 在 LLMProvider 外包遥测 + Guardrails 的装饰层。

包裹点：``LLMProviderRegistry.get()/resolve()`` 返回处（见 registry.py）。
顺序（spec §3.1）：开 span → 输入检查 → 真实调用 → 输出检查 → 落盘。
"""

from __future__ import annotations

import inspect
import logging
from typing import Any

from app.infrastructure.llm import genai_telemetry as telemetry
from app.infrastructure.llm import guardrails
from app.infrastructure.llm.providers.base import LLMProvider
from app.infrastructure.llm.trace_store import get_trace_store
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


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
    def provider_id(self) -> str:
        return self._inner.provider_id

    @property
    def is_configured(self) -> bool:
        return self._inner.is_configured

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        span = telemetry.start_genai_span(
            provider_id=self.provider_id,
            model=kwargs.get("model"),
            temperature=temperature,
            max_tokens=max_tokens,
            profile=self._profile,
            caller=_infer_caller(),
            tenant_id=kwargs.get("tenant_id"),
            messages=messages,
        )
        try:
            input_result = guardrails.check_input(messages)
            self._record_guardrail(span, "input", input_result)
            if input_result.action == "block":
                span.attributes["guardrail.blocked"] = True
                span.finish("ok")
                self._persist(span)
                return None

            try:
                result = await self._inner.chat_completion(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
            except RECOVERABLE_ERRORS as exc:
                telemetry.record_error(span, exc)
                self._persist(span)
                raise

            if result is None:
                span.add_event("gen_ai.provider.empty_result")
                span.finish("ok")
                self._persist(span)
                return None

            choices = result.get("choices") or []
            content = str((choices[0].get("message") or {}).get("content") or "") if choices else ""
            if content:
                masked, output_result = guardrails.check_output(content)
                self._record_guardrail(span, "output", output_result)
                if output_result.action == "block":
                    span.attributes["guardrail.blocked"] = True
                    span.finish("ok")
                    self._persist(span)
                    return None
                if masked != content:
                    try:
                        result["choices"][0]["message"]["content"] = masked
                    except (IndexError, KeyError, TypeError):
                        pass

            telemetry.record_response(span, result, request_messages=messages)
            span.finish("ok")
            self._persist(span)
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
        except RECOVERABLE_ERRORS:
            raise
        except Exception:  # noqa: BLE001 — 装饰层自身异常不得阻断业务
            logger.error("instrumented provider failure, passthrough", exc_info=True)
            return await self._inner.chat_completion(
                messages, temperature=temperature, max_tokens=max_tokens, **kwargs
            )

    @staticmethod
    def _record_guardrail(span, phase: str, result) -> None:
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
        if not telemetry.trace_enabled():
            return
        if telemetry.should_record(span):
            get_trace_store().record(span.to_dict())


def wrap_provider(provider: LLMProvider, *, profile: str | None = None) -> LLMProvider:
    """按开关包裹 provider；双开关全关或已包裹时原样返回。"""
    if getattr(provider, "_xcagi_instrumented", False):
        return provider
    if not telemetry.trace_enabled() and not guardrails.guardrails_enabled():
        return provider
    return InstrumentedProvider(provider, profile=profile)
