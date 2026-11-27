"""Observe real SQL snapshots without becoming another execution authority."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.run_diagnostics import diagnose_run, scan_agent_diagnostics
from app.application.agent_orchestrator.run_models import AgentRun, ToolCall
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_execution_models import AgentTaskExecution
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)


def _at(seconds):
    return datetime.fromtimestamp(seconds, UTC).isoformat()


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    from app.domain.shared_services import ssot
    from app.infrastructure.observability import metrics

    engine = create_engine(
        f"sqlite:///{tmp_path / 'agent.db'}", connect_args={"check_same_thread": False}
    )
    factory = sessionmaker(bind=engine)
    repository = SQLAlchemyAgentRunRepository(session_factory=factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=factory)
    repository._ensure_schema()
    queue._ensure_schema()
    order_dir = tmp_path / "orders"
    monkeypatch.setattr(ssot, "_STORE_DIR", order_dir)
    monkeypatch.setattr(ssot, "_EVENTS_FILE", order_dir / "work_orders.jsonl")
    monkeypatch.setattr(ssot, "_remote_enabled", lambda: False)
    monkeypatch.setattr(ssot, "_publish_bus_event", lambda *args: None)
    monkeypatch.setattr("app.build_identity.verified_source_sha", lambda: "a" * 40)
    observations = {"completed": [], "scans": [], "faults": []}
    monkeypatch.setattr(
        metrics,
        "set_diagnostic_findings",
        lambda counts, **kw: observations["completed"].append((dict(counts), kw)),
    )
    monkeypatch.setattr(
        metrics, "observe_diagnostic_scan", lambda **kw: observations["scans"].append(kw)
    )
    monkeypatch.setattr(
        metrics, "observe_diagnostic_fault", lambda **kw: observations["faults"].append(kw)
    )
    yield repository, queue, factory, observations, ssot
    engine.dispose()


def _persist(
    repository,
    factory,
    *,
    status="running",
    age=1000,
    run_id=None,
    execution_sha="b" * 40,
    **metadata,
):
    from app.db.models.agent import AgentRunRecord

    now = time.time()
    run = AgentRun("account-private", "private business prompt", status=status, metadata=metadata)
    if run_id is not None:
        run.run_id = run_id
    run.metadata.setdefault("runtime_context", {"tenant_id": "private-tenant"})
    if execution_sha is not None:
        run.add_event("run.started", "secret diagnostic message", {"source_sha": execution_sha})
    repository.save(run)
    with factory.begin() as db:
        record = db.get(AgentRunRecord, run.run_id)
        payload = json.loads(record.payload_json)
        payload["updated_at"] = payload["created_at"] = _at(now - age)
        record.created_at = record.updated_at = _at(now - age)
        record.payload_json = json.dumps(payload)
    return repository.get(run.run_id)


@pytest.mark.parametrize(
    "state",
    [
        "waiting_user",
        "waiting_input",
        "waiting_approval",
        "waiting_auth",
        "paused",
        "cancelled",
        "rejected",
        "completed",
    ],
)
def test_legitimate_waits_and_terminal_states_are_not_stalled(state):
    now = time.time()
    run = AgentRun("u", "wait", status=state, updated_at=_at(now - 100000))
    before = run.to_dict()
    assert diagnose_run(run, now=now) is None
    assert run.to_dict() == before


def test_child_and_quality_control_waits_are_not_dead_workers():
    now = time.time()
    run = AgentRun(
        "u", "waiting for original child", status="running", updated_at=_at(now - 100000)
    )
    run.metadata["xiaox_runtime"] = {
        "coordinator_active": "false",
        "calls": {"c": {"state": "running", "child_run_id": "child"}},
    }
    assert diagnose_run(run, now=now) is None
    run.metadata.clear()
    run.tool_calls.append(
        ToolCall(
            step_id="s",
            node_id="n",
            tool_id="excel",
            action="write",
            status="completed",
            metadata={"verification": {"status": "pending"}},
        )
    )
    assert diagnose_run(run, now=now) is None
    run.metadata["verification_recovery"] = {"lease_until": now - 6}
    assert diagnose_run(run, now=now)["layer"] == "verification"
    assert run.status == "running" and run.tool_calls[0].status == "completed"


def test_stall_observation_respects_deadlines_and_future_queue_availability():
    now = time.time()
    run = AgentRun("u", "active", status="running", updated_at=_at(now - 1000))
    execution = AgentTaskExecution(
        run.run_id,
        run.run_id,
        "u",
        state="running",
        heartbeat_at=_at(now),
        lease_expires_at=_at(now + 15),
    )
    assert diagnose_run(run, execution, now=now)["kind"] == "progress_stalled"
    run.metadata["xiaox_runtime"] = {"coordinator_active": True, "deadline_at": now + 600}
    assert diagnose_run(run, execution, now=now) is None
    run.metadata["xiaox_runtime"]["deadline_at"] = now - 10
    assert diagnose_run(run, execution, now=now)["kind"] == "deadline_exceeded"
    run.metadata["xiaox_runtime"]["deadline_at"] = True
    assert diagnose_run(run, execution, now=now)["kind"] == "progress_stalled"
    execution.lease_expires_at = _at(now - 10)
    assert diagnose_run(run, execution, now=now)["kind"] == "lease_expired"
    run.status = "queued"
    execution.state, execution.available_at = "queued", _at(now + 3600)
    assert diagnose_run(run, execution, now=now) is None
    execution.available_at = _at(now - 1000)
    assert diagnose_run(run, execution, now=now)["kind"] == "queue_overdue"


@pytest.mark.parametrize(
    "stage,layer",
    [
        ("model", "model"),
        ("planning", "planning"),
        ("business", "tool"),
        ("database", "persistence"),
        ("goal_verification", "verification"),
        ("handoff", "collaboration"),
        ("delivery", "delivery"),
        ("runtime", "runtime"),
        ("new-unclassified-stage", "unknown"),
    ],
)
def test_architecture_classification_uses_structured_stage_not_error_prose(stage, layer):
    run = AgentRun(
        "u",
        "business",
        status="failed",
        metadata={"runtime_failure_stage": stage, "runtime_failure_kind": "known_failure"},
    )
    run.final_output = {
        "xiaox_result": {
            "ok": False,
            "execution_state": "failed",
            "error": "database timeout network tool model sensitive prose",
        }
    }
    assert diagnose_run(run, now=time.time())["layer"] == layer


@pytest.mark.parametrize(
    "model_unknown,layer,kind",
    [(False, "tool", "business_outcome_unknown"), (True, "model", "model_usage_unknown")],
)
def test_unknown_effect_is_diagnosed_without_replaying(model_unknown, layer, kind):
    run = AgentRun("u", "business", status="blocked")
    run.metadata["xiaox_runtime"] = {"model_reconciliation_required": model_unknown}
    run.final_output = {"xiaox_result": {"ok": False, "execution_state": "unknown"}}
    before = run.to_dict()
    assert diagnose_run(run, now=time.time()) == {"layer": layer, "kind": kind, "code": kind}
    assert run.to_dict() == before


def test_sql_scan_keeps_snapshots_and_receipts_and_persists_redacted_evidence(ledger):
    repository, queue, factory, observed, ssot = ledger
    run = _persist(repository, factory)
    waiting = _persist(repository, factory, status="waiting_user")
    original = {item.run_id: item.to_dict() for item in (run, waiting)}
    cursor = {}
    assert scan_agent_diagnostics(repository=repository, cursor=cursor) == 1
    assert cursor == {}
    assert len(observed["completed"]) == 1
    order = ssot.list_work_orders()[0]
    assert order["status"] == "candidate"
    context = order["history"][0]["context"]
    evidence, reference = context["diagnostic"], context["evidence_ref"]
    assert evidence["observer_source_sha"] == "a" * 40
    assert evidence["execution_source_sha"] == "b" * 40
    assert evidence["business_replay_allowed"] is False
    assert evidence["diagnosis"] == "suspected"
    assert evidence["source_event_ids"]
    assert (
        hashlib.sha256(
            json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str).encode()
        ).hexdigest()
        == reference["sha256"]
    )
    encoded = json.dumps(order)
    for private in (
        "account-private",
        "private-tenant",
        "private business prompt",
        "secret diagnostic message",
    ):
        assert private not in encoded
    for identity, payload in original.items():
        assert repository.get(identity).to_dict() == payload
        assert queue.get(identity) is None
    # Fresh repository/cursor simulates observer restart; SSOT retains one order.
    restored = SQLAlchemyAgentRunRepository(session_factory=factory, auto_create=False)
    scan_agent_diagnostics(repository=restored, cursor={})
    assert len(ssot.list_work_orders()) == len(observed["faults"]) == 1


@pytest.mark.parametrize("execution_sha", ["b" * 40, None])
def test_imported_running_task_never_inherits_persistence_host_as_execution_source(
    ledger, monkeypatch, execution_sha
):
    repository, _, factory, _, ssot = ledger
    monkeypatch.setattr(
        "app.application.agent_orchestrator.run_terminal_metrics.observed_source_sha",
        lambda: "a" * 40,
    )
    run = _persist(repository, factory, execution_sha=execution_sha)
    state_event = [event for event in run.events if event.event_type == "run.state_changed"][-1]
    assert state_event.data["source_sha"] == "a" * 40
    scan_agent_diagnostics(repository=repository, cursor={})
    evidence = ssot.list_work_orders()[0]["history"][0]["context"]["diagnostic"]
    assert evidence["persistence_source_sha"] == evidence["observer_source_sha"] == "a" * 40
    assert evidence["execution_source_sha"] == execution_sha
    assert evidence["execution_source_status"] == ("recorded" if execution_sha else "unavailable")


@pytest.mark.parametrize(
    "child_case",
    [
        "missing",
        "foreign_user",
        "foreign_tenant",
        "foreign_mod",
        "wrong_parent",
        "wrong_task",
        "valid",
        "recent_missing",
    ],
)
def test_sql_wait_protection_requires_original_child_binding_after_grace(ledger, child_case):
    repository, _, factory, _, ssot = ledger
    parent_id, child_id = "run_" + "d" * 32, "run_" + "c" * 32
    task_id = "task_" + "e" * 32
    if child_case not in {"missing", "recent_missing"}:
        child = AgentRun(
            "account-private", "private unrelated child", run_id=child_id, status="waiting_user"
        )
        child.metadata = {
            "runtime_context": {"tenant_id": "private-tenant", "parent_run_id": parent_id},
            "task_context": {"task_id": task_id},
        }
        if child_case == "foreign_user":
            child.user_id = "foreign-private-user"
        elif child_case == "foreign_tenant":
            child.metadata["runtime_context"]["tenant_id"] = "foreign-private-tenant"
        elif child_case == "foreign_mod":
            child.metadata["runtime_context"]["_mod_authorization"] = {
                "mod_id": "foreign-private-mod"
            }
        elif child_case == "wrong_parent":
            child.metadata["runtime_context"]["parent_run_id"] = "another-parent"
        elif child_case == "wrong_task":
            child.metadata["task_context"]["task_id"] = "another-task"
        repository.save(child)
    parent = _persist(
        repository,
        factory,
        run_id=parent_id,
        age=10 if child_case == "recent_missing" else 10000,
        xiaox_runtime={
            "coordinator_active": False,
            "calls": {
                "call": {"state": "submitted", "child_run_id": child_id, "child_task_id": task_id}
            },
        },
    )
    before = parent.to_dict()
    count = scan_agent_diagnostics(repository=repository, cursor={})
    assert repository.get(parent_id).to_dict() == before
    if child_case in {"valid", "recent_missing"}:
        assert count == 0 and not ssot.list_work_orders()
    else:
        assert count == 1
        evidence = ssot.list_work_orders()[0]["history"][0]["context"]["diagnostic"]
        assert evidence["layer"] == "collaboration"
        assert evidence["kind"] == "child_receipt_missing"
        assert evidence["diagnosis"] == "suspected" and evidence["business_replay_allowed"] is False
        assert evidence["missing_child_refs"] == [child_id]
        assert "foreign-private" not in json.dumps(evidence)


def test_bounded_scan_does_not_starve_old_runs_or_publish_partial_gauges(ledger):
    repository, _, factory, observed, ssot = ledger
    for index in range(5):
        _persist(repository, factory, age=0, run_id=f"run_{index:032x}")
    last = _persist(repository, factory, run_id=f"run_{9:032x}")
    cursor = {}
    for _ in range(2):
        assert scan_agent_diagnostics(repository=repository, cursor=cursor, limit=2) == 0
        assert not observed["completed"]
    assert scan_agent_diagnostics(repository=repository, cursor=cursor, limit=2) == 1
    assert not cursor
    assert observed["completed"][0][0] == {("runtime", "progress_stalled"): 1}
    assert (
        ssot.list_work_orders()[0]["history"][0]["context"]["diagnostic"]["run_id"] == last.run_id
    )


def test_sql_scan_skips_large_explicit_wait_population_before_limit(ledger, monkeypatch):
    repository, _, factory, observed, _ = ledger
    with repository.transaction() as db:
        for index in range(1000):
            repository.save_in_session(
                db,
                AgentRun(
                    "waiting-owner", "human wait", run_id=f"run_{index:032x}", status="waiting_user"
                ),
            )
    stalled = _persist(repository, factory, run_id="run_" + "f" * 32)
    mapper, loaded = repository._record_to_run, []

    def read(row):
        loaded.append(row.run_id)
        return mapper(row)

    monkeypatch.setattr(repository, "_record_to_run", read)
    assert scan_agent_diagnostics(repository=repository, cursor={}, limit=1) == 1
    assert loaded == [stalled.run_id]
    assert observed["completed"][-1][0] == {("runtime", "progress_stalled"): 1}


def test_candidate_failure_retries_next_sweep_without_false_repair_or_starvation(
    ledger, monkeypatch
):
    repository, _, factory, observed, ssot = ledger
    for index in range(3):
        _persist(repository, factory, run_id=f"run_{index:032x}")
    real = ssot.upsert_candidate
    monkeypatch.setattr(
        ssot, "upsert_candidate", lambda **kw: {"wo_id": "wrong-order", "status": "candidate"}
    )
    assert scan_agent_diagnostics(repository=repository, cursor={}) == 3
    assert observed["scans"][-1] == {"outcome": "error"}
    assert observed["completed"][-1][0] == {("runtime", "progress_stalled"): 3}
    assert not observed["faults"] and not ssot.list_work_orders()
    monkeypatch.setattr(ssot, "upsert_candidate", real)
    assert scan_agent_diagnostics(repository=repository, cursor={}) == 3
    assert len(ssot.list_work_orders()) == 3
    assert all(order["status"] == "candidate" for order in ssot.list_work_orders())


@pytest.mark.parametrize("raises", [False, True])
def test_unreadable_row_does_not_certify_partial_sweep_as_fresh(ledger, monkeypatch, raises):
    repository, _, factory, observed, _ = ledger
    for index in range(3):
        _persist(repository, factory, run_id=f"run_{index:032x}")
    mapper = repository._record_to_run

    def read(row):
        if row.run_id.endswith("0"):
            if raises:
                raise TypeError("malformed historical payload contains private data")
            return None
        return mapper(row)

    monkeypatch.setattr(repository, "_record_to_run", read)
    cursor = {}
    scan_agent_diagnostics(repository=repository, cursor=cursor, limit=1)
    assert cursor.get("unreadable") is True
    scan_agent_diagnostics(repository=repository, cursor=cursor, limit=1)
    scan_agent_diagnostics(repository=repository, cursor=cursor, limit=1)
    assert not cursor and not observed["completed"]
    assert {"outcome": "error"} in observed["scans"]


def test_shared_work_order_dedup_survives_concurrent_processes(ledger, tmp_path):
    repository, _, factory, _, ssot = ledger
    _persist(repository, factory)
    code = """
import sys
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.run_diagnostics import scan_agent_diagnostics
from app.domain.shared_services import ssot
ssot._STORE_DIR = Path(sys.argv[2])
ssot._EVENTS_FILE = ssot._STORE_DIR / 'work_orders.jsonl'
ssot._remote_enabled = lambda: False
ssot._publish_bus_event = lambda *args: None
engine = create_engine('sqlite:///' + sys.argv[1])
repo = SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=engine), auto_create=False)
assert scan_agent_diagnostics(repository=repo, cursor={}) == 1
engine.dispose()
"""
    children = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(tmp_path / "agent.db"), str(tmp_path / "orders")],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    try:
        for child in children:
            stdout, stderr = child.communicate(timeout=30)
            assert child.returncode == 0, stdout + stderr
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
    assert len(ssot.list_work_orders()) == 1
    assert len(ssot._load_events()) == 1


def test_slow_candidate_does_not_block_worker_heartbeat_or_original_recovery(ledger, monkeypatch):
    from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher

    repository, queue, factory, _, ssot = ledger
    _persist(repository, factory, status="failed")
    run = repository.save(AgentRun("u", "ordinary queued work"))
    queue.enqueue(run)
    entered, publish_release, worker_release = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    real = ssot.upsert_candidate

    def slow(**kwargs):
        entered.set()
        assert publish_release.wait(5)
        return real(**kwargs)

    monkeypatch.setattr(ssot, "upsert_candidate", slow)
    dispatcher = AgentTaskDispatcher(
        execution_repository=queue,
        run_repository=repository,
        max_workers=1,
        heartbeat_seconds=0.5,
        lease_seconds=3,
    )
    recoveries = []
    monkeypatch.setattr(dispatcher, "_recover_outcomes", lambda: recoveries.append(True))
    monkeypatch.setattr(dispatcher, "_execute_claim", lambda *args: worker_release.wait(5))
    try:
        dispatcher._dispatch_available()
        assert entered.wait(2)
        before = queue.get(run.run_id).heartbeat_at
        dispatcher._active[run.run_id].last_heartbeat -= 1
        started = time.monotonic()
        dispatcher._dispatch_available()
        assert time.monotonic() - started < 0.5
        assert len(recoveries) == 2
        assert queue.get(run.run_id).heartbeat_at != before
        assert dispatcher._diagnostic_worker.is_alive()
        # Shutdown is bounded even with an already pending support request.
        started = time.monotonic()
        dispatcher.stop(timeout=0.01)
        assert time.monotonic() - started < 0.5
    finally:
        worker_release.set()
        publish_release.set()
        dispatcher.stop(timeout=2)


@pytest.mark.parametrize("failure", ["thread", "import", "thread_and_metric"])
def test_observer_start_failure_cannot_stop_business_claims_and_heartbeats(
    ledger, monkeypatch, failure
):
    import builtins

    from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher
    from app.infrastructure.observability import metrics

    repository, queue, _, observed, _ = ledger
    run = repository.save(AgentRun("u", "ordinary work"))
    queue.enqueue(run)
    release = threading.Event()
    dispatcher = AgentTaskDispatcher(
        execution_repository=queue, run_repository=repository, max_workers=1
    )
    recoveries = []
    monkeypatch.setattr(dispatcher, "_recover_outcomes", lambda: recoveries.append(True))
    monkeypatch.setattr(dispatcher, "_execute_claim", lambda *args: release.wait(5))
    start, import_module = threading.Thread.start, builtins.__import__

    def failing_start(thread):
        if thread.name.endswith("-diagnostics"):
            raise RuntimeError("can't start new thread")
        return start(thread)

    def failing_import(name, *args, **kwargs):
        if name == "app.application.agent_orchestrator.run_diagnostics":
            raise ImportError("optional observer unavailable")
        return import_module(name, *args, **kwargs)

    if failure == "import":
        monkeypatch.setattr(builtins, "__import__", failing_import)
    else:
        monkeypatch.setattr(threading.Thread, "start", failing_start)
    if failure == "thread_and_metric":

        def broken_metric(**kwargs):
            raise RuntimeError("metrics unavailable")

        monkeypatch.setattr(metrics, "observe_diagnostic_scan", broken_metric)
    try:
        dispatcher._dispatch_available()
        execution = queue.get(run.run_id)
        assert execution.state in {"claimed", "running"}
        assert dispatcher._diagnostic_worker is None
        assert dispatcher._diagnostic_continue is False
        dispatcher._active[run.run_id].last_heartbeat -= 10
        dispatcher._dispatch_available()
        assert queue.get(run.run_id).heartbeat_at != execution.heartbeat_at
        assert len(recoveries) == 2
        if failure != "thread_and_metric":
            assert observed["scans"] == [{"outcome": "error"}]
    finally:
        release.set()
        dispatcher.stop(timeout=2)


def test_observer_continues_partial_sweep_and_waits_from_full_completion(ledger, monkeypatch):
    from types import SimpleNamespace

    from app.application.agent_orchestrator import task_dispatcher

    repository, queue, *_ = ledger
    clock, invocations = [100.0], []
    monkeypatch.setattr(task_dispatcher, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def scan(*, cursor, **kwargs):
        invocations.append(clock[0])
        if len(invocations) == 1:
            cursor.update(upper="z", after="a", counts={})
            clock[0] = 110.0
        else:
            cursor.clear()
            clock[0] += 9.0

    monkeypatch.setattr(
        "app.application.agent_orchestrator.run_diagnostics.scan_agent_diagnostics", scan
    )
    dispatcher = task_dispatcher.AgentTaskDispatcher(
        execution_repository=queue, run_repository=repository
    )

    def tick(at):
        clock[0] = at
        dispatcher._diagnose_runs()
        if dispatcher._diagnostic_worker is not None:
            dispatcher._diagnostic_worker.join(timeout=2)
            assert not dispatcher._diagnostic_worker.is_alive()

    tick(100.0)
    assert dispatcher._last_diagnostic_scan == 110.0
    tick(110.9)
    assert invocations == [100.0]
    tick(111.0)
    assert dispatcher._last_diagnostic_scan == 120.0
    tick(149.9)
    assert invocations == [100.0, 111.0]
    tick(150.0)
    assert invocations == [100.0, 111.0, 150.0]
    dispatcher.stop(timeout=0)


def test_observer_no_progress_falls_back_to_idle_interval(ledger, monkeypatch):
    from types import SimpleNamespace

    from app.application.agent_orchestrator import task_dispatcher

    repository, queue, *_ = ledger
    clock, invocations = [101.0], []
    monkeypatch.setattr(task_dispatcher, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def no_progress(**kwargs):
        invocations.append(clock[0])
        clock[0] += 1.0

    monkeypatch.setattr(
        "app.application.agent_orchestrator.run_diagnostics.scan_agent_diagnostics", no_progress
    )
    dispatcher = task_dispatcher.AgentTaskDispatcher(
        execution_repository=queue, run_repository=repository
    )
    dispatcher._diagnostic_cursor.update(upper="z", after="a", counts={})
    dispatcher._diagnostic_continue, dispatcher._last_diagnostic_scan = True, 100.0
    dispatcher._diagnose_runs()
    dispatcher._diagnostic_worker.join(timeout=2)
    assert dispatcher._diagnostic_continue is False
    clock[0] = 103.0
    dispatcher._diagnose_runs()
    assert invocations == [101.0]
    clock[0] = 132.0
    dispatcher._diagnose_runs()
    dispatcher._diagnostic_worker.join(timeout=2)
    assert invocations == [101.0, 132.0]
    dispatcher.stop(timeout=0)
