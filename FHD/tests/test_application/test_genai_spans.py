"""工具执行 GenAI 语义约定 span 埋点测试。"""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import NoOpTracer

from app.infrastructure.observability import genai_spans


@pytest.fixture
def exporter(monkeypatch):
    """构造内存 exporter，并让被测模块使用其 tracer。"""
    provider = TracerProvider()
    memory = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(memory))
    monkeypatch.setattr(genai_spans, "get_tracer", lambda: provider.get_tracer("test"))
    return memory


def test_span_name_and_genai_attributes(exporter):
    with genai_spans.tool_call_span(
        tool_id="customers", action="create", node_id="node-1", run_id="run-1"
    ):
        pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "execute_tool customers.create"
    assert span.attributes["gen_ai.operation.name"] == "execute_tool"
    assert span.attributes["gen_ai.tool.name"] == "customers"
    assert span.attributes["gen_ai.tool.call.id"] == "node-1"
    assert span.attributes["gen_ai.agent.id"] == "run-1"
    assert span.attributes["gen_ai.tool.call.result"] == "success"
    assert "error.type" not in span.attributes


def test_agent_id_omitted_without_run_id(exporter):
    with genai_spans.tool_call_span(tool_id="orders", action="list", node_id="node-2", run_id=None):
        pass

    span = exporter.get_finished_spans()[0]
    assert "gen_ai.agent.id" not in span.attributes
    assert span.attributes["gen_ai.tool.call.result"] == "success"


def test_exception_records_error_type_and_reraises(exporter):
    with pytest.raises(ValueError):
        with genai_spans.tool_call_span(
            tool_id="customers", action="create", node_id="node-3", run_id="run-3"
        ):
            raise ValueError("boom")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].attributes["error.type"] == "ValueError"
    assert "gen_ai.tool.call.result" not in spans[0].attributes
    assert spans[0].events, "异常应作为 span 事件被记录"


def test_noop_when_tracer_not_configured(monkeypatch):
    """未初始化 OTel（NoOpTracer）时上下文管理器必须静默通过。"""
    monkeypatch.setattr(genai_spans, "get_tracer", lambda: NoOpTracer())
    with genai_spans.tool_call_span(
        tool_id="customers", action="create", node_id="node-4", run_id="run-4"
    ) as span:
        assert span is not None


def test_noop_when_tracer_absent(monkeypatch):
    """tracer 缺失时也不得抛错，且不吞掉业务异常。"""
    monkeypatch.setattr(genai_spans, "get_tracer", lambda: None)
    with genai_spans.tool_call_span(
        tool_id="customers", action="create", node_id="node-5", run_id="run-5"
    ) as span:
        assert span is None

    with pytest.raises(RuntimeError):
        with genai_spans.tool_call_span(
            tool_id="customers", action="create", node_id="node-6", run_id="run-6"
        ):
            raise RuntimeError("boom")
