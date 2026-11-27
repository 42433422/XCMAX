from __future__ import annotations

import pytest

from app.application.agent_orchestrator.chat_trace import _resolved_user_id
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.task_context import apply_task_context


def test_task_context_keeps_conversation_separate_from_task_and_tracks_workspace() -> None:
    run = AgentRun(user_id="7", message="请核对本月销售并提交报告")

    result = apply_task_context(
        run,
        {
            "conversation_id": "conv-sales",
            "workspace_id": "tenant-3-sales",
            "worktree_path": "/workspace/sales-report",
            "task_title": "本月销售报告",
        },
    )

    assert result["task_id"] == run.run_id
    assert result["conversation_id"] == "conv-sales"
    assert result["title"] == "本月销售报告"
    assert result["workspace_id"] == "tenant-3-sales"
    assert result["workspace_path"] == "/workspace/sales-report"
    assert result["isolation"] == "worktree"
    assert run.metadata["task_context"] == result


def test_explicit_business_task_and_turn_identity_survive_approval_attempts() -> None:
    first = AgentRun(user_id="7", message="新增客户")
    second = AgentRun(user_id="7", message="审批后继续")
    context = {
        "conversation_id": "conv-sales",
        "turn_id": "turn-create-customer",
        "task_id": "task-create-customer",
    }

    first_context = apply_task_context(first, context)
    second_context = apply_task_context(second, {**context, "task_attempt": 2})

    assert first_context["conversation_id"] == second_context["conversation_id"]
    assert first_context["task_id"] == second_context["task_id"]
    assert first_context["turn_id"] == second_context["turn_id"]
    assert second_context["attempt"] == 2


def test_authenticated_actor_owns_trace_instead_of_client_scoped_user_id() -> None:
    resolved = _resolved_user_id(
        runtime_context={"local_user_id": 73, "actor_id": 73},
        user_id="web_normal_untrusted-session",
    )

    assert resolved == "73"


def test_trace_identity_survives_roundtrip_and_different_resume_request() -> None:
    from app.application.agent_orchestrator.run_models import agent_run_from_dict
    from app.application.agent_orchestrator.task_context import observe_run_phase
    from app.neuro_bus.tracer import TraceContext, get_trace_context

    with TraceContext("1" * 32, "2" * 16, request_id="request-original"):
        run = AgentRun(user_id="owner", message="execute")
        apply_task_context(run, {"task_id": "task-1", "trace_id": "untrusted-client-id"})
        created = run.add_event("run.created")
    restored = agent_run_from_dict(run.to_dict())
    with TraceContext("3" * 32, "4" * 16, request_id="request-resume"):
        with observe_run_phase(restored, "execution"):
            event = restored.add_event("tool.started", data={"trace_id": "wrong"})
            assert get_trace_context()["trace_id"] == "1" * 32
        assert get_trace_context()["trace_id"] == "3" * 32
    assert created.data["trace_id"] == event.data["trace_id"] == "1" * 32
    assert event.data["task_id"] == "task-1"
    assert event.data["request_id"] == "request-resume"
    assert restored.metadata["trace_id"] == run.metadata["trace_id"]
    assert event.data["span_id"] != created.data["span_id"]


def test_active_duration_accumulates_segments_without_approval_wait(monkeypatch) -> None:
    from app.application.agent_orchestrator.run_models import agent_run_from_dict
    from app.application.agent_orchestrator.task_context import observe_run_phase

    run = AgentRun(user_id="owner", message="execute")
    with observe_run_phase(run, "execution"):
        run.status = "waiting_user"
    first = run.metadata["active_duration_ms"]
    restored = agent_run_from_dict(run.to_dict())
    monkeypatch.setattr("app.neuro_bus.tracer.time.time", lambda: 1.0)
    with observe_run_phase(restored, "execution"):
        restored.status = "completed"
    observed = restored.events[-1].data
    assert run.events[-1].data["status"] == "waiting_user"
    assert observed["status"] == "completed"
    assert observed["duration_scope"] == "active"
    assert 0 <= observed["phase_duration_ms"] < 1000
    assert abs(observed["duration_ms"] - first - observed["phase_duration_ms"]) < 0.002


def test_phase_observation_preserves_original_exception_and_restores_context() -> None:
    import pytest

    from app.application.agent_orchestrator.task_context import observe_run_phase
    from app.neuro_bus.tracer import get_trace_context

    before = get_trace_context()
    run = AgentRun(user_id="owner", message="execute")
    failure = RuntimeError("password=do-not-log")
    with pytest.raises(RuntimeError) as caught, observe_run_phase(run, "planning"):
        raise failure
    assert caught.value is failure
    assert get_trace_context() == before
    observed = run.events[-1].data
    assert observed["error_code"] == "agent_phase_failed"
    assert observed["error_type"] == "RuntimeError"
    assert "do-not-log" not in str(observed)
    assert observed["duration_ms"] >= 0


@pytest.mark.parametrize("status", ["unknown", "timed_out"])
def test_uncertain_or_expired_phase_does_not_export_success(monkeypatch, status):
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from app.application.agent_orchestrator.task_context import observe_run_phase

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        "app.infrastructure.llm.trace_store.get_runtime_tracer",
        lambda *args, **kwargs: provider.get_tracer("test"),
    )
    try:
        run = AgentRun(
            user_id="owner",
            message="execute",
            metadata={"trace_id": "a" * 32, "span_id": "b" * 16, "trace_flags": "01"},
        )
        with observe_run_phase(run, "execution"):
            run.status = status
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].status.status_code == trace.StatusCode.ERROR
        assert run.status == run.events[-1].data["status"] == status
        assert run.events[-1].data["error_code"] == "agent_run_" + status
    finally:
        provider.shutdown()


def test_legacy_runs_keep_exact_cas_snapshots_when_adding_observations() -> None:
    import copy

    from app.application.agent_orchestrator.run_lifecycle import RunLifecycleMixin
    from app.application.agent_orchestrator.run_sql_repository import (
        valid_control_update,
        valid_stream_tool_audit_update,
    )

    previous = AgentRun(user_id="owner", message="legacy", status="running")
    for action in ("pause", "cancel"):
        candidate = copy.deepcopy(previous)
        RunLifecycleMixin._mark_controlled(candidate, action)
        if action == "pause":
            candidate.metadata["control"]["resume_status"] = "running"
        assert valid_control_update(candidate, previous)
        assert "trace_id" not in candidate.metadata
    candidate = copy.deepcopy(previous)
    candidate.metadata["stream_tool_audit"] = [{"sequence": 1}]
    candidate.add_event("tool.receipt_observed")
    assert valid_stream_tool_audit_update(candidate, previous)
    assert "trace_id" not in candidate.metadata


def test_observation_failure_cannot_mask_business_result_or_exception(monkeypatch) -> None:
    import pytest

    from app.application.agent_orchestrator.task_context import observe_run_phase
    from app.neuro_bus.tracer import NeuroTracer, get_trace_context

    run = AgentRun(user_id="owner", message="execute")
    before = get_trace_context()

    def broken(*args, **kwargs):
        raise TypeError("telemetry unavailable")

    with monkeypatch.context() as scoped:
        scoped.setattr(NeuroTracer, "start_span", broken)
        with observe_run_phase(run, "execution"):
            run.status = "completed"
        failure = ValueError("business failure")
        with pytest.raises(ValueError) as caught, observe_run_phase(run, "execution"):
            raise failure
        assert caught.value is failure
    monkeypatch.setattr(run, "add_event", broken)
    with observe_run_phase(run, "execution"):
        run.status = "completed"
    assert run.status == "completed"
    assert get_trace_context() == before


def test_malformed_old_observation_metadata_does_not_interrupt_execution() -> None:
    from app.application.agent_orchestrator.task_context import observe_run_phase

    run = AgentRun(
        user_id="owner",
        message="legacy",
        metadata={
            "task_context": ["old-format"],
            "active_duration_ms": "unknown",
        },
    )
    with observe_run_phase(run, "execution"):
        run.status = "completed"
    assert run.events[-1].data["status"] == "completed"
    assert run.metadata["active_duration_ms"] >= 0


def test_legacy_nonstandard_ids_have_stable_readonly_canonical_observations() -> None:
    from app.application.agent_orchestrator.task_context import ensure_run_trace, observe_run_phase

    run = AgentRun(
        user_id="owner",
        message="legacy",
        metadata={
            "trace_id": "old-trace",
            "span_id": "old-span",
        },
    )
    original = dict(run.metadata)
    context = ensure_run_trace(run, live=False)
    assert len(context["trace_id"]) == 32 and int(context["trace_id"], 16) > 0
    assert len(context["span_id"]) == 16 and int(context["span_id"], 16) > 0
    assert context["trace_flags"] == "00"
    assert ensure_run_trace(run, live=False) == context
    assert run.metadata == original
    assert run.to_dict()["trace_id"] == context["trace_id"]
    with observe_run_phase(run, "execution"):
        event = run.add_event("tool.started")
    assert event.data["trace_id"] == context["trace_id"]
    assert run.metadata["trace_id"] == original["trace_id"]
    assert run.metadata["span_id"] == original["span_id"]


def test_background_task_retains_sdk_unsampled_decision(monkeypatch) -> None:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.sampling import ALWAYS_OFF

    from app.application.agent_orchestrator.task_context import observe_run_phase
    from app.neuro_bus.tracer import get_trace_context

    provider = TracerProvider(sampler=ALWAYS_OFF)
    monkeypatch.setattr(trace, "get_tracer", lambda *args, **kwargs: provider.get_tracer("test"))
    try:
        run = AgentRun(user_id="owner", message="background")
        apply_task_context(run, {})
        assert int(run.metadata["trace_flags"], 16) & 1 == 0
        with observe_run_phase(run, "execution"):
            assert int(get_trace_context()["trace_flags"], 16) & 1 == 0
    finally:
        provider.shutdown()


def test_task_creation_survives_observation_failure_and_cancel_is_distinct(monkeypatch) -> None:
    import asyncio

    import pytest

    from app.application.agent_orchestrator.task_context import observe_run_phase
    from app.neuro_bus.tracer import NeuroTracer

    run = AgentRun(user_id="owner", message="background")
    with monkeypatch.context() as scoped:

        def broken(*args, **kwargs):
            raise TypeError("telemetry unavailable")

        scoped.setattr(NeuroTracer, "start_span", broken)
        apply_task_context(run, {})
        assert len(run.metadata["trace_id"]) == 32
    cancelled = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError) as caught, observe_run_phase(run, "execution"):
        raise cancelled
    assert caught.value is cancelled
    assert run.events[-1].data["error_code"] == "agent_phase_cancelled"
    assert run.events[-1].data["error_type"] == "CancelledError"
