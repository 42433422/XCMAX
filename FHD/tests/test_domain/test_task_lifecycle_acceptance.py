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
    assert again.state == "completed"
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
    assert reopened.state == "completed"
    assert repo.claim("other", lease_seconds=30) is None
    engine.dispose()


def test_employee_success_and_unknown_are_not_rewritten(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    EmployeeRunLog.__table__.create(engine)

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
    engine.dispose()
