"""工具执行 GenAI 语义约定 span 埋点测试。"""

from __future__ import annotations

import asyncio

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_OFF, ALWAYS_ON, ParentBased
from opentelemetry.trace import NoOpTracer, StatusCode, get_current_span

from app.infrastructure.observability import genai_spans
from app.neuro_bus.tracer import TraceContext, current_span, current_trace


@pytest.fixture
def exporter(monkeypatch):
    """构造内存 exporter，并让被测模块使用其 tracer。"""
    provider = TracerProvider(sampler=ALWAYS_ON)
    memory = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(memory))
    monkeypatch.setattr(genai_spans, "get_tracer", lambda: provider.get_tracer("test"))
    yield memory
    provider.shutdown()


def test_span_name_and_genai_attributes(exporter):
    with genai_spans.tool_call_span(
        tool_id="customers", action="create", node_id="node-1", run_id="run-1"
    ) as span:
        genai_spans.record_tool_result(span, {"success": True})

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
    with genai_spans.tool_call_span(tool_id="orders", action="list", node_id="node-2") as span:
        genai_spans.record_tool_result(span, {"success": True})

    span = exporter.get_finished_spans()[0]
    assert "gen_ai.agent.id" not in span.attributes
    assert span.attributes["gen_ai.tool.call.result"] == "success"


@pytest.mark.parametrize("exception_type", [ValueError, asyncio.CancelledError])
def test_exception_records_error_type_and_reraises(exporter, exception_type):
    before = current_trace.get(), current_span.get()
    with pytest.raises(exception_type):
        with genai_spans.tool_call_span(
            tool_id="customers", action="create", node_id="node-3", run_id="run-3"
        ):
            raise exception_type("password=do-not-export database secret")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].attributes["error.type"] == exception_type.__name__
    assert spans[0].attributes["gen_ai.tool.call.result"] == "error"
    assert spans[0].status.status_code == StatusCode.ERROR
    assert spans[0].events, "异常应作为 span 事件被记录"
    assert "do-not-export" not in str(spans[0].to_json())
    assert (current_trace.get(), current_span.get()) == before


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


def test_no_receipt_does_not_claim_business_success(exporter):
    with genai_spans.tool_call_span(tool_id="orders", action="list", node_id="n"):
        pass
    assert "gen_ai.tool.call.result" not in exporter.get_finished_spans()[0].attributes


def test_broken_tracer_does_not_prevent_business_or_replace_its_error(monkeypatch):
    def unavailable():
        raise RuntimeError("exporter unavailable")

    monkeypatch.setattr(genai_spans, "get_tracer", unavailable)
    business_error = ValueError("business error")
    with pytest.raises(ValueError) as caught:
        with genai_spans.tool_call_span(tool_id="orders", action="list", node_id="n") as span:
            assert span is None
            raise business_error
    assert caught.value is business_error


def test_attempt_is_current_parent_and_context_is_restored(exporter):
    tracer = genai_spans.get_tracer()
    before = current_trace.get(), current_span.get()
    with TraceContext("a" * 32, "b" * 16):
        with genai_spans.tool_call_span(tool_id="orders", action="list", node_id="n") as tool:
            assert current_span.get() == format(tool.get_span_context().span_id, "016x")
            with tracer.start_as_current_span("database read"):
                pass
            genai_spans.record_tool_result(tool, {"success": True})
        assert current_span.get() == "b" * 16
    database, tool = exporter.get_finished_spans()
    assert database.parent.span_id == tool.context.span_id
    assert tool.parent.span_id == int("b" * 16, 16)
    assert database.context.trace_id == tool.context.trace_id == int("a" * 32, 16)
    assert (current_trace.get(), current_span.get()) == before


def test_no_sdk_still_propagates_distinct_attempts(monkeypatch):
    monkeypatch.setattr(genai_spans, "get_tracer", lambda: NoOpTracer())
    spans = []
    with TraceContext("a" * 32, "b" * 16):
        for attempt in (1, 2):
            with genai_spans.tool_call_span(
                tool_id="orders", action="list", node_id="n", attempt=attempt
            ):
                context = get_current_span().get_span_context()
                assert context.is_valid and context.trace_id == int("a" * 32, 16)
                spans.append(context.span_id)
        assert current_span.get() == "b" * 16
    assert len(set(spans + [int("b" * 16, 16)])) == 3


def test_existing_otel_parent_is_preserved_without_neuro_context(exporter):
    with genai_spans.get_tracer().start_as_current_span("upstream") as parent:
        with genai_spans.tool_call_span(tool_id="orders", action="list", node_id="n") as tool:
            genai_spans.record_tool_result(tool, {"success": True})
    child = exporter.get_finished_spans()[0]
    assert child.context.trace_id == parent.get_span_context().trace_id
    assert child.parent.span_id == parent.get_span_context().span_id


def test_root_attempt_respects_sdk_sampling_without_fabricated_sampled_parent(monkeypatch):
    provider = TracerProvider(sampler=ALWAYS_OFF)
    monkeypatch.setattr(genai_spans, "get_tracer", lambda: provider.get_tracer("test"))
    try:
        with genai_spans.tool_call_span(tool_id="orders", action="list", node_id="n") as tool:
            assert not tool.get_span_context().trace_flags.sampled
            assert not get_current_span().get_span_context().trace_flags.sampled
    finally:
        provider.shutdown()


@pytest.fixture
def step_execution(monkeypatch):
    from types import SimpleNamespace

    from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.agent_orchestrator.run_usage import RunUsageLedger
    from app.application.agent_orchestrator.runtime_dependencies import RuntimeDependencies
    from app.application.agent_orchestrator.step_execution import StepExecution
    from app.application.agent_orchestrator.tool_spec import ToolActionSpecV2, ToolValidationResult

    def action_spec(tool_id, action):
        return ToolActionSpecV2(
            tool_id=tool_id,
            action=action,
            timeout_seconds=5,
            read_only=(tool_id, action) == ("observation_test", "read"),
        )

    dependencies = RuntimeDependencies(
        action_spec=action_spec,
        validate=lambda tool, action, _: ToolValidationResult(True, tool, action),
        refresh_budget=lambda _: None,
    )
    executor = SimpleNamespace()
    repository = InMemoryAgentRunRepository()
    execution = StepExecution(
        repository,
        executor,
        RunUsageLedger(dependencies),
        dependencies,
        attach_artifacts=lambda *_, **__: None,
        observe=lambda *_, **__: {"observation_id": "observation"},
    )
    run = AgentRun("u1", "read", metadata={"trace_id": "a" * 32, "span_id": "b" * 16})
    step = AgentStep(node_id="read", tool_id="observation_test", action="read", idempotent=True)
    run.steps.append(step)
    return execution, executor, run, step


def test_business_failure_then_retry_has_independent_correlated_spans(exporter, step_execution):
    execution, executor, run, step = step_execution
    outputs = iter(
        [{"success": False, "error_code": "upstream_busy"}, {"success": True, "data": [1]}]
    )
    received = []

    def execute(_step, *, runtime_context, deadline_monotonic):
        received.append((runtime_context, get_current_span().get_span_context()))
        return next(outputs)

    executor.execute_with_deadline = execute
    for _ in range(2):
        execution.execute_step(run, step, runtime_context={}, node_outputs={})
    failed, success = exporter.get_finished_spans()
    assert failed.status.status_code == StatusCode.ERROR
    assert failed.attributes["error.type"] == "upstream_busy"
    assert success.status.status_code == StatusCode.UNSET
    assert success.attributes["gen_ai.tool.call.result"] == "success"
    assert "error.type" not in success.attributes
    assert failed.context.span_id != success.context.span_id
    assert step.error == "" and step.status == "completed"
    for attempt, ((ctx, observed), span, call) in enumerate(
        zip(received, [failed, success], run.tool_calls), 1
    ):
        assert ctx["trace_id"] == call.metadata["trace_id"] == "a" * 32
        assert observed.span_id == span.context.span_id == int(call.metadata["span_id"], 16)
        call_events = [event for event in run.events if event.data.get("call_id") == call.call_id]
        assert [event.event_type for event in call_events] == [
            "tool.started",
            "verification.failed" if attempt == 1 else "verification.not_required",
            "tool.failed" if attempt == 1 else "tool.completed",
        ]
        assert call_events[1].data["verification"] == call.metadata["verification"]
        assert call.metadata["verification"]["accepted"] is (attempt == 2)
        assert call.metadata["verification_contract"]["read_only"] is True
        events = [call_events[0].data, call_events[2].data]
        for event in events:
            assert event["trace_id"] == "a" * 32
            assert event["span_id"] == call.metadata["span_id"]
            assert event["attempt"] == attempt
            assert event["action"] == "read" and event["step_id"] == step.step_id
        assert events[0]["duration_ms"] == 0
        assert events[1]["duration_ms"] == call.duration_ms >= 0
    assert (
        execution.repository.get(run.run_id).tool_calls[-1].metadata == run.tool_calls[-1].metadata
    )


def test_unverified_customer_receipt_marks_actual_attempt_failed(exporter, step_execution):
    execution, executor, run, step = step_execution
    step.tool_id, step.action = "customers", "create"
    executor.execute_with_deadline = lambda *_, **__: {"success": True, "id": "unverified"}
    execution.execute_step(run, step, runtime_context={}, node_outputs={})
    span = exporter.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["error.type"] == "customer_receipt_unverified"
    assert run.tool_calls[0].metadata["verification_contract"]["read_only"] is False
    assert run.tool_calls[0].metadata["verification"]["accepted"] is False
    assert run.events[-2].event_type == "verification.failed"
    assert run.events[-1].event_type == "tool.failed"
    assert run.metadata["non_retryable"] is True


def test_metrics_failure_cannot_change_completed_tool(exporter, step_execution, monkeypatch):
    execution, executor, run, step = step_execution
    executor.execute_with_deadline = lambda *_, **__: {"success": True, "data": [1]}

    def fail_metrics(**_):
        raise RuntimeError("metrics unavailable")

    monkeypatch.setattr(
        "app.application.agent_orchestrator.step_execution.observe_tool_call", fail_metrics
    )
    execution.execute_step(run, step, runtime_context={}, node_outputs={})
    assert step.status == "completed"
    completed = next(
        event for event in reversed(run.events) if event.event_type == "tool.completed"
    )
    assert completed.data["call_id"] == run.tool_calls[-1].call_id
    assert exporter.get_finished_spans()[0].attributes["gen_ai.tool.call.result"] == "success"


def test_unsampled_run_preserves_flags_and_state_in_attempt_and_worker_context(
    step_execution, monkeypatch
):
    execution, executor, run, step = step_execution
    run.metadata.update(trace_flags="00", trace_state="vendor=opaque")
    provider = TracerProvider(sampler=ParentBased(ALWAYS_ON))
    monkeypatch.setattr(genai_spans, "get_tracer", lambda: provider.get_tracer("test"))
    received = []

    def execute(_step, *, runtime_context, deadline_monotonic):
        received.append(runtime_context)
        active = get_current_span().get_span_context()
        assert not active.trace_flags.sampled
        assert active.trace_state.to_header() == "vendor=opaque"
        return {"success": True}

    executor.execute_with_deadline = execute
    try:
        execution.execute_step(run, step, runtime_context={}, node_outputs={})
    finally:
        provider.shutdown()
    for context in (received[0], run.tool_calls[0].metadata, run.events[-1].data):
        assert context["trace_flags"] == "00"
        assert context["trace_state"] == "vendor=opaque"
    assert step.status == "completed"
