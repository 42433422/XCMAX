"""Real repository readback using isolated in-memory and temporary SQLite stores."""

import asyncio
import copy
import importlib.util
import threading
import time
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator import run_sql_repository as installed_sql
from app.application.agent_orchestrator.run_models import AgentRun
from tests.test_application.test_chat_stream_lifetime import (
    bind_entrypoint_modules,
    ROOT,
    bridge,
    extract,
    life,
    wait,
)


@pytest.fixture(autouse=True)
def source_bindings(monkeypatch):
    bind_entrypoint_modules(monkeypatch)


def load_source(name):
    path = ROOT / "app/application/agent_orchestrator" / (name + ".py")
    spec = importlib.util.spec_from_file_location("isolated_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def repositories(monkeypatch):
    sql = load_source("run_sql_repository")
    monkeypatch.setattr(
        installed_sql,
        "valid_stream_interruption_update",
        sql.valid_stream_interruption_update,
        raising=False,
    )
    monkeypatch.setattr(
        installed_sql, "valid_control_update", sql.valid_control_update, raising=False
    )
    monkeypatch.setattr(
        installed_sql,
        "valid_stream_tool_audit_update",
        sql.valid_stream_tool_audit_update,
        raising=False,
    )
    memory = load_source("run_repository")
    return memory.InMemoryAgentRunRepository, sql.SQLAlchemyAgentRunRepository


def observer(repo):
    return extract(
        "app/application/agent_orchestrator/chat_trace.py",
        "mark_chat_stream_interrupted",
        {
            "get_agent_run_repository": lambda: repo,
        },
    )


def initial(repo):
    return repo.save(
        AgentRun(
            user_id="synthetic-owner",
            message="synthetic read",
            status="running",
            metadata={
                "runtime_context": {
                    "tenant_id": "tenant-a",
                    "_mod_authorization": {"mod_id": "mod-a"},
                    "turn_id": "turn-a",
                },
                "cost_units_total": 17,
            },
            final_output={
                "receipt": {"committed": True, "id": "existing-write"},
                "cost_units_total": 17,
            },
        )
    )


@pytest.mark.parametrize("field", ["terminal", "owner", "tenant", "mod", "turn", "created_at"])
def test_observer_never_overwrites_real_terminal_or_replaced_owner(repositories, field):
    repo = repositories[0]()
    expected = initial(repo)
    newer = copy.deepcopy(expected)
    if field == "terminal":
        newer.status = "completed"
    elif field == "owner":
        newer.user_id = "new-owner"
    elif field == "created_at":
        newer.created_at = "next-generation"
    elif field == "mod":
        newer.metadata["runtime_context"]["_mod_authorization"]["mod_id"] = "new-mod"
    else:
        newer.metadata["runtime_context"][{"tenant": "tenant_id", "turn": "turn_id"}[field]] = "new"
    repo.save(newer)
    before = repo.get(expected.run_id).to_dict()
    observer(repo)(expected, pending=False, reason="consumer_closed")
    assert repo.get(expected.run_id).to_dict() == before


def test_unknown_readback_preserves_receipt_cost_and_later_real_completion(repositories):
    repo = repositories[0]()
    expected = initial(repo)
    mark = observer(repo)
    mark(expected, pending=True, reason="consumer_closed")
    current = repo.get(expected.run_id)
    assert current.status == "running"
    assert current.metadata["stream_interruption"]["worker_pending"] is True
    mark(expected, pending=False, reason="consumer_closed")
    current = repo.get(expected.run_id)
    assert current.status == "blocked"
    assert current.final_output["receipt"] == expected.final_output["receipt"]
    assert current.final_output["cost_units_total"] == 17
    assert current.metadata["cost_units_total"] == 17
    assert current.metadata["stream_interruption"]["business_outcome"] == "unknown"
    assert len(repo.list_events(expected.run_id)) == 2
    mark(expected, pending=True, reason="consumer_closed")
    assert repo.get(expected.run_id).metadata["stream_interruption"]["worker_pending"] is False
    current.status = "completed"
    current.final_output["confirmed_later"] = True
    repo.save(current)
    before = repo.get(expected.run_id).to_dict()
    mark(expected, pending=False, reason="consumer_closed")
    assert repo.get(expected.run_id).to_dict() == before


@pytest.mark.asyncio
async def test_worker_accounting_keeps_inflight_business_visible_then_unknown(repositories):
    repo = repositories[0]()
    expected = initial(repo)
    mark = observer(repo)
    entered, release, finished = (threading.Event() for _ in range(3))
    writes = []

    def producer(*a, **k):
        life.watch_stream_interruption(
            lambda **state: mark(expected, **state), run_snapshot=expected
        )
        try:
            yield b"run-id-already-delivered"
            writes.append("committed-once")
            entered.set()
            assert release.wait(2)
            yield b"late"
        finally:
            finished.set()

    stream = bridge(producer)
    await anext(stream)
    await wait(entered)
    await stream.aclose()
    deadline = time.monotonic() + 1
    while (
        not repo.get(expected.run_id).metadata.get("stream_interruption")
        and time.monotonic() < deadline
    ):
        await asyncio.sleep(0.01)
    assert repo.get(expected.run_id).status == "running"
    assert repo.get(expected.run_id).metadata["stream_interruption"]["worker_pending"] is True
    release.set()
    await wait(finished)
    deadline = time.monotonic() + 1
    while repo.get(expected.run_id).status != "blocked" and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    assert repo.get(expected.run_id).status == "blocked"
    assert writes == ["committed-once"]
    assert repo.get(expected.run_id).final_output["receipt"] == expected.final_output["receipt"]


def test_registration_after_workers_exit_and_concurrent_last_workers(repositories):
    repo = repositories[0]()
    expected = initial(repo)
    mark = observer(repo)
    lifetime = life.StreamLifetime()
    lifetime.worker_started()
    lifetime.worker_started()
    lifetime.cancel()
    threads = [threading.Thread(target=lifetime.worker_finished) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(1)
    lifetime.observe(lambda **state: mark(expected, **state))
    assert repo.get(expected.run_id).status == "blocked"
    assert len(repo.list_events(expected.run_id)) == 1


def test_sql_cas_with_two_connections_preserves_new_terminal_and_audit_fields(
    repositories, tmp_path
):
    path = tmp_path / "isolated-runs.sqlite"
    first_engine = create_engine(f"sqlite:///{path}")
    second_engine = create_engine(f"sqlite:///{path}")
    first = repositories[1](session_factory=sessionmaker(bind=first_engine))
    second = repositories[1](session_factory=sessionmaker(bind=second_engine))
    expected = initial(first)
    mark = observer(first)
    second._ensure_schema()
    raced = []

    def finish_before_conditional_update(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE agent_runs") and not raced:
            raced.append(True)
            current = second.get(expected.run_id)
            current.status = "completed"
            current.final_output["confirmed_from_other_connection"] = True
            current.metadata["audit_added_elsewhere"] = "retained"
            second.save(current)

    event.listen(first_engine, "before_cursor_execute", finish_before_conditional_update)
    try:
        mark(expected, pending=False, reason="consumer_closed")
        result = second.get(expected.run_id)
        assert raced == [True]
        assert result.status == "completed"
        assert result.final_output["confirmed_from_other_connection"] is True
        assert result.metadata["audit_added_elsewhere"] == "retained"
        assert "stream_interruption" not in result.metadata
    finally:
        first_engine.dispose()
        second_engine.dispose()


def test_sql_unknown_readback_and_cas_does_not_drop_concurrent_audit(repositories, tmp_path):
    path = tmp_path / "isolated-audit.sqlite"
    engines = [create_engine(f"sqlite:///{path}") for _ in range(2)]
    first, second = [
        repositories[1](session_factory=sessionmaker(bind=engine)) for engine in engines
    ]
    expected = initial(first)
    second._ensure_schema()
    raced = []

    def audit_before_update(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE agent_runs") and not raced:
            raced.append(True)
            current = second.get(expected.run_id)
            current.metadata["concurrent_audit"] = "keep"
            second.save(current)

    event.listen(engines[0], "before_cursor_execute", audit_before_update)
    try:
        observer(first)(expected, pending=False, reason="consumer_closed")
        fresh = second.get(expected.run_id)
        assert fresh.status == "blocked"
        assert fresh.metadata["concurrent_audit"] == "keep"
        assert fresh.final_output["receipt"] == expected.final_output["receipt"]
        assert fresh.metadata["stream_interruption"]["replay_allowed"] is False
    finally:
        for engine in engines:
            engine.dispose()


@pytest.mark.parametrize("pending", [False, True])
def test_actual_retry_resume_and_background_recovery_refuse_unverified_interruption(
    repositories, pending
):
    from app.application.agent_orchestrator.run_lifecycle import (
        RunLifecycleMixin,
        requires_retry_reconciliation,
    )
    from app.application.agent_orchestrator.unified_task import task_capabilities

    background = load_source("task_background")
    repo = repositories[0]()
    expected = initial(repo)
    observer(repo)(expected, pending=pending, reason="consumer_closed")
    marked = repo.get(expected.run_id)
    assert requires_retry_reconciliation(marked)
    assert task_capabilities(marked)["retry"] is False
    attempts = []

    class Runner(RunLifecycleMixin, background.BackgroundTaskExecutionMixin):
        def start_run(self, **kwargs):
            attempts.append("replayed")
            pytest.fail("unknown execution must not start another billed/write run")

        def _execute_with_durable_lease(self, *args, **kwargs):
            attempts.append("executed")
            pytest.fail("unknown execution must not resume/recover")

    runner = Runner()
    runner._repo = repo
    with pytest.raises(ValueError, match="人工核对"):
        runner.retry_run(expected.run_id, requested_by=expected.user_id)
    # Background recovery must not infer safety merely because no running steps
    # were captured by the interrupted legacy stream.
    assert runner._prepare_expired_execution_recovery(marked) is False
    runner.execute_dispatched_run(expected.run_id, recovered=True)
    runner.execute_dispatched_run(expected.run_id, recovered=False)
    marked.status = "paused"
    repo.save(marked)
    with pytest.raises(ValueError, match="人工核对"):
        runner.resume_run(expected.run_id, requested_by=expected.user_id)
    with pytest.raises(ValueError, match="人工核对"):
        runner.stage_resume_run(expected.run_id, requested_by=expected.user_id)
    assert attempts == []
    assert repo.get(expected.run_id).final_output["receipt"] == expected.final_output["receipt"]


def test_normal_failed_read_only_run_still_retries_and_recovers(repositories):
    from app.application.agent_orchestrator.run_lifecycle import (
        RunLifecycleMixin,
        requires_retry_reconciliation,
    )

    background = load_source("task_background")
    repo = repositories[0]()
    previous = repo.save(AgentRun(user_id="synthetic", message="read-only test", status="failed"))
    started = []

    class Runner(RunLifecycleMixin, background.BackgroundTaskExecutionMixin):
        def start_run(self, **kwargs):
            started.append(kwargs)
            return repo.save(
                AgentRun(user_id=kwargs["user_id"], message=kwargs["message"], status="queued")
            )

    runner = Runner()
    runner._repo = repo
    assert requires_retry_reconciliation(previous) is False
    retried = runner.retry_run(previous.run_id, requested_by=previous.user_id)
    assert retried.run_id != previous.run_id
    assert len(started) == 1 and started[0]["auto_execute"] is True
    assert runner._prepare_expired_execution_recovery(retried) is True


def test_transactional_resume_cannot_enqueue_interrupted_unknown_run(repositories, tmp_path):
    from app.application.agent_orchestrator.approval_grant import ApprovalGrantError
    from app.application.agent_orchestrator.resume_transaction import resume_and_enqueue
    from app.application.agent_orchestrator.task_execution_sql_repository import (
        SQLAlchemyTaskExecutionRepository,
    )
    from app.db.models.agent import AgentTaskExecutionRecord

    engine = create_engine(f"sqlite:///{tmp_path / 'resume-gate.sqlite'}")
    factory = sessionmaker(bind=engine)
    repo = repositories[1](session_factory=factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=factory)
    expected = initial(repo)
    observer(repo)(expected, pending=False, reason="consumer_closed")
    paused = repo.get(expected.run_id)
    paused.status = "paused"
    repo.save(paused)
    try:
        with pytest.raises(ApprovalGrantError, match="人工核对"):
            resume_and_enqueue(
                repo,
                queue,
                run_id=expected.run_id,
                principal_id=expected.user_id,
                runtime_context={},
            )
        with factory() as db:
            assert db.query(AgentTaskExecutionRecord).count() == 0
        assert repo.get(expected.run_id).final_output["receipt"] == expected.final_output["receipt"]
    finally:
        engine.dispose()


def test_existing_recovery_evidence_is_retained_and_legacy_marker_is_gated(repositories):
    repo = repositories[0]()
    expected = initial(repo)
    existing = copy.deepcopy(expected)
    existing.metadata["recovery"] = {"independent_audit": "keep", "state": "not-yet-reviewed"}
    existing.metadata["stream_interruption"] = {
        "reason": "consumer_closed",
        "worker_pending": False,
        "business_outcome": "unknown",
        "replay_allowed": False,
    }
    existing.status = "blocked"
    repo.save(existing)
    observer(repo)(expected, pending=False, reason="consumer_closed")
    fresh = repo.get(expected.run_id)
    assert fresh.metadata["non_retryable"] is True
    assert fresh.metadata["recovery"]["state"] == "manual_reconciliation_required"
    assert fresh.metadata["recovery"]["independent_audit"] == "keep"


@pytest.mark.parametrize("storage", ["memory", "sqlite"])
@pytest.mark.parametrize("action", ["cancel", "pause"])
@pytest.mark.parametrize("order", ["observer_first", "control_first", "cas_conflict"])
def test_control_and_observer_both_orders_preserve_gate_and_audit(
    repositories, tmp_path, monkeypatch, storage, action, order
):
    engine = None
    if storage == "sqlite":
        engine = create_engine(f"sqlite:///{tmp_path / 'control-race.sqlite'}")
        repo = repositories[1](session_factory=sessionmaker(bind=engine))
    else:
        repo = repositories[0]()
    expected = initial(repo)
    mark = observer(repo)
    lifecycle = load_source("run_lifecycle")
    starts = []

    class Runner(lifecycle.RunLifecycleMixin):
        def start_run(self, **kwargs):
            starts.append(kwargs)
            pytest.fail("unknown original effect must not dispatch again")

    runner = Runner()
    runner._repo = repo
    injected = []
    original_save = repo.save_control_if_unchanged

    def conflict(run, previous):
        if not injected:
            injected.append(True)
            mark(expected, pending=True, reason="consumer_closed")
            current = repo.get(expected.run_id)
            current.metadata["concurrent_audit"] = "retained"
            current.add_event("audit.saved", "keep")
            repo.save(current)
        return original_save(run, previous)

    if order == "observer_first":
        mark(expected, pending=True, reason="consumer_closed")
    if order == "cas_conflict":
        monkeypatch.setattr(repo, "save_control_if_unchanged", conflict)
    try:
        getattr(runner, action + "_run")(expected.run_id, requested_by=expected.user_id)
        mark(expected, pending=False, reason="consumer_closed")
        current = repo.get(expected.run_id)
        assert current.status == ("cancelled" if action == "cancel" else "paused")
        assert current.metadata["non_retryable"] is True
        assert current.metadata["stream_interruption"]["worker_pending"] is False
        assert current.final_output["receipt"] == expected.final_output["receipt"]
        assert current.final_output["cost_units_total"] == 17
        with pytest.raises(ValueError, match="人工核对"):
            runner.retry_run(expected.run_id)
        if action == "pause":
            with pytest.raises(ValueError, match="人工核对"):
                runner.resume_run(expected.run_id)
        if injected:
            assert current.metadata["concurrent_audit"] == "retained"
            assert any(event.event_type == "audit.saved" for event in current.events)
        assert starts == []
    finally:
        if engine:
            engine.dispose()


def receipt_writer(repo):
    from app.application.agent_orchestrator.trace_payloads import _trace_safe_value

    return extract(
        "app/application/agent_orchestrator/chat_trace.py",
        "record_legacy_stream_tool_receipt",
        {
            "get_agent_run_repository": lambda: repo,
            "_trace_safe_value": _trace_safe_value,
        },
    )


@pytest.mark.parametrize("operation", ["interruption", "receipt", "control"])
def test_persistent_snapshot_contention_is_bounded_without_changing_execution(
    repositories, monkeypatch, operation
):
    from app.application.agent_orchestrator.run_lifecycle import RunLifecycleMixin

    repo = repositories[0]()
    expected = initial(repo)
    before, attempts = expected.to_dict(), []

    def contention(*args):
        attempts.append(1)
        if len(attempts) > 8:
            pytest.fail("snapshot contention must not spin indefinitely")
        return False

    seam = {
        "interruption": "save_stream_interruption_if_unchanged",
        "receipt": "save_stream_tool_audit_if_unchanged",
        "control": "save_control_if_unchanged",
    }[operation]
    monkeypatch.setattr(repo, seam, contention)
    runner = RunLifecycleMixin()
    runner._repo = repo
    with pytest.raises(RuntimeError, match="changed repeatedly"):
        if operation == "interruption":
            observer(repo)(expected, pending=True, reason="synthetic")
        elif operation == "receipt":
            receipt_writer(repo)(expected, sequence=1, record={"output": "synthetic"})
        else:
            runner.cancel_run(expected.run_id, requested_by="owner")
    assert len(attempts) == 8
    assert repo.get(expected.run_id).to_dict() == before
    if operation == "control":
        assert repo.latest_task_control(expected.run_id).status == "requested"








@pytest.fixture(params=["memory", "sqlite"])
def independent_run_stores(request, tmp_path):
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository

    engines = []
    if request.param == "sqlite":
        url = f"sqlite:///{tmp_path / 'independent-evidence.sqlite'}"
        engines = [create_engine(url) for _ in range(2)]
        stores = [
            SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=e)) for e in engines
        ]
    else:
        stores = [InMemoryAgentRunRepository()]
        stores.append(stores[0])
    try:
        yield stores
    finally:
        for engine in engines:
            engine.dispose()


@pytest.mark.parametrize("action", ["cancel", "pause"])
def test_control_blocks_immediate_replay_before_observer_can_persist(
    independent_run_stores, monkeypatch, action
):
    from app.application.agent_orchestrator import chat_trace
    from app.application.agent_orchestrator.run_lifecycle import RunLifecycleMixin
    from app.application.agent_orchestrator.run_models import AgentRun

    repo, reader = independent_run_stores
    monkeypatch.setattr(chat_trace, "get_agent_run_repository", lambda: repo)
    original = repo.save(
        AgentRun(
            user_id="owner",
            message="write still running",
            status="running",
            metadata={"channel": "compat_chat_stream"},
        )
    )
    lifetime = life.StreamLifetime()
    entered, release = threading.Event(), threading.Event()

    def delayed_observer(**state):
        entered.set()
        assert release.wait(2)
        chat_trace.mark_chat_stream_interrupted(original, **state)

    lifetime.observe(delayed_observer)
    lifetime.worker_started()
    lifetime.cancel()
    assert entered.wait(1)
    runner = RunLifecycleMixin()
    runner._repo = repo
    try:
        getattr(runner, action + "_run")(original.run_id)
        persisted = reader.get(original.run_id)
        assert persisted.status == ("cancelled" if action == "cancel" else "paused")
        assert persisted.metadata["non_retryable"] is True
        assert persisted.metadata["recovery"]["state"] == "manual_reconciliation_required"
        with pytest.raises(ValueError, match="人工核对"):
            runner.retry_run(original.run_id)
        if action == "pause":
            with pytest.raises(ValueError, match="人工核对"):
                runner.resume_run(original.run_id)
        assert len(reader.list_recent()) == 1
    finally:
        release.set()
        lifetime.worker_finished()


def test_worker_control_and_finalization_cannot_erase_independent_evidence(
    independent_run_stores, monkeypatch
):
    from app.application.agent_orchestrator import chat_trace
    from app.application.agent_orchestrator.run_lifecycle import RunLifecycleMixin
    from app.application.agent_orchestrator.run_models import AgentStep, ToolCall

    repo, writer = independent_run_stores
    monkeypatch.setattr(chat_trace, "get_agent_run_repository", lambda: writer)
    step = AgentStep("write", "business_db", "write", status="running", attempt_count=1)
    call = ToolCall(step.step_id, step.node_id, step.tool_id, step.action, status="running")
    original = repo.save(
        AgentRun(
            user_id="owner", message="write", status="running", steps=[step], tool_calls=[call]
        )
    )
    stale = repo.get(original.run_id)
    returned = writer.get(original.run_id)
    receipt = {"success": True, "receipt": {"id": "committed-once"}}
    returned.steps[0].status = returned.tool_calls[0].status = "completed"
    returned.steps[0].output = returned.tool_calls[0].output = receipt
    writer.save(returned)
    chat_trace.mark_chat_stream_interrupted(original, pending=True, reason="consumer_closed")
    chat_trace.record_legacy_stream_tool_receipt(original, sequence=1, record={"output": receipt})
    repo.request_task_control(original.run_id, "cancel")
    runner = RunLifecycleMixin()
    runner._repo = repo
    assert runner._apply_requested_control(stale)
    current = writer.get(original.run_id)
    assert current.metadata["non_retryable"] is True
    assert current.steps[0].status == current.tool_calls[0].status == "completed"
    assert current.steps[0].output == current.tool_calls[0].output == receipt
    assert current.metadata["stream_tool_audit"][0]["record"]["output"] == receipt
    # A stale whole-run save must retain the receipt and control metadata too.
    repo.save(original)
    final = writer.get(original.run_id)
    assert final.metadata["non_retryable"] is True
    assert final.metadata["recovery"]["state"] == "manual_reconciliation_required"
    assert final.metadata["stream_tool_audit"] == current.metadata["stream_tool_audit"]
    assert final.steps[0].status == final.tool_calls[0].status == "completed"
    assert final.steps[0].output == final.tool_calls[0].output == receipt
    assert {e.event_type for e in final.events} >= {
        "run.observation_interrupted",
        "tool.receipt_observed",
        "run.cancelled",
    }


@pytest.mark.parametrize("identity", ["owner", "created_at", "tenant_id", "turn_id", "mod"])
def test_plain_save_does_not_copy_receipts_between_generations(
    independent_run_stores, monkeypatch, identity
):
    from app.application.agent_orchestrator import chat_trace

    repo, reader = independent_run_stores
    monkeypatch.setattr(chat_trace, "get_agent_run_repository", lambda: repo)
    expected = initial(repo)
    chat_trace.mark_chat_stream_interrupted(
        expected, pending=False, reason="consumer_closed"
    )
    chat_trace.record_legacy_stream_tool_receipt(
        expected, sequence=1, record={"receipt": "old-scope"}
    )
    replacement = copy.deepcopy(expected)
    if identity == "owner":
        replacement.user_id = "another-owner"
    elif identity == "created_at":
        replacement.created_at = "replacement-generation"
    elif identity == "mod":
        replacement.metadata["runtime_context"]["_mod_authorization"] = {"mod_id": "replacement"}
    else:
        replacement.metadata["runtime_context"][identity] = "replacement"
    repo.save(replacement)
    final = reader.get(expected.run_id)
    assert "stream_tool_audit" not in final.metadata
    assert "stream_interruption" not in final.metadata
    assert "non_retryable" not in final.metadata


@pytest.mark.parametrize("unknown", [False, True])
def test_known_idempotent_repair_keeps_references_but_unknown_result_never_replays(
    independent_run_stores, monkeypatch, tmp_path, unknown
):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    repo, reader = independent_run_stores
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    calls = []

    def execute(step, *, runtime_context):
        calls.append(runtime_context["idempotency_key"])
        if len(calls) == 1:
            return {
                "success": False,
                "message": "read failed",
                **(
                    {
                        "outcome": "unknown",
                        "retryable": False,
                        "reconciliation_required": True,
                        "io_reconciliation": [{"method": "GET", "kind": "response_unknown"}],
                    }
                    if unknown
                    else {}
                ),
            }
        return {"success": True, "data": []}

    plan = PlanGraph(
        plan_id="repair-boundary",
        intent="business_db_read",
        metadata={"repair_overrides": {"read": {"retry": True, "max_attempts": 1}}},
        nodes=[
            WorkflowNode(
                node_id="read",
                tool_id="business_db",
                action="read",
                params={"entity": "products"},
                risk="low",
                idempotent=True,
            )
        ],
    )
    runner = AgentOrchestrator(repository=repo, tool_executor=NS(execute=execute))
    run = runner.start_run_from_plan(user_id="owner", message="read", plan=plan)
    stored = reader.get(run.run_id)
    assert run.status == stored.status == ("blocked" if unknown else "completed")
    assert len(calls) == stored.steps[0].attempt_count == (1 if unknown else 2)
    assert [call.status for call in stored.tool_calls] == (
        ["failed"] if unknown else ["failed", "completed"]
    )
    if unknown:
        stale = repo.get(run.run_id)
        stale.steps[0].output = {}
        stale.status = "running"
        repo.save(stale)
        final = reader.get(run.run_id)
        assert final.status == "blocked"
        assert final.steps[0].output == stored.steps[0].output
        assert final.steps[0].output["outcome"] == "unknown"
        assert final.steps[0].output["reconciliation_evidence"]["io_reconciliation"] == [
            {"method": "GET", "kind": "response_unknown"}
        ]
        with pytest.raises(ValueError, match="人工核对"):
            runner.retry_run(run.run_id)
        assert len(calls) == 1
    else:
        assert run.steps[0].status == "completed"
        assert run.steps[0].output == stored.steps[0].output == {"success": True, "data": []}
        assert len(run.steps[0].repair_history) == 1
