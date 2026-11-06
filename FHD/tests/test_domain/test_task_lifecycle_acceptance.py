"""A19–A30 gates on the writers that actually persist task status.

These tests import the production repositories and services. Removing the
state-machine calls from those writers makes the assertions fail.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.task_execution_repository import (
    InMemoryTaskExecutionRepository,
    SQLAlchemyTaskExecutionRepository,
)
from app.application.employee_runtime import run_ledger
from app.application.workflow_definition_app_service import WorkflowDefinitionAppService
from app.db.db_base import Base
from app.db.models.employee_run_log import EmployeeRunLog
from app.db.models.task_lifecycle import TaskLifecycleRecord
from app.db.models.workflow import WorkflowRun, WorkflowRunStatus
from app.errors import WorkflowError


def _run(name: str) -> AgentRun:
    run = AgentRun(user_id="owner", message=name, status="queued")
    run.metadata["runtime_context"] = {"tenant_id": "tenant-a"}
    run.metadata["task_context"] = {"task_id": name}
    return run


def test_completed_execution_cannot_be_reopened_or_rewritten() -> None:
    repo = InMemoryTaskExecutionRepository()
    run = _run("terminal")
    repo.enqueue(run)
    claimed = repo.claim("worker", lease_seconds=30)
    assert claimed is not None
    assert repo.finish(run.run_id, "worker", "completed") is not None
    assert repo.transition(run.run_id, "queued") is None
    assert repo.transition(run.run_id, "failed") is None
    assert repo.finish(run.run_id, "worker", "failed") is None
    again = repo.enqueue(run, requested_by="late")
    assert again.state == "succeeded"
    assert again.last_error_code == ""
    assert repo.claim("other", lease_seconds=30) is None


def test_queued_execution_cannot_skip_to_success() -> None:
    repo = InMemoryTaskExecutionRepository()
    run = _run("skip")
    repo.enqueue(run)
    assert repo.transition(run.run_id, "completed") is None
    assert repo.get(run.run_id).state == "queued"


def test_recovery_stops_after_three_claims() -> None:
    repo = InMemoryTaskExecutionRepository()
    run = _run("retry-cap")
    queued = repo.enqueue(run)
    start = datetime.fromisoformat(queued.available_at.replace("Z", "+00:00"))
    owners = []
    for index in range(3):
        claimed = repo.claim(
            f"worker-{index}",
            lease_seconds=5,
            now=(start + timedelta(seconds=30 * index)).isoformat(),
        )
        assert claimed is not None
        owners.append(claimed.lease_owner)
    assert owners == ["worker-0", "worker-1", "worker-2"]
    exhausted = repo.claim(
        "worker-3",
        lease_seconds=5,
        now=(start + timedelta(seconds=90)).isoformat(),
    )
    assert exhausted is None
    stored = repo.get(run.run_id)
    assert stored.state == "failed"
    assert stored.last_error_code == "retries_exhausted"
    assert stored.execution_count == 3


def test_sql_queue_keeps_the_same_terminal_guard(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'queue.db'}")
    repo = SQLAlchemyTaskExecutionRepository(session_factory=sessionmaker(bind=engine))
    run = _run("sql-terminal")
    repo.enqueue(run)
    claimed = repo.claim("worker", lease_seconds=30)
    assert claimed is not None
    assert repo.finish(run.run_id, "worker", "completed") is not None
    assert repo.transition(run.run_id, "queued") is None
    reopened = repo.enqueue(run)
    assert reopened.state == "succeeded"
    assert repo.claim("other", lease_seconds=30) is None
    engine.dispose()


def test_employee_success_and_unknown_are_not_rewritten(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(
        engine, tables=[EmployeeRunLog.__table__, TaskLifecycleRecord.__table__]
    )

    from contextlib import contextmanager

    @contextmanager
    def database():
        with Session(engine) as db:
            yield db

    monkeypatch.setattr(run_ledger, "get_db", database)
    success = run_ledger.create_employee_run_log(employee_id="worker", tenant_id=1)
    run_ledger.finish_employee_run_log(success, tenant_id=1, status="success", output={"n": 1})
    with pytest.raises(ValueError):
        run_ledger.finish_employee_run_log(success, tenant_id=1, status="failed", error="late")
    run_ledger.finish_employee_run_log(success, tenant_id=1, status="success", output={"n": 2})
    with Session(engine) as db:
        stored = db.get(EmployeeRunLog, success)
        assert stored.status == "success"
        assert stored.output_json == '{"n": 1}'

    unknown = run_ledger.create_employee_run_log(employee_id="worker", tenant_id=1)
    run_ledger.finish_employee_run_log(unknown, tenant_id=1, status="unknown", error="receipt lost")
    with Session(engine) as db:
        assert db.get(EmployeeRunLog, unknown).status == "unknown"
    with pytest.raises(ValueError):
        run_ledger.finish_employee_run_log(unknown, tenant_id=1, status="success")
    engine.dispose()


def test_workflow_cancel_uses_the_shared_machine() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    service = WorkflowDefinitionAppService(session_factory=factory)
    created = service.create_definition(
        tenant_id=1,
        name="cancel-gate",
        nodes=[
            {
                "node_id": "n1",
                "tool_id": "products",
                "action": "query",
                "params": {},
                "risk": "low",
                "idempotent": True,
                "description": "查询",
                "depends_on": [],
            }
        ],
    )
    run = service.start_run(created["id"])
    with factory() as db:
        row = db.get(WorkflowRun, run["id"])
        row.status = "timed_out"
        db.commit()
    with pytest.raises(WorkflowError) as exc:
        service.cancel_run(run["id"])
    assert exc.value.status_code == 409
    with factory() as db:
        assert db.get(WorkflowRun, run["id"]).status == "timed_out"
    pending = service.start_run(created["id"])
    assert pending["status"] == WorkflowRunStatus.PENDING.value
    assert service.cancel_run(pending["id"])["status"] == WorkflowRunStatus.CANCELLED.value
    assert service.lifecycle(pending["id"])["history"][-1]["to"] == "cancelled"
    engine.dispose()


def test_sql_queue_retries_open_effect_and_idempotency(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'retry.db'}")
    repo = SQLAlchemyTaskExecutionRepository(
        session_factory=sessionmaker(bind=engine), jitter_ratio=0.0
    )
    run = _run("sql-retry")
    stored = repo.enqueue(run, idempotency_key="sql-1", fingerprint="body")
    assert (
        repo.enqueue(_run("copy"), idempotency_key="sql-1", fingerprint="body").run_id
        == stored.run_id
    )
    claimed = repo.claim("worker", lease_seconds=30)
    assert claimed is not None
    retried = repo.finish(run.run_id, "worker", "failed", error_code="timeout")
    assert retried is not None and retried.state == "queued"
    assert repo.claim("worker", lease_seconds=5, now=claimed.updated_at) is None
    again = repo.claim("worker", lease_seconds=5, now=retried.available_at)
    assert again is not None and again.execution_count == 2
    repo.mark_open_effect(run.run_id, "write-order")
    start = datetime.fromisoformat(again.updated_at.replace("Z", "+00:00"))
    assert (
        repo.claim("other", lease_seconds=5, now=(start + timedelta(seconds=30)).isoformat())
        is None
    )
    assert repo.get(run.run_id).last_error_code == "needs_verification"
    assert repo.lifecycle(run.run_id)["history"]
    engine.dispose()


def test_queue_retries_with_backoff_then_stops() -> None:
    repo = InMemoryTaskExecutionRepository(jitter_ratio=0.0, rng=__import__("random").Random(1))
    run = _run("backoff")
    queued = repo.enqueue(run)
    start = datetime.fromisoformat(queued.available_at.replace("Z", "+00:00"))
    claimed = repo.claim("worker", lease_seconds=30, now=start.isoformat())
    assert claimed is not None
    retried = repo.finish(run.run_id, "worker", "failed", error_code="timeout")
    assert retried is not None and retried.state == "queued"
    assert retried.available_at > start.isoformat()
    assert repo.claim("worker", lease_seconds=30, now=start.isoformat()) is None
    again = repo.claim("worker", lease_seconds=30, now=(start + timedelta(seconds=2)).isoformat())
    assert again is not None and again.execution_count == 2
    repo.finish(run.run_id, "worker", "failed", error_code="timeout")
    third = repo.claim("worker", lease_seconds=30, now=(start + timedelta(seconds=10)).isoformat())
    assert third is not None and third.execution_count == 3
    stopped = repo.finish(run.run_id, "worker", "failed", error_code="timeout")
    assert stopped is not None and stopped.state == "timed_out"
    assert [event["to"] for event in repo.lifecycle(run.run_id)["history"]][-1] == "timed_out"


def test_open_effect_is_verified_instead_of_replayed() -> None:
    repo = InMemoryTaskExecutionRepository()
    run = _run("effect")
    queued = repo.enqueue(run)
    start = datetime.fromisoformat(queued.available_at.replace("Z", "+00:00"))
    assert repo.claim("worker", lease_seconds=5, now=start.isoformat()) is not None
    repo.mark_open_effect(run.run_id, "write-order")
    assert (
        repo.claim("other", lease_seconds=5, now=(start + timedelta(seconds=30)).isoformat())
        is None
    )
    stored = repo.get(run.run_id)
    assert stored.state == "failed" and stored.last_error_code == "needs_verification"


def test_approval_resumes_the_same_task_and_timeout_rejects() -> None:
    repo = InMemoryTaskExecutionRepository(approval_timeout_seconds=30)
    run = _run("approval")
    repo.enqueue(run)
    claimed = repo.claim("worker", lease_seconds=30)
    assert claimed is not None
    paused = repo.request_approval(run.run_id, "boss")
    assert paused is not None and paused.state == "waiting_approval" and paused.run_id == run.run_id
    with pytest.raises(Exception):
        repo.resolve_approval(run.run_id, "approve", "stranger")
    resumed = repo.resolve_approval(run.run_id, "approve", "boss")
    assert resumed is not None and resumed.state == "queued" and resumed.run_id == run.run_id
    assert repo.claim("worker", lease_seconds=30) is not None
    paused = repo.request_approval(run.run_id, "boss")
    assert paused is not None
    moment = datetime.fromisoformat(paused.updated_at.replace("Z", "+00:00"))
    assert (
        repo.claim("worker", lease_seconds=5, now=(moment + timedelta(seconds=31)).isoformat())
        is None
    )
    assert repo.get(run.run_id).state == "rejected"
    assert repo.get(run.run_id).last_error_code == "approval_timeout"


def test_idempotent_enqueue_does_not_create_a_second_task() -> None:
    repo = InMemoryTaskExecutionRepository()
    first = _run("same")
    second = _run("same")
    stored = repo.enqueue(first, idempotency_key="order-1", fingerprint="body")
    again = repo.enqueue(second, idempotency_key="order-1", fingerprint="body")
    assert again.run_id == stored.run_id
    with pytest.raises(Exception):
        repo.enqueue(_run("other"), idempotency_key="order-1", fingerprint="other-body")


def test_employee_retry_approval_and_rejection(monkeypatch) -> None:
    from contextlib import contextmanager

    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(
        engine, tables=[EmployeeRunLog.__table__, TaskLifecycleRecord.__table__]
    )

    @contextmanager
    def database():
        with Session(engine) as db:
            yield db

    monkeypatch.setattr(run_ledger, "get_db", database)
    run_id = run_ledger.create_employee_run_log(employee_id="worker", tenant_id=1)
    run_ledger.finish_employee_run_log(
        run_id, tenant_id=1, status="failed", error_code="timeout", attempts=1, jitter_ratio=0
    )
    with Session(engine) as db:
        row = db.get(EmployeeRunLog, run_id)
        assert row.status == "pending" and row.attempts == 2
        row.status = "running"
        db.commit()
    run_ledger.finish_employee_run_log(
        run_id, tenant_id=1, status="failed", error_code="timeout", attempts=3, jitter_ratio=0
    )
    with Session(engine) as db:
        assert db.get(EmployeeRunLog, run_id).status == "timed_out"
    waiting = run_ledger.create_employee_run_log(employee_id="worker", tenant_id=1)
    run_ledger.request_employee_approval(waiting, tenant_id=1, approver="boss")
    with pytest.raises(ValueError):
        run_ledger.decide_employee_run_log(
            waiting, tenant_id=1, decision="approve", actor="stranger"
        )
    run_ledger.decide_employee_run_log(waiting, tenant_id=1, decision="approve", actor="boss")
    with Session(engine) as db:
        assert db.get(EmployeeRunLog, waiting).status == "pending"
        assert db.get(EmployeeRunLog, waiting).id == waiting
    rejected = run_ledger.create_employee_run_log(employee_id="worker", tenant_id=1)
    run_ledger.request_employee_approval(rejected, tenant_id=1, approver="boss")
    assert run_ledger.expire_employee_approvals(tenant_id=1, timeout_seconds=0) == 1
    with Session(engine) as db:
        assert db.get(EmployeeRunLog, rejected).status == "rejected"
    with pytest.raises(ValueError):
        run_ledger.finish_employee_run_log(rejected, tenant_id=1, status="success")
    engine.dispose()


def test_workflow_retry_approval_and_history() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    service = WorkflowDefinitionAppService(session_factory=factory)
    created = service.create_definition(
        tenant_id=1,
        name="lifecycle",
        nodes=[
            {
                "node_id": "n1",
                "tool_id": "products",
                "action": "query",
                "params": {},
                "risk": "low",
                "idempotent": True,
                "description": "查询",
                "depends_on": [],
            }
        ],
    )
    run = service.start_run(created["id"])
    service._move_run(run["id"], "running", code="dispatch")
    scheduled = service.fail_run(run["id"], error_code="timeout", attempts=1)
    assert scheduled["status"] == "pending" and scheduled["id"] == run["id"]
    service._move_run(run["id"], "running", code="dispatch")
    assert service.fail_run(run["id"], error_code="timeout", attempts=3)["status"] == "timed_out"
    waiting = service.start_run(created["id"])
    service._move_run(waiting["id"], "running", code="dispatch")
    assert service.request_approval(waiting["id"], "boss")["status"] == "awaiting_approval"
    with pytest.raises(WorkflowError):
        service.decide_run(waiting["id"], "approve", "stranger")
    assert service.decide_run(waiting["id"], "approve", "boss")["id"] == waiting["id"]
    assert service.decide_run(waiting["id"], "approve", "boss")["status"] == "pending"
    timed = service.start_run(created["id"])
    service._move_run(timed["id"], "running", code="dispatch")
    service.request_approval(timed["id"], "boss")
    assert service.expire_approvals(timeout_seconds=0) >= 1
    assert service.get_run(timed["id"])["status"] == "rejected"
    with pytest.raises(WorkflowError) as exc:
        service.fail_run(timed["id"], error_code="timeout", attempts=1)
    assert exc.value.status_code == 409
    engine.dispose()


def test_workflow_engine_retry_stops_at_three_attempts() -> None:
    from app.application.workflow.engine import WorkflowEngine
    from app.application.workflow.workflow_types import WorkflowNode

    calls = []

    def dispatch(tool_id, action, params):
        calls.append(tool_id)
        return {"success": False, "message": "timeout", "error_code": "timeout"}

    node = WorkflowNode("n1", "products", "query", risk="low", idempotent=True)
    result = WorkflowEngine(dispatch)._run_node(node, {}, max_retries=9)
    assert len(calls) == 3
    assert result.success is False
    assert len(result.attempts) == 3


def test_employee_runner_retries_the_same_run() -> None:
    from app.fastapi_routes.admin_control.employee_run import EmployeeRunner, EmployeeWork

    class Backend:
        def __init__(self) -> None:
            self.calls = 0
            self.finished: dict[str, object] = {}

        def start(self, work: EmployeeWork) -> int:
            return 41

        def execute(self, work: EmployeeWork, run_id: int) -> dict[str, object]:
            self.calls += 1
            if self.calls < 3:
                return {"success": False, "error": "upstream timeout", "error_code": "timeout"}
            return {"success": True, "summary": "done"}

        def verify(self, employee_id: str, result: dict[str, object]) -> tuple[bool, str]:
            return True, ""

        def requires_reconciliation(self, result: dict[str, object]) -> bool:
            return False

        def awaits_approval(self, result: dict[str, object]) -> bool:
            return False

        def finish(self, run_id: int, **kwargs: object) -> None:
            self.finished = {"run_id": run_id, **kwargs}

    backend = Backend()
    response = EmployeeRunner(backend).run(
        EmployeeWork("worker", "write", {}, 7, 1, "session", None)
    )
    assert backend.calls == 3
    assert response["run_id"] == 41 and response["attempts"] == 3
    assert backend.finished["run_id"] == 41
    assert backend.finished["status"] == "success"


def test_dispatcher_timeout_requeues_the_same_execution() -> None:
    from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher

    repo = InMemoryTaskExecutionRepository(jitter_ratio=0.0)
    run = _run("dispatcher-timeout")
    repo.enqueue(run)
    claimed = repo.claim("worker", lease_seconds=30)
    assert claimed is not None

    class TimeoutOrchestrator:
        def execute_dispatched_run(self, run_id: str, *, recovered: bool = False) -> None:
            raise TimeoutError("upstream timeout")

        def fail_dispatched_run(self, run_id: str) -> None:
            raise AssertionError("timeout must stay on the same queued task")

    dispatcher = AgentTaskDispatcher(
        execution_repository=repo,
        orchestrator_factory=lambda repository: TimeoutOrchestrator(),
    )
    dispatcher._execute_claim(claimed, claimed.lease_owner)
    stored = repo.get(run.run_id)
    assert stored is not None
    assert stored.state == "queued" and stored.run_id == run.run_id
    assert stored.last_error_code == "timeout"
