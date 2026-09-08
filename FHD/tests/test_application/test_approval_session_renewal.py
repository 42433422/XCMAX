"""Session renewal shares the durable approval transaction and preserves identity."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.approval_grant import (
    ApprovalGrantError,
    issue_approval_grant,
)
from app.application.agent_orchestrator.approval_transaction import approve_and_enqueue
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.db.models.agent_approval import AgentApprovalConsumption


@pytest.fixture
def waiting_task(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "session-renewal-test-" * 4)
    engine = create_engine(f"sqlite:///{tmp_path / 'renewal.db'}")
    factory = sessionmaker(bind=engine)
    runs = SQLAlchemyAgentRunRepository(session_factory=factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=factory)
    binding = {
        "session_row_id": 1,
        "user_id": "owner",
        "mod_id": "sales",
        "account_tenant_id": "tenant",
        "account_role": "user",
    }
    run = AgentRun(
        user_id="owner",
        message="approve",
        status="waiting_user",
        steps=[
            AgentStep(node_id="node", tool_id="sales", action="create_order", status="waiting_user")
        ],
        metadata={"runtime_context": {"tenant_id": "tenant", "_mod_authorization": binding}},
    )
    runs.save(run)
    queue.get(run.run_id)
    AgentApprovalConsumption.__table__.create(engine)
    grant = issue_approval_grant(run, principal_id="owner")["grant"]
    try:
        yield runs, queue, factory, run, binding, grant
    finally:
        engine.dispose()


def approve(task, binding):
    runs, queue, _, run, _, grant = task
    return approve_and_enqueue(
        runs,
        queue,
        run_id=run.run_id,
        token=grant,
        principal_id="owner",
        runtime_context={},
        authenticated_binding=binding,
    )


def test_same_identity_session_renewal_commits_with_approval(waiting_task):
    runs, queue, factory, original, previous, _ = waiting_task
    replacement = {**previous, "session_row_id": 2}
    approve(waiting_task, replacement)
    persisted = runs.get(original.run_id)
    assert persisted.metadata["runtime_context"] == {
        "tenant_id": "tenant",
        "_mod_authorization": replacement,
    }
    assert persisted.status == "queued"
    assert queue.get(original.run_id) is not None
    assert len([e for e in persisted.events if e.event_type == "task.session_renewed"]) == 1
    with factory() as db:
        assert db.query(AgentApprovalConsumption).count() == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("user_id", "other"),
        ("mod_id", "other"),
        ("account_tenant_id", "other"),
        ("account_role", "admin"),
        ("session_row_id", True),
        ("session_row_id", 0),
    ],
)
def test_scope_change_rejects_before_consumption(waiting_task, field, value):
    runs, queue, factory, original, previous, _ = waiting_task
    before = runs.get(original.run_id).to_dict()
    with pytest.raises(ApprovalGrantError):
        approve(waiting_task, {**previous, "session_row_id": 2, field: value})
    assert runs.get(original.run_id).to_dict() == before
    assert queue.get(original.run_id) is None
    with factory() as db:
        assert db.query(AgentApprovalConsumption).count() == 0


def test_enqueue_failure_rolls_back_session_and_allows_retry(waiting_task, monkeypatch):
    runs, queue, factory, original, previous, _ = waiting_task
    before = runs.get(original.run_id).to_dict()
    enqueue = queue.enqueue_in_session

    def fail(db, run, **kwargs):
        enqueue(db, run, **kwargs)
        db.flush()
        raise RuntimeError("queue failure")

    monkeypatch.setattr(queue, "enqueue_in_session", fail)
    replacement = {**previous, "session_row_id": 2}
    with pytest.raises(RuntimeError, match="queue failure"):
        approve(waiting_task, replacement)
    assert runs.get(original.run_id).to_dict() == before
    assert queue.get(original.run_id) is None
    with factory() as db:
        assert db.query(AgentApprovalConsumption).count() == 0
    monkeypatch.setattr(queue, "enqueue_in_session", enqueue)
    assert approve(waiting_task, replacement).status == "queued"


@pytest.mark.parametrize("missing", ["account_tenant_id", "account_role", "session_row_id"])
def test_legacy_incomplete_binding_requires_reconciliation(waiting_task, missing):
    runs, queue, factory, original, previous, _ = waiting_task
    legacy = runs.get(original.run_id)
    del legacy.metadata["runtime_context"]["_mod_authorization"][missing]
    runs.save(legacy)
    before = runs.get(original.run_id).to_dict()
    with pytest.raises(ApprovalGrantError):
        approve(waiting_task, {**previous, "session_row_id": 2})
    assert runs.get(original.run_id).to_dict() == before
    assert queue.get(original.run_id) is None
    with factory() as db:
        assert db.query(AgentApprovalConsumption).count() == 0
