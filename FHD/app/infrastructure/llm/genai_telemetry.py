"""GenAI (LLM) 调用遥测 — 属性命名对齐 OTel GenAI semantic conventions。

设计要点：
- 自研轻量 span，不强依赖 OTel SDK（OTLP 导出由 trace_store 负责）。
- 与 neuro_bus tracer 仅靠 trace_id 桥接，不合并。
- 消息内容默认只记 len + sha256；XCAGI_GENAI_TRACE_CAPTURE_CONTENT=1 记全文。
"""

from __future__ import annotations

import hashlib
import os
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

# 每千 token 美元费率（输入, 输出）；仅埋点估算，精细归因属批次 B
_MODEL_RATES_USD_PER_1K: dict[str, tuple[float, float]] = {
    "deepseek-chat": (0.00014, 0.00028),
    "deepseek-reasoner": (0.00055, 0.00219),
    "gpt-4o-mini": (0.00015, 0.0006),
}

_MAX_CAPTURED_CONTENT = 4096


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    try:
        return float(raw)
    except ValueError:
        return default


def trace_enabled() -> bool:
    return _env_flag("XCAGI_GENAI_TRACE_ENABLED", True)


def capture_content() -> bool:
    return _env_flag("XCAGI_GENAI_TRACE_CAPTURE_CONTENT", False)


def sample_rate() -> float:
    return max(0.0, min(1.0, _env_float("XCAGI_GENAI_TRACE_SAMPLE_RATE", 1.0)))


def content_descriptor(text: str) -> dict[str, Any]:
    """消息内容描述符：默认 len+sha256，开关打开时记全文（截断 4KB）。"""
    if capture_content():
        return {"text": text[:_MAX_CAPTURED_CONTENT], "len": len(text)}
    return {"len": len(text), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


@dataclass
class GenAISpan:
    """一次 LLM 调用的遥测 span。"""

    span_id: str
    trace_id: str
    parent_span_id: str | None
    name: str
    start_time: float
    end_time: float | None = None
    status: str = "ok"  # "ok" | "error"
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def finish(self, status: str = "ok") -> None:
        self.end_time = time.time()
        self.status = status

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self.events.append({"name": name, "timestamp": time.time(), "attributes": attributes or {}})

    def to_dict(self) -> dict[str, Any]:
        duration_ms = round((self.end_time - self.start_time) * 1000, 3) if self.end_time else None
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": duration_ms,
            "status": self.status,
            "attributes": self.attributes,
            "events": self.events,
        }


def _current_business_trace() -> tuple[str | None, str | None]:
    """桥接 neuro_bus 业务链路（不可用时静默返回 None）。"""
    try:
        from app.neuro_bus.tracer import current_span, current_trace

        return current_trace.get(), current_span.get()
    except RECOVERABLE_ERRORS:  # noqa: BLE001 — 桥接失败不阻断
        return None, None


def start_genai_span(
    *,
    provider_id: str,
    model: str | None,
    temperature: float,
    max_tokens: int,
    profile: str,
    caller: str | None,
    tenant_id: str | None,
    messages: list[dict[str, str]] | None,
) -> GenAISpan:
    trace_id, parent_span_id = _current_business_trace()
    span = GenAISpan(
        span_id=uuid.uuid4().hex[:16],
        trace_id=trace_id or uuid.uuid4().hex,
        parent_span_id=parent_span_id,
        name="chat",
        start_time=time.time(),
    )
    attrs = span.attributes
    attrs["gen_ai.operation.name"] = "chat"
    attrs["gen_ai.system"] = provider_id
    if model:
        attrs["gen_ai.request.model"] = model
    attrs["gen_ai.request.temperature"] = temperature
    attrs["gen_ai.request.max_tokens"] = max_tokens
    attrs["xcagi.profile"] = profile
    if caller:
        attrs["xcagi.caller"] = caller
    if tenant_id:
        attrs["xcagi.tenant_id"] = tenant_id
    for message in messages or []:
        role = str(message.get("role") or "user")
        span.add_event(
            f"gen_ai.{role}.message",
            {"content": content_descriptor(str(message.get("content") or ""))},
        )
    return span


def record_response(
    span: GenAISpan,
    result: dict[str, Any] | None,
    *,
    request_messages: list[dict[str, str]] | None = None,
) -> None:
    """从 OpenAI 兼容响应回填 usage / finish_reasons / 估算成本。"""
    result = result or {}
    choices = result.get("choices") or []
    if choices:
        reasons = [c.get("finish_reason") for c in choices if c.get("finish_reason")]
        if reasons:
            span.attributes["gen_ai.response.finish_reasons"] = reasons
    usage = result.get("usage") or {}
    input_tokens = usage.get("prompt_tokens")
    output_tokens = usage.get("completion_tokens")
    if input_tokens is None and request_messages:
        from app.infrastructure.llm.token_estimator import estimate_messages_tokens

        input_tokens = estimate_messages_tokens(request_messages)
    if output_tokens is None and choices:
        from app.infrastructure.llm.token_estimator import estimate_tokens

        content = str((choices[0].get("message") or {}).get("content") or "")
        output_tokens = estimate_tokens(content)
    if input_tokens is not None:
        span.attributes["gen_ai.usage.input_tokens"] = int(input_tokens)
    if output_tokens is not None:
        span.attributes["gen_ai.usage.output_tokens"] = int(output_tokens)
    cost = estimate_cost_usd(
        span.attributes.get("gen_ai.request.model"), input_tokens, output_tokens
    )
    if cost is not None:
        span.attributes["xcagi.cost_usd"] = round(cost, 8)


def estimate_cost_usd(
    model: str | None, input_tokens: int | None, output_tokens: int | None
) -> float | None:
    rates = _MODEL_RATES_USD_PER_1K.get(str(model or ""))
    if rates is None or input_tokens is None or output_tokens is None:
        return None
    return input_tokens / 1000 * rates[0] + output_tokens / 1000 * rates[1]


def record_error(span: GenAISpan, exc: BaseException) -> None:
    span.attributes["error.type"] = type(exc).__name__
    span.attributes["error.message"] = str(exc)[:500]
    span.finish("error")


def should_record(span: GenAISpan) -> bool:
    """采样决策：错误与 guardrail 拦截 span 永远保留。"""
    if span.status != "ok":
        return True
    if span.attributes.get("guardrail.blocked"):
        return True
    return random.random() < sample_rate()
