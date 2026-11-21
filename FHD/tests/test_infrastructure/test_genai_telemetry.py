"""genai_telemetry 单元测试：属性规范 / 采样 / 内容脱敏 / neuro_bus 桥接。"""

from __future__ import annotations

import pytest

from app.infrastructure.llm import genai_telemetry as gt


def _setup_shared_0(monkeypatch):
    monkeypatch.setenv("XCAGI_GENAI_TRACE_SAMPLE_RATE", "0")
    span = gt.start_genai_span(
        provider_id="p",
        model=None,
        temperature=0.7,
        max_tokens=1,
        profile="d",
        caller=None,
        tenant_id=None,
        messages=[],
    )
    return span


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in list(__import__("os").environ):
        if key.startswith("XCAGI_GENAI_TRACE"):
            monkeypatch.delenv(key, raising=False)


class TestStartSpan:
    def test_start_span_has_otel_genai_attributes(self):
        span = gt.start_genai_span(
            provider_id="openai_compatible",
            model="deepseek-chat",
            temperature=0.1,
            max_tokens=300,
            profile="intent",
            caller="app.services.x",
            tenant_id=None,
            messages=[{"role": "user", "content": "你好"}],
        )
        a = span.attributes
        assert a["gen_ai.operation.name"] == "chat"
        assert a["gen_ai.system"] == "openai_compatible"
        assert a["gen_ai.request.model"] == "deepseek-chat"
        assert a["gen_ai.request.temperature"] == 0.1
        assert a["gen_ai.request.max_tokens"] == 300
        assert a["xcagi.profile"] == "intent"
        assert a["xcagi.caller"] == "app.services.x"
        assert span.trace_id and span.span_id

    def test_start_span_bridges_neuro_bus_trace(self):
        from app.neuro_bus.tracer import TraceContext

        with TraceContext(trace_id="biz-trace-1", span_id="biz-span-1"):
            span = gt.start_genai_span(
                provider_id="p",
                model=None,
                temperature=0.7,
                max_tokens=100,
                profile="default",
                caller=None,
                tenant_id=None,
                messages=[],
            )
        assert span.trace_id == "biz-trace-1"
        assert span.parent_span_id == "biz-span-1"


class TestContentDescriptor:
    def test_default_records_len_and_sha256_not_text(self, monkeypatch):
        monkeypatch.delenv("XCAGI_GENAI_TRACE_CAPTURE_CONTENT", raising=False)
        d = gt.content_descriptor("秘密内容")
        assert d["len"] == 4 and len(d["sha256"]) == 64
        assert "秘密内容" not in str(d)

    def test_capture_content_enabled_records_text(self, monkeypatch):
        monkeypatch.setenv("XCAGI_GENAI_TRACE_CAPTURE_CONTENT", "1")
        d = gt.content_descriptor("abc")
        assert d["text"] == "abc"


class TestRecordResponse:
    def test_usage_from_provider_response(self):
        span = gt.start_genai_span(
            provider_id="p",
            model="deepseek-chat",
            temperature=0.7,
            max_tokens=100,
            profile="default",
            caller=None,
            tenant_id=None,
            messages=[],
        )
        gt.record_response(
            span,
            {
                "choices": [{"finish_reason": "stop", "message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
        assert span.attributes["gen_ai.usage.input_tokens"] == 10
        assert span.attributes["gen_ai.usage.output_tokens"] == 5
        assert span.attributes["gen_ai.response.finish_reasons"] == ["stop"]
        assert span.attributes["xcagi.cost_usd"] == pytest.approx(
            10 / 1000 * 0.00014 + 5 / 1000 * 0.00028
        )

    def test_missing_usage_falls_back_to_estimator(self):
        span = gt.start_genai_span(
            provider_id="p",
            model="unknown-model",
            temperature=0.7,
            max_tokens=100,
            profile="default",
            caller=None,
            tenant_id=None,
            messages=[],
        )
        gt.record_response(
            span,
            {"choices": [{"message": {"content": "你好世界"}}]},
            request_messages=[{"role": "user", "content": "你好"}],
        )
        assert span.attributes["gen_ai.usage.input_tokens"] > 0
        assert span.attributes["gen_ai.usage.output_tokens"] > 0
        assert "xcagi.cost_usd" not in span.attributes  # 未知模型不计费


class TestSampling:
    def test_error_span_always_recorded(self, monkeypatch):
        span = _setup_shared_0(monkeypatch)
        span.finish("error")
        assert gt.should_record(span) is True

    def test_blocked_span_always_recorded(self, monkeypatch):
        span = _setup_shared_0(monkeypatch)
        span.attributes["guardrail.blocked"] = True
        span.finish("ok")
        assert gt.should_record(span) is True

    def test_sample_rate_zero_drops_normal_span(self, monkeypatch):
        span = _setup_shared_0(monkeypatch)
        span.finish("ok")
        assert gt.should_record(span) is False

    def test_trace_disabled(self, monkeypatch):
        monkeypatch.setenv("XCAGI_GENAI_TRACE_ENABLED", "0")
        assert gt.trace_enabled() is False


def test_duration_uses_monotonic_clock_and_error_finish_is_idempotent(monkeypatch):
    from types import SimpleNamespace

    ticks = [100_000_000]
    monkeypatch.setattr(
        gt, "time", SimpleNamespace(time=lambda: 1.0, perf_counter_ns=lambda: ticks[0])
    )
    span = gt.GenAISpan("s", "t", None, "chat", start_time=200.0)
    span._started_ns = ticks[0]
    ticks[0] += 25_000_000
    gt.record_error(span, ValueError("Bearer private-secret api_key=secret-key"))
    ticks[0] += 80_000_000
    span.finish()
    assert span.to_dict()["duration_ms"] == 25
    assert span.status == "error"
    assert "private-secret" not in str(span.attributes)
    assert "secret-key" not in str(span.attributes)
