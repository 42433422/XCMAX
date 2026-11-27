"""GenAI (LLM) 调用遥测 — 属性命名对齐 OTel GenAI semantic conventions。

设计要点：
- 保留既有模型属性与 JSONL 视图，批处理、导出和关闭由 trace_store 的 OTel SDK 负责。
- 与工具及 NeuroBus 沿用同一 W3C trace/parent 身份和应用 SDK 生命周期。
- 消息内容默认只记 len + sha256；XCAGI_GENAI_TRACE_CAPTURE_CONTENT=1 记全文。
"""

from __future__ import annotations

import hashlib
import logging
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.utils.deployment import env_flag as _env_flag
from app.utils.deployment import env_float as _env_float
from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

# 每千 token 美元费率（输入, 输出）；仅埋点估算，精细归因属批次 B
_MODEL_RATES_USD_PER_1K: dict[str, tuple[float, float]] = {
    "deepseek-chat": (0.00014, 0.00028),
    "deepseek-reasoner": (0.00055, 0.00219),
    "gpt-4o-mini": (0.00015, 0.0006),
}

_MAX_CAPTURED_CONTENT = 4096
logger = logging.getLogger(__name__)


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
    trace_flags: str = "01"
    trace_state: str = ""
    _started_ns: int = field(default_factory=time.perf_counter_ns, init=False, repr=False)
    _duration_ms: float | None = field(default=None, init=False, repr=False)

    def finish(self, status: str = "ok") -> None:
        if self.end_time is not None:
            return
        self._duration_ms = round(max(0, time.perf_counter_ns() - self._started_ns) / 1_000_000, 3)
        self.end_time = time.time()
        if status == "ok" and (
            self.attributes.get("guardrail.blocked")
            or any(event["name"] == "gen_ai.provider.empty_result" for event in self.events)
        ):
            status = "error"
            self.attributes.setdefault("error.code", "llm_response_unavailable")
        self.status = status
        if self.name == "chat":
            try:
                from app.infrastructure.observability.metrics import observe_model_call

                observe_model_call(
                    source="provider",
                    status="success" if status == "ok" else status,
                    phases_ms={"total": self._duration_ms},
                )
            except BOUNDARY_ERRORS as exc:
                logger.warning("model metric observation unavailable (%s)", type(exc).__name__)

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self.events.append({"name": name, "timestamp": time.time(), "attributes": attributes or {}})

    def to_dict(self) -> dict[str, Any]:
        duration_ms = self._duration_ms
        if duration_ms is None and self.end_time is not None:
            duration_ms = round(max(0, self.end_time - self.start_time) * 1000, 3)
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "trace_flags": self.trace_flags,
            "trace_state": self.trace_state,
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
        from app.neuro_bus.tracer import get_trace_context

        context = get_trace_context()
        return context.get("trace_id"), context.get("span_id")
    except RECOVERABLE_ERRORS:
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
    from app.neuro_bus.tracer import get_trace_context

    propagation = get_trace_context()
    if propagation.get("trace_id") == span.trace_id:
        span.trace_flags = propagation.get("trace_flags", "01")
        span.trace_state = propagation.get("trace_state", "")
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
    from app.security.log_redaction import redact_log_text

    span.attributes["error.type"] = type(exc).__name__
    span.attributes["error.message"] = redact_log_text(str(exc))[:500]
    span.finish("error")


def should_record(span: GenAISpan) -> bool:
    """采样决策：错误与 guardrail 拦截 span 永远保留。"""
    if span.status != "ok":
        return True
    if span.attributes.get("guardrail.blocked"):
        return True
    return random.random() < sample_rate()


class ModelRequestObservation:
    """Observe the existing Responses request, without owning its execution state.

    HTTPcore supplies transport intervals. Header/body waits include both network
    and remote work; remote queue and inference remain explicitly unobserved.
    No context token survives an await/yield or crosses the SSE response task.
    """

    _TRANSPORT_PHASES = {
        "connect_tcp": "connect",
        "start_tls": "connect",
        "send_request_headers": "request_send",
        "send_request_body": "request_send",
        "receive_response_headers": "response_wait",
        "receive_response_body": "response_read",
    }

    def __init__(
        self,
        *,
        context: dict[str, str],
        run_id: str,
        provider_id: str,
        model: str,
        request_group: str,
    ) -> None:
        self.span = GenAISpan(
            span_id=uuid.uuid4().hex[:16],
            trace_id=context["trace_id"],
            parent_span_id=context.get("span_id"),
            name="responses",
            start_time=time.time(),
            trace_flags=context.get("trace_flags", "00"),
            trace_state=context.get("trace_state", ""),
            attributes={
                "gen_ai.operation.name": "responses",
                "gen_ai.system": provider_id,
                "gen_ai.request.model": model,
                "xcagi.run_id": run_id,
                "xcagi.request_group": request_group,
                "xcagi.source": "xiaox.model_gateway",
                "xcagi.timing_scope": "gateway_request_including_retries",
                "xcagi.remote_queue_timing": "unavailable",
                "xcagi.inference_timing": "unavailable",
            },
        )
        self.phases_ms: dict[str, float] = {}
        self._started: dict[str, tuple[str, int]] = {}
        self.outcome = "unknown"

    def attempt(self, request_id: str, attempt: int) -> None:
        self.outcome = "unknown"
        self.span.add_event(
            "gen_ai.request.attempt", {"request_id": request_id, "attempt": attempt}
        )

    def settle(self, *, usage: dict[str, int] | None, state: str) -> None:
        self.outcome = (
            "unknown" if usage is None else "success" if state == "completed" else "error"
        )

    def add_duration(self, phase: str, duration_ms: float) -> None:
        self.phases_ms[phase] = self.phases_ms.get(phase, 0.0) + max(0.0, duration_ms)

    async def transport_trace(self, event_name: str, _info: dict[str, Any]) -> None:
        # Never capture the callback's headers, URL, exception text or stream.
        parts = event_name.split(".")
        if len(parts) != 3 or parts[1] not in self._TRANSPORT_PHASES:
            return
        key = ".".join(parts[:2])
        if parts[2] == "started":
            self._started[key] = (self._TRANSPORT_PHASES[parts[1]], time.perf_counter_ns())
        elif parts[2] in {"complete", "failed"} and key in self._started:
            phase, started = self._started.pop(key)
            self.add_duration(phase, (time.perf_counter_ns() - started) / 1_000_000)

    def headers(self) -> dict[str, str]:
        span = self.span
        headers = {"traceparent": f"00-{span.trace_id}-{span.span_id}-{span.trace_flags}"}
        if span.trace_state:
            headers["tracestate"] = span.trace_state
        return headers

    def snapshot(self) -> dict[str, Any]:
        duration = self.span._duration_ms
        if duration is None:
            duration = max(0, time.perf_counter_ns() - self.span._started_ns) / 1_000_000
        return {
            "trace_id": self.span.trace_id,
            "span_id": self.span.span_id,
            "parent_span_id": self.span.parent_span_id,
            "duration_ms": round(duration, 3),
            "phases_ms": {**self.phases_ms, "total": round(duration, 3)},
            "timing_scope": "gateway_request_including_retries",
            "final": self.span.end_time is not None,
            "group_outcome": self.outcome,
            "remote_queue_ms": None,
            "inference_ms": None,
        }

    def finish(self, error: BaseException | None = None) -> None:
        if self.span.end_time is not None:
            return
        if error is not None:
            self.outcome = (
                "cancelled"
                if type(error).__name__ in {"CancelledError", "GeneratorExit"}
                else "error"
            )
            self.span.attributes["error.type"] = type(error).__name__
        if self.outcome != "success":
            self.span.attributes["error.code"] = "model_request_" + self.outcome
        self.span.attributes["xcagi.outcome"] = self.outcome
        self.span.finish(
            "ok"
            if self.outcome == "success"
            else "cancelled"
            if self.outcome == "cancelled"
            else "error"
        )
        snapshot = self.snapshot()
        for phase, duration in snapshot["phases_ms"].items():
            self.span.attributes[f"xcagi.phase.{phase}_ms"] = duration
        try:
            from app.infrastructure.observability.metrics import observe_model_call

            observe_model_call(source="xiaox", status=self.outcome, phases_ms=snapshot["phases_ms"])
        except BOUNDARY_ERRORS as exc:
            logger.warning("model metric observation unavailable (%s)", type(exc).__name__)
        try:
            if trace_enabled() and should_record(self.span):
                from app.infrastructure.llm.trace_store import get_trace_store

                get_trace_store().record(self.span.to_dict())
        except BOUNDARY_ERRORS as exc:
            logger.warning("model trace observation unavailable (%s)", type(exc).__name__)
