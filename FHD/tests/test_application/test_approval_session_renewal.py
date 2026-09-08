"""Session renewal shares the durable approval transaction and preserves identity."""

import os
import uuid

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
def renewal_engine(tmp_path):
    postgres_url = os.environ.get("XCAGI_TEST_AGENT_POSTGRES_URL")
    admin = None
    schema = "agent_test_" + uuid.uuid4().hex
    if postgres_url:
        admin = create_engine(postgres_url)
        with admin.begin() as db:
            db.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        engine = create_engine(
            postgres_url,
            connect_args={
                "options": f"-csearch_path={schema} -clock_timeout=3000 -cstatement_timeout=10000",
            },
        )
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'renewal.db'}")
    try:
        yield engine
    finally:
        engine.dispose()
        if admin is not None:
            with admin.begin() as db:
                db.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
            admin.dispose()


@pytest.fixture
def waiting_task(renewal_engine, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "session-renewal-test-" * 4)
    engine = renewal_engine
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


@pytest.mark.parametrize("waiting", [True, False])
@pytest.mark.parametrize("fail_enqueue", [True, False])
def test_resume_session_and_queue_commit_together(waiting_task, monkeypatch, waiting, fail_enqueue):
    from app.application.agent_orchestrator.resume_transaction import resume_and_enqueue

    runs, queue, factory, original, previous, _ = waiting_task
    run = runs.get(original.run_id)
    run.status = "paused"
    run.steps[0].status = "waiting_user" if waiting else "pending"
    run.metadata["control"] = {"resume_status": "running"}
    runs.save(run)
    before = runs.get(run.run_id).to_dict()
    enqueue = queue.enqueue_in_session

    def fail(db, run, **kwargs):
        enqueue(db, run, **kwargs)
        db.flush()
        raise RuntimeError("interrupted resume")

    if fail_enqueue:
        monkeypatch.setattr(queue, "enqueue_in_session", fail)

    def resume():
        return resume_and_enqueue(
            runs,
            queue,
            run_id=run.run_id,
            principal_id="owner",
            runtime_context={},
            authenticated_binding={**previous, "session_row_id": 2},
        )

    if fail_enqueue and not waiting:
        with pytest.raises(RuntimeError, match="interrupted resume"):
            resume()
        assert runs.get(run.run_id).to_dict() == before
        assert runs.latest_task_control(run.run_id) is None
        assert queue.get(run.run_id) is None
        monkeypatch.setattr(queue, "enqueue_in_session", enqueue)
    result = resume()
    assert result.status == ("waiting_user" if waiting else "queued")
    assert result.metadata["runtime_context"]["_mod_authorization"]["session_row_id"] == 2
    assert (queue.get(run.run_id) is None) == waiting
    assert runs.latest_task_control(run.run_id).status == "applied"
    with factory() as db:
        assert db.query(AgentApprovalConsumption).count() == 0


def test_resume_cannot_replace_an_outstanding_worker_claim(waiting_task):
    from app.application.agent_orchestrator.resume_transaction import resume_and_enqueue

    runs, queue, _, original, previous, _ = waiting_task
    queue.enqueue(original)
    claim = queue.claim("worker", lease_seconds=30)
    assert claim is not None
    run = runs.get(original.run_id)
    run.status = "paused"
    runs.save(run)
    before = runs.get(run.run_id).to_dict()
    with pytest.raises(ApprovalGrantError, match="执行权"):
        resume_and_enqueue(
            runs,
            queue,
            run_id=run.run_id,
            principal_id="owner",
            runtime_context={},
            authenticated_binding={**previous, "session_row_id": 2},
        )
    assert runs.get(run.run_id).to_dict() == before
    assert runs.latest_task_control(run.run_id) is None
    assert queue.get(run.run_id).lease_owner == "worker"


def test_http_resume_renews_session_without_bypassing_approval(waiting_task, monkeypatch):
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.fastapi_routes.domains.agent import route_support, routes
    from app.infrastructure.auth.agent_principal import AgentPrincipal, require_agent_principal

    runs, queue, _, original, previous, _ = waiting_task
    run = runs.get(original.run_id)
    run.status = "paused"
    run.metadata["control"] = {"resume_status": "running"}
    runs.save(run)
    monkeypatch.setattr(routes, "get_agent_run_repository", lambda: runs)
    monkeypatch.setattr(routes, "get_task_execution_repository", lambda: queue)
    monkeypatch.setattr(route_support, "get_task_execution_repository", lambda: queue)
    monkeypatch.setattr(
        routes,
        "AgentOrchestrator",
        lambda: SimpleNamespace(
            get_run=runs.get,
            latest_task_control=runs.latest_task_control,
        ),
    )
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[require_agent_principal] = lambda: AgentPrincipal(
        user_id="owner",
        tenant_id="tenant",
        mod_authorization={**previous, "session_row_id": 2},
    )
    response = TestClient(app).post(f"/api/agent/runs/{run.run_id}/resume", json={})
    assert response.status_code == 200
    assert runs.get(run.run_id).status == "waiting_user"
    assert (
        runs.get(run.run_id).metadata["runtime_context"]["_mod_authorization"]["session_row_id"]
        == 2
    )
    assert queue.get(run.run_id) is None


def test_worker_claim_between_resume_read_and_write_prevents_resume(waiting_task, monkeypatch):
    from contextlib import contextmanager

    from app.application.agent_orchestrator.resume_transaction import resume_and_enqueue
    from app.db.models.agent import AgentTaskExecutionRecord

    runs, queue, _, original, previous, _ = waiting_task
    with runs.transaction(read_only=True) as db:
        if db.get_bind().dialect.name != "sqlite":
            pytest.skip("SQLite-specific FOR UPDATE interleaving; PostgreSQL holds the row lock")
    run = runs.get(original.run_id)
    run.status = "paused"
    run.steps[0].status = "pending"
    runs.save(run)
    queue.enqueue(run)
    before = runs.get(run.run_id).to_dict()
    transaction = runs.transaction

    @contextmanager
    def interleaved_transaction(**kwargs):
        with transaction(**kwargs) as db:
            query = db.query

            class InterleavedQuery:
                def __init__(self, inner):
                    self.inner = inner

                def filter_by(self, **values):
                    self.inner = self.inner.filter_by(**values)
                    return self

                def with_for_update(self):
                    self.inner = self.inner.with_for_update()
                    return self

                def one_or_none(self):
                    observed = self.inner.one_or_none()
                    assert queue.claim("interleaved-worker", lease_seconds=30) is not None
                    db.query = query
                    return observed

            db.query = lambda model: (
                InterleavedQuery(query(model))
                if model is AgentTaskExecutionRecord
                else query(model)
            )
            yield db

    monkeypatch.setattr(runs, "transaction", interleaved_transaction)
    with pytest.raises(ApprovalGrantError):
        resume_and_enqueue(
            runs,
            queue,
            run_id=run.run_id,
            principal_id="owner",
            runtime_context={},
            authenticated_binding={**previous, "session_row_id": 2},
        )
    assert runs.get(run.run_id).to_dict() == before
    assert runs.latest_task_control(run.run_id) is None
    assert queue.get(run.run_id).lease_owner == "interleaved-worker"


def test_postgres_resume_holds_queue_lock_until_commit(waiting_task, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from app.application.agent_orchestrator.resume_transaction import resume_and_enqueue

    runs, queue, _, original, previous, _ = waiting_task
    with runs.transaction(read_only=True) as db:
        if db.get_bind().dialect.name != "postgresql":
            pytest.skip("Requires explicit isolated PostgreSQL test URL")
    run = runs.get(original.run_id)
    run.status = "paused"
    run.steps[0].status = "pending"
    runs.save(run)
    queue.enqueue(run)
    save = runs.save_in_session
    attempts = []

    def save_with_competing_claim(db, updated):
        with pytest.raises(OperationalError) as caught:
            queue.claim("competing-worker", lease_seconds=30)
        assert getattr(caught.value.orig, "sqlstate", None) == "55P03"
        attempts.append("blocked_by_resume_transaction")
        return save(db, updated)

    monkeypatch.setattr(runs, "save_in_session", save_with_competing_claim)
    result = resume_and_enqueue(
        runs,
        queue,
        run_id=run.run_id,
        principal_id="owner",
        runtime_context={},
        authenticated_binding={**previous, "session_row_id": 2},
    )
    assert result.status == "queued"
    assert attempts == ["blocked_by_resume_transaction"]
    claimed = queue.claim("after-commit-worker", lease_seconds=30)
    assert claimed is not None and claimed.run_id == run.run_id
    assert claimed.execution_count == 1


def test_durable_resume_rejects_unreconciled_result(waiting_task):
    from app.application.agent_orchestrator.resume_transaction import resume_and_enqueue

    runs, queue, factory, original, previous, _ = waiting_task
    run = runs.get(original.run_id)
    run.status = "paused"
    run.steps[0].status = "pending"
    run.metadata["recovery"] = {"state": "manual_reconciliation_required"}
    runs.save(run)
    before = runs.get(run.run_id).to_dict()
    with pytest.raises(ApprovalGrantError, match="核对"):
        resume_and_enqueue(
            runs,
            queue,
            run_id=run.run_id,
            principal_id="owner",
            runtime_context={},
            authenticated_binding=previous,
        )
    assert runs.get(run.run_id).to_dict() == before
    assert runs.latest_task_control(run.run_id) is None
    assert queue.get(run.run_id) is None
