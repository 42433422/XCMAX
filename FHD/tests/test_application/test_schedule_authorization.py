from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.recurring_schedule_service import RecurringScheduleService
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.schedule_authorization import ScheduleAuthorizations
from app.application.agent_orchestrator.schedule_repository import ScheduleRepository
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.db.models.user import User
from app.infrastructure.auth.agent_principal import AgentPrincipal

OWNER = AgentPrincipal(user_id="17", tenant_id="7")


@pytest.fixture
def runtime(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'consent.sqlite'}", connect_args={"check_same_thread": False}
    )
    User.__table__.create(engine, checkfirst=True)
    factory = sessionmaker(bind=engine)
    with factory.begin() as db:
        db.add(
            User(
                id=17,
                username="schedule-owner",
                password="test-password-hash",
                tenant_id=7,
                is_active=True,
            )
        )
    runs = SQLAlchemyAgentRunRepository(session_factory=factory)
    runs.get("")
    executor = Mock()
    executor.execute.return_value = {"success": True, "data": []}
    orchestrator = AgentOrchestrator(repository=runs, tool_executor=executor)
    orchestrator._record_tool_usage_entry = lambda *_: True
    queue = SQLAlchemyTaskExecutionRepository(session_factory=factory)
    repo = ScheduleRepository(factory)
    service = RecurringScheduleService(repo, orchestrator, queue)
    row = service.create(
        {
            "task_id": "auto-query",
            "tool_id": "products",
            "action": "query",
            "params": {"keyword": "sample"},
            "scheduled_at": "2030-01-01T00:00:00Z",
            "recurrence": {"kind": "interval", "seconds": 3600},
        },
        OWNER,
    )
    authorization = ScheduleAuthorizations(repo)
    yield service, row, authorization, factory, executor
    engine.dispose()


def _grant(authorization, row, max_runs=2):
    scope = authorization.inspect(row["schedule_id"], OWNER)
    return authorization.grant(
        row["schedule_id"],
        OWNER,
        expires_at="2031-01-01T00:00:00Z",
        max_runs=max_runs,
        expected_scope_hash=scope["scope_hash"],
    )


def _run():
    run = AgentRun(user_id="17", message="scheduled", status="waiting_user")
    run.metadata["runtime_context"] = {"tenant_id": "7"}
    run.steps = [
        AgentStep(
            node_id="query",
            tool_id="products",
            action="query",
            params={"keyword": "sample"},
            risk="low",
            status="waiting_user",
        )
    ]
    return run


def test_concurrent_reservations_cannot_exceed_quota_and_replay_is_free(runtime):
    service, row, authorization, factory, _ = runtime
    _grant(authorization, row, max_runs=1)
    candidates = [_run(), _run()]
    with ThreadPoolExecutor(2) as pool:
        receipts = list(
            pool.map(
                lambda run: ScheduleAuthorizations(ScheduleRepository(factory)).reserve(
                    row["schedule_id"], run, now="2030-01-01T00:00:00Z"
                ),
                candidates,
            )
        )
    assert sum(bool(value) for value in receipts) == 1
    winner = candidates[next(i for i, value in enumerate(receipts) if value)]
    assert authorization.reserve(row["schedule_id"], winner, now="2030-01-01T01:00:00Z")
    assert authorization.inspect(row["schedule_id"], OWNER)["authorization"]["reserved_runs"] == 1


def test_consent_matches_owner_parameters_deadline_and_revocation(runtime):
    service, row, authorization, factory, _ = runtime
    with pytest.raises(ValueError):
        authorization.grant(
            row["schedule_id"],
            AgentPrincipal(user_id="18", tenant_id="7"),
            expires_at="2031-01-01T00:00:00Z",
            max_runs=1,
            expected_scope_hash="bad",
        )
    _grant(authorization, row)
    run = _run()
    run.steps[0].params["keyword"] = "different"
    assert not authorization.reserve(row["schedule_id"], run)
    run = _run()
    assert not authorization.reserve(row["schedule_id"], run, now="2032-01-01T00:00:00Z")
    receipt = authorization.reserve(row["schedule_id"], run)
    run.metadata["schedule_authorization"] = {
        "schedule_id": row["schedule_id"],
        "authorization_id": receipt,
    }
    assert authorization.valid_for_execution(run)
    with factory.begin() as db:
        db.get(User, 17).is_active = False
    assert not authorization.valid_for_execution(run)
    with factory.begin() as db:
        db.get(User, 17).is_active = True
    assert authorization.revoke(row["schedule_id"], OWNER)
    assert not authorization.valid_for_execution(run)
    replacement = _grant(authorization, row)
    assert authorization.reserve(row["schedule_id"], run) == replacement["authorization_id"]


def test_due_authorized_run_executes_and_next_occurrence_exhausts_quota(runtime):
    service, row, authorization, _, executor = runtime
    _grant(authorization, row, max_runs=1)
    assert service.tick("timer", now="2030-01-01T00:00:00Z")
    task = service.orchestrator.list_tasks(user_id="17", tenant_id="7")[0]
    run = service.orchestrator.get_run(task.active_run_id)
    assert run.status == "queued" and run.metadata["schedule_authorization"]
    queue = service.execution_repository
    claimed = queue.claim("worker", lease_seconds=30, now="2030-01-01T00:00:00+00:00")
    assert claimed.run_id == run.run_id
    with patch(
        "app.application.agent_orchestrator.schedule_authorization.ScheduleAuthorizations",
        return_value=authorization,
    ):
        completed = service.orchestrator.execute_dispatched_run(run.run_id)
    assert completed.status == "completed"
    executor.execute.assert_called_once()
    queue.finish(run.run_id, "worker", "completed")
    service.tick("timer", now="2030-01-01T01:00:00Z")
    tasks = service.orchestrator.list_tasks(user_id="17", tenant_id="7")
    assert len(tasks) == 2 and sum(task.status == "waiting_user" for task in tasks) == 1


@pytest.mark.parametrize("control", ["pause", "cancel", "revoke"])
def test_pending_automatic_run_returns_to_approval_after_control(runtime, control):
    service, row, authorization, _, executor = runtime
    _grant(authorization, row)
    service.tick("timer", now="2030-01-01T00:00:00Z")
    task = service.orchestrator.list_tasks(user_id="17", tenant_id="7")[0]
    if control == "revoke":
        authorization.revoke(row["schedule_id"], OWNER)
    else:
        service.repository.control(row["schedule_id"], "17", "7", control)
    with patch(
        "app.application.agent_orchestrator.schedule_authorization.ScheduleAuthorizations",
        return_value=authorization,
    ):
        blocked = service.orchestrator.execute_dispatched_run(task.active_run_id)
    assert blocked.status == "waiting_user"
    assert blocked.steps[0].status == "waiting_user"
    executor.execute.assert_not_called()
    manual = service.orchestrator.stage_approved_run(
        blocked.run_id, approved_by="17", approved_step_id=blocked.steps[0].step_id
    )
    assert "schedule_authorization" not in manual.metadata


def test_authorization_http_requires_reviewed_scope_and_can_activate_existing_task(runtime):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.fastapi_routes.domains.agent import schedule_routes
    from app.infrastructure.auth.agent_principal import require_agent_principal

    service, row, authorization, _, _ = runtime
    service.tick("timer", now="2030-01-01T00:00:00Z")
    task = service.orchestrator.list_tasks(user_id="17", tenant_id="7")[0]
    assert task.status == "waiting_user"
    app = FastAPI()
    app.include_router(schedule_routes.router)
    principal = OWNER
    app.dependency_overrides[require_agent_principal] = lambda: principal
    path = f"/api/agent/schedules/{row['schedule_id']}/authorization"
    with (
        patch(
            "app.application.agent_orchestrator.schedule_authorization.ScheduleAuthorizations",
            return_value=authorization,
        ),
        patch.object(schedule_routes, "RecurringScheduleService", return_value=service),
    ):
        client = TestClient(app)
        inspected = client.get(path).json()["data"]
        assert inspected["operation"]["params"] == {"keyword": "sample"}
        body = {
            "scope_hash": inspected["scope_hash"],
            "expires_at": "2031-01-01T00:00:00Z",
            "max_runs": 3,
        }
        assert client.post(path, json={**body, "scope_hash": "stale"}).status_code == 400
        assert client.post(path, json={**body, "max_runs": True}).status_code == 400
        principal = AgentPrincipal(user_id="18", tenant_id="7")
        assert client.get(path).status_code == 404
        assert client.post(path, json=body).status_code == 400
        principal = OWNER
        assert client.post(path, json=body).json()["success"]
        run = service.orchestrator.get_run(task.active_run_id)
        assert run.status == "queued" and service.execution_repository.get(run.run_id)
        assert client.delete(path).json()["data"]["revoked"]
        assert not authorization.valid_for_execution(run)


def test_renewing_revoked_consent_requeues_the_waiting_occurrence(runtime):
    service, row, authorization, _, _ = runtime
    _grant(authorization, row)
    service.tick("timer", now="2030-01-01T00:00:00Z")
    task = service.orchestrator.list_tasks(user_id="17", tenant_id="7")[0]
    queue = service.execution_repository
    queue.claim("worker", lease_seconds=30, now="2030-01-01T00:00:00+00:00")
    authorization.revoke(row["schedule_id"], OWNER)
    with patch(
        "app.application.agent_orchestrator.schedule_authorization.ScheduleAuthorizations",
        return_value=authorization,
    ):
        blocked = service.orchestrator.execute_dispatched_run(task.active_run_id)
    queue.finish(blocked.run_id, "worker", "blocked")
    replacement = _grant(authorization, row)
    service.activate_pending(row["schedule_id"], OWNER)
    renewed = service.orchestrator.get_run(blocked.run_id)
    assert renewed.status == "queued"
    assert (
        renewed.metadata["schedule_authorization"]["authorization_id"]
        == replacement["authorization_id"]
    )
    assert queue.get(renewed.run_id).state == "queued"


def test_authorization_migration_preserves_existing_data_and_composite_receipts(tmp_path):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    from app.db.models.schedule_authorization import (
        ScheduleAuthorizationRecord,
        ScheduleAuthorizationUseRecord,
    )

    path = Path(__file__).resolve().parents[2] / "alembic/versions/2026_09_08_schedule_consent.py"
    spec = importlib.util.spec_from_file_location("consent_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.sqlite'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE existing_customer_data (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO existing_customer_data VALUES (17)")
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            module.upgrade()
        inspector = inspect(connection)
        for model in (ScheduleAuthorizationRecord, ScheduleAuthorizationUseRecord):
            assert {column["name"] for column in inspector.get_columns(model.__tablename__)} == {
                column.name for column in model.__table__.columns
            }
        assert set(
            inspector.get_pk_constraint("agent_schedule_authorization_uses")["constrained_columns"]
        ) == {"run_id", "authorization_id"}
        assert connection.exec_driver_sql("SELECT id FROM existing_customer_data").scalar() == 17
    engine.dispose()
