"""Approval must be enforced inside the executor, and the caller must read the row back."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.agent_orchestrator.orchestrator import AgentOrchestrator, _runtime_dependencies
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.agent_orchestrator.task_execution_repository import (
    InMemoryTaskExecutionRepository,
)
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.db.models.customer import Customer
from app.db.models.purchase_unit import PurchaseUnit
from app.db.models.sales import SalesOrder, SalesOrderItem
from app.db.models.task_lifecycle import TaskLifecycleRecord

NAME = "闭环待审批客户丁"
REJECTED_NAME = "闭环驳回不应写入"


def _names(engine) -> list[str]:
    with Session(engine) as db:
        rows = db.execute(
            select(PurchaseUnit.unit_name).execution_options(skip_tenant_filter=True)
        ).scalars()
        return list(rows)


def _row(engine, name: str):
    with Session(engine) as db:
        return db.execute(
            select(PurchaseUnit)
            .where(PurchaseUnit.unit_name == name)
            .execution_options(skip_tenant_filter=True)
        ).scalar_one_or_none()


@pytest.fixture()
def customers_db(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'business.sqlite'}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    PurchaseUnit.__table__.create(engine)
    TaskLifecycleRecord.__table__.create(engine)
    Customer.__table__.create(engine)
    SalesOrder.__table__.create(engine)
    SalesOrderItem.__table__.create(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(
        "app.application.customer_app_service.get_customers_session", lambda: factory()
    )
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setenv("AUDIT_LOG_PATH", str(audit))
    monkeypatch.setenv("SECRET_KEY", "approval-gate-test-secret-32bytes")
    return engine, audit


def _context(task_id: str, **extra) -> dict:
    body = {
        "tenant_id": "11",
        "user_id": "11",
        "employee_id": "employee-a",
        "task_id": task_id,
    }
    body.update(extra)
    return body


def _execute(task_id: str, name: str, **extra) -> dict:
    return AgentToolExecutor().execute(
        AgentStep(
            node_id="create",
            tool_id="customers",
            action="create",
            params={"unit_name": name},
        ),
        runtime_context=_context(task_id, **extra),
    )


def _reject(name: str = "reject me") -> tuple[InMemoryTaskExecutionRepository, str]:
    queue = InMemoryTaskExecutionRepository()
    run = AgentRun(user_id="11", message=name, status="queued")
    run.metadata["runtime_context"] = {"tenant_id": "11", "task_id": run.run_id}
    queue.enqueue(run)
    assert queue.claim("worker", lease_seconds=30) is not None
    queue.request_approval(run.run_id, "boss")
    queue.resolve_approval(run.run_id, "reject", "boss")
    return queue, run.run_id


def _audit_events(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_direct_execute_after_reject_writes_nothing(customers_db) -> None:
    engine, audit = customers_db
    _queue, task_id = _reject()
    result = _execute(task_id, REJECTED_NAME, approval_id="rejected")
    assert result.get("success") is not True
    assert result.get("reason") == "approval_rejected"
    assert REJECTED_NAME not in _names(engine)
    events = [
        item
        for item in _audit_events(audit)
        if item.get("action") == "security.approval_execution_denied"
    ]
    assert events
    details = events[-1]["details"]
    assert details["task_id"] == task_id
    assert details["tenant_id"] == "11"
    assert details["tool_id"] == "customers"
    assert details["action"] == "create"
    assert details["reason"] == "approval_rejected"


def test_tampered_approval_id_does_not_authorize(customers_db) -> None:
    engine, _audit = customers_db
    _queue, task_id = _reject()
    result = _execute(task_id, REJECTED_NAME, approval_id="approved", approved=True)
    assert result.get("success") is not True
    assert REJECTED_NAME not in _names(engine)


def test_other_task_approval_does_not_authorize(customers_db) -> None:
    engine, _audit = customers_db
    allowed = AgentRun(user_id="11", message="other", status="queued")
    allowed.metadata["runtime_context"] = {"tenant_id": "11"}
    queue = InMemoryTaskExecutionRepository()
    queue.enqueue(allowed)
    assert queue.claim("worker", lease_seconds=30) is not None
    queue.request_approval(allowed.run_id, "boss")
    queue.resolve_approval(allowed.run_id, "approve", "boss")
    _queue, blocked = _reject()
    result = _execute(blocked, REJECTED_NAME, approval_id=allowed.run_id)
    assert result.get("success") is not True
    assert REJECTED_NAME not in _names(engine)


def test_other_tenant_approval_does_not_authorize(customers_db) -> None:
    engine, _audit = customers_db
    queue = InMemoryTaskExecutionRepository()
    run = AgentRun(user_id="22", message="foreign", status="queued")
    run.metadata["runtime_context"] = {"tenant_id": "22"}
    queue.enqueue(run)
    assert queue.claim("worker", lease_seconds=30) is not None
    queue.request_approval(run.run_id, "boss")
    queue.resolve_approval(run.run_id, "approve", "boss")
    result = _execute(run.run_id, REJECTED_NAME, tenant_id="11", approval_id=run.run_id)
    assert result.get("success") is not True
    assert result.get("reason") == "approval_tenant_mismatch"
    assert REJECTED_NAME not in _names(engine)


def test_resubmit_after_reject_still_has_no_row(customers_db) -> None:
    engine, _audit = customers_db
    _queue, task_id = _reject()
    first = _execute(task_id, REJECTED_NAME)
    second = _execute(task_id, REJECTED_NAME, approval_id="approved")
    assert first.get("success") is not True
    assert second.get("success") is not True
    assert REJECTED_NAME not in _names(engine)


def test_waiting_approval_denies_before_write(customers_db) -> None:
    engine, _audit = customers_db
    queue = InMemoryTaskExecutionRepository()
    run = AgentRun(user_id="11", message="wait", status="queued")
    run.metadata["runtime_context"] = {"tenant_id": "11"}
    queue.enqueue(run)
    assert queue.claim("worker", lease_seconds=30) is not None
    queue.request_approval(run.run_id, "boss")
    result = _execute(run.run_id, REJECTED_NAME, approval_id="granted")
    assert result.get("reason") == "approval_required"
    assert queue.get(run.run_id).state == "waiting_approval"
    assert REJECTED_NAME not in _names(engine)


def test_expired_approval_denies_before_write(customers_db) -> None:
    engine, _audit = customers_db
    queue = InMemoryTaskExecutionRepository(approval_timeout_seconds=0)
    run = AgentRun(user_id="11", message="expire", status="queued")
    run.metadata["runtime_context"] = {"tenant_id": "11"}
    queue.enqueue(run)
    assert queue.claim("worker", lease_seconds=30) is not None
    queue.request_approval(run.run_id, "boss")
    result = _execute(run.run_id, REJECTED_NAME)
    assert result.get("reason") == "approval_expired"
    assert REJECTED_NAME not in _names(engine)


def test_logical_task_id_uses_its_current_run_approval(customers_db) -> None:
    engine, _audit = customers_db
    queue = InMemoryTaskExecutionRepository()
    run = AgentRun(user_id="11", message="logical task", status="queued")
    run.metadata.update(
        runtime_context={"tenant_id": "11"}, task_context={"task_id": "logical-task"}
    )
    queue.enqueue_waiting_approval(run, approver="boss")
    result = _execute("logical-task", REJECTED_NAME, run_id=run.run_id)
    assert result.get("reason") == "approval_required"
    assert queue.get(run.run_id).state == "waiting_approval"
    assert REJECTED_NAME not in _names(engine)


@pytest.mark.parametrize("run_binding", ["missing", "other"])
def test_run_id_cannot_detach_a_write_from_its_rejected_task(customers_db, run_binding) -> None:
    engine, _audit = customers_db
    queue, rejected_id = _reject()
    other = AgentRun(user_id="11", message="other", status="queued")
    other.metadata["runtime_context"] = {"tenant_id": "11"}
    queue.enqueue(other)
    assert queue.claim("worker", lease_seconds=30, run_id=other.run_id) is not None
    run_id = "missing-run" if run_binding == "missing" else other.run_id
    result = _execute(rejected_id, REJECTED_NAME, run_id=run_id)
    assert result.get("success") is not True
    assert result.get("reason") in {"approval_rejected", "approval_task_mismatch"}
    assert REJECTED_NAME not in _names(engine)


def test_approved_write_is_not_success_when_commit_fails(customers_db, monkeypatch) -> None:
    engine, _audit = customers_db
    queue = InMemoryTaskExecutionRepository()
    run = AgentRun(user_id="11", message="approve", status="queued")
    run.metadata["runtime_context"] = {"tenant_id": "11"}
    queue.enqueue(run)
    assert queue.claim("worker", lease_seconds=30) is not None
    queue.request_approval(run.run_id, "boss")
    assert queue.resolve_approval(run.run_id, "approve", "boss") is not None

    real_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def failing_session():
        session = real_factory()

        def fail_commit():
            raise OperationalError("INSERT", {}, Exception("disk full"))

        session.commit = fail_commit
        return session

    monkeypatch.setattr(
        "app.application.customer_app_service.get_customers_session", failing_session
    )
    result = _execute(run.run_id, NAME)
    assert result.get("success") is not True
    assert NAME not in _names(engine)


def test_ordinary_create_without_lifecycle_still_writes(customers_db) -> None:
    engine, _audit = customers_db
    result = _execute("erp-no-task-row", "普通客户无任务")
    assert result.get("success") is True
    row = _row(engine, "普通客户无任务")
    assert row is not None
    assert int(row.id) == int(result["data"]["id"])
    assert str(row.tenant_id) == "11"


def test_approved_customer_is_read_back_from_caller_database(customers_db) -> None:
    engine, _audit = customers_db
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict

    node = WorkflowNode(
        node_id="create-customer",
        tool_id="customers",
        action="create",
        params={"unit_name": NAME},
        risk="medium",
        idempotent=False,
    )
    plan = PlanGraph(plan_id="approved-customer-readback", intent="customer_create", nodes=[node])
    run = AgentRun(
        user_id="11",
        message="create customer needs approval",
        status="queued",
        steps=[
            AgentStep(
                node_id="create-customer",
                tool_id="customers",
                action="create",
                params={"unit_name": NAME},
                risk="medium",
                idempotent=False,
            )
        ],
    )
    run.plan_id = plan.plan_id
    run.metadata["plan"] = plan_to_dict(plan)
    run.metadata["runtime_context"] = _context(run.run_id)
    gate = AgentOrchestrator(
        repository=InMemoryAgentRunRepository(), dependencies=_runtime_dependencies()
    )
    gate._execute_ready_steps(run, runtime_context=run.metadata["runtime_context"])
    assert run.steps[0].status == "waiting_user"
    assert NAME not in _names(engine)
    gate._execute_ready_steps(
        run,
        runtime_context=run.metadata["runtime_context"],
        approved_step_id=run.steps[0].step_id,
    )
    row = _row(engine, NAME)
    assert row is not None
    assert str(row.tenant_id) == "11"
    assert run.steps[0].status == "completed"
    assert run.steps[0].params["unit_name"] == NAME
    assert int(run.steps[0].output["data"]["id"]) == int(row.id)
