from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.recurrence import next_occurrence, normalize_recurrence
from app.application.agent_orchestrator.recurring_schedule_service import RecurringScheduleService
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.schedule_repository import ScheduleRepository
from app.infrastructure.auth.agent_principal import AgentPrincipal


@pytest.fixture
def runtime(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'schedule.sqlite'}", connect_args={"check_same_thread": False}
    )
    factory = sessionmaker(bind=engine)
    runs = SQLAlchemyAgentRunRepository(session_factory=factory)
    # Host lifespan initializes tables before starting background dispatchers.
    runs.get("")
    service = RecurringScheduleService(
        ScheduleRepository(factory), AgentOrchestrator(repository=runs)
    )
    yield service, factory
    engine.dispose()


def _create(service, **overrides):
    return service.create(
        {
            "task_id": "daily-inventory",
            "tool_id": "products",
            "action": "query",
            "params": {"keyword": "sample"},
            "scheduled_at": "2030-01-01T00:00:00Z",
            "recurrence": {"kind": "interval", "seconds": 3600},
            **overrides,
        },
        AgentPrincipal(user_id="17", tenant_id="7"),
    )


def test_recurrence_midnight_dst_gap_and_fold():
    midnight = {"kind": "daily", "hour": 0, "timezone": "Asia/Shanghai"}
    assert (
        next_occurrence(midnight, "2030-01-01T16:00:00Z", "2030-01-01T16:00:00Z")
        == "2030-01-02T16:00:00+00:00"
    )
    gap = {"kind": "daily", "hour": 2, "minute": 30, "timezone": "America/New_York"}
    assert (
        next_occurrence(gap, "2026-03-07T07:30:00Z", "2026-03-07T07:30:00Z")
        == "2026-03-09T06:30:00+00:00"
    )
    fold = {"kind": "daily", "hour": 1, "minute": 30, "timezone": "America/New_York"}
    assert (
        next_occurrence(fold, "2026-11-01T05:30:00Z", "2026-11-01T05:30:00Z")
        == "2026-11-02T06:30:00+00:00"
    )


@pytest.mark.parametrize(
    "rule",
    [
        {},
        {"kind": "interval", "seconds": True},
        {"kind": "interval", "seconds": 1},
        {"kind": "daily", "hour": 24, "timezone": "UTC"},
    ],
)
def test_invalid_recurrence(rule):
    with pytest.raises(ValueError):
        normalize_recurrence(rule)


def test_persistent_occurrences_approval_no_overlap_and_missed_coalescing(runtime):
    service, factory = runtime
    row = _create(service)
    assert _create(service)["deduplicated"]
    with pytest.raises(ValueError):
        _create(service, recurrence={"kind": "interval", "seconds": 7200})
    # Recreate both repositories, proving it is not an in-memory timer.
    runs = SQLAlchemyAgentRunRepository(session_factory=factory)
    service = RecurringScheduleService(
        ScheduleRepository(factory), AgentOrchestrator(repository=runs)
    )
    assert service.tick("worker", now="2029-12-31T23:59:59Z") is False
    assert service.tick("worker", now="2030-01-01T00:00:00Z") is True
    stored = service.repository.list_owned("17", "7")[0]
    task = service.orchestrator.get_task(
        user_id="17", tenant_id="7", task_id=stored["last_task_id"]
    )
    assert task.status == "waiting_user"
    run = runs.get(task.active_run_id)
    assert run.user_id == "17" and run.metadata["runtime_context"]["tenant_id"] == "7"
    assert not run.tool_calls
    # Several missed times do not produce an approval backlog.
    service.tick("worker", now="2030-01-03T00:30:00Z")
    assert len(runs.list_tasks(user_id="17", tenant_id="7")) == 1
    assert service.repository.list_owned("17", "7")[0]["next_run_at"] == "2030-01-03T01:00:00+00:00"
    run.status = "cancelled"
    runs.save(run)
    service.tick("worker", now="2030-01-03T01:00:00Z")
    assert len(runs.list_tasks(user_id="17", tenant_id="7")) == 2
    assert service.repository.list_owned("other", "7") == []
    assert not service.repository.control(row["schedule_id"], "17", "8", "pause")


def test_claim_is_exclusive_recoverable_and_old_worker_cannot_finish(runtime):
    service, factory = runtime
    row = _create(service)
    repos = [ScheduleRepository(factory), ScheduleRepository(factory)]
    with ThreadPoolExecutor(2) as pool:
        claims = list(
            pool.map(lambda i: repos[i].claim(f"w{i}", now="2030-01-01T00:00:00+00:00"), range(2))
        )
    winner = next(item for item in claims if item)
    assert sum(item is not None for item in claims) == 1
    recovered = repos[0].claim("recovery", now="2030-01-01T00:02:00+00:00")
    assert recovered["next_run_at"] == winner["next_run_at"]
    assert not repos[1].finish(
        row["schedule_id"], winner["lease_owner"], next_run_at="2099-01-01T00:00:00Z"
    )
    assert repos[0].finish(row["schedule_id"], "recovery", next_run_at="2030-01-01T01:00:00+00:00")


def test_pause_resume_cancel_and_publication_replay(runtime, monkeypatch):
    service, _ = runtime
    row = _create(service)
    repo = service.repository
    assert repo.control(row["schedule_id"], "17", "7", "pause")
    assert not service.tick("worker", now="2030-01-01T00:00:00Z")
    assert repo.control(row["schedule_id"], "17", "7", "resume")
    original = repo.finish
    calls = 0

    def crash_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("lost receipt after durable task save")
        return original(*args, **kwargs)

    monkeypatch.setattr(repo, "finish", crash_once)
    service.tick("worker", now="2030-01-01T00:00:00Z")
    assert repo.list_owned("17", "7")[0]["state"] == "paused"
    repo.control(row["schedule_id"], "17", "7", "resume")
    service.tick("worker", now="2030-01-01T00:02:00Z")
    assert len(service.orchestrator.list_tasks(user_id="17", tenant_id="7")) == 1
    assert repo.control(row["schedule_id"], "17", "7", "cancel")
    assert not repo.control(row["schedule_id"], "17", "7", "resume")
    assert not service.tick("worker", now="2030-01-02T00:00:00Z")


def test_failed_inflight_publication_cannot_resurrect_cancelled_schedule(runtime):
    service, _ = runtime
    row = _create(service)
    repo = service.repository
    repo.claim("worker", now="2030-01-01T00:00:00+00:00")
    repo.control(row["schedule_id"], "17", "7", "cancel")
    repo.finish(
        row["schedule_id"], "worker", next_run_at="2030-01-01T01:00:00+00:00", error="failed"
    )
    assert repo.list_owned("17", "7")[0]["state"] == "cancelled"


def test_schedule_http_and_model_entrypoints_are_account_scoped(runtime, monkeypatch):
    import json
    from unittest.mock import patch

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.tools.registered_capabilities import execute_registered_capability
    from app.application.tools.scheduled_capability import manage_schedule
    from app.fastapi_routes.domains.agent import schedule_routes
    from app.infrastructure.auth.agent_principal import require_agent_principal

    service, factory = runtime
    app = FastAPI()
    app.include_router(schedule_routes.router)
    principal = AgentPrincipal(user_id="17", tenant_id="7")
    app.dependency_overrides[require_agent_principal] = lambda: principal
    monkeypatch.setattr(schedule_routes, "RecurringScheduleService", lambda: service)
    client = TestClient(app)
    args = {
        "task_id": "model-recurring",
        "tool_id": "products",
        "action": "query",
        "params": {"keyword": "sample"},
        "scheduled_at": "2030-01-01T00:00:00Z",
        "recurrence": {"kind": "daily", "hour": 0, "timezone": "Asia/Shanghai"},
    }
    with (
        patch(
            "app.application.tools.scheduled_capability.get_current_request", return_value=object()
        ),
        patch(
            "app.application.tools.scheduled_capability.require_agent_principal",
            return_value=principal,
        ),
        patch(
            "app.application.agent_orchestrator.recurring_schedule_service.RecurringScheduleService",
            return_value=service,
        ),
        patch(
            "app.application.agent_orchestrator.schedule_repository.ScheduleRepository",
            return_value=service.repository,
        ),
    ):
        created = json.loads(execute_registered_capability(args))
        assert created["schedule_created"] and not created["operation_executed"]
        assert created["approval_policy"] == "each_occurrence"
        assert (
            json.loads(manage_schedule({"action": "list"}))["schedules"][0]["schedule_id"]
            == created["schedule_id"]
        )
    schedule_id = created["schedule_id"]
    assert client.post("/api/agent/schedules", json=args).json()["data"]["deduplicated"]
    assert client.get("/api/agent/schedules").json()["data"][0]["state"] == "active"
    principal = AgentPrincipal(user_id="18", tenant_id="7")
    assert client.get("/api/agent/schedules").json()["data"] == []
    assert client.post(f"/api/agent/schedules/{schedule_id}/cancel").status_code == 404
    principal = AgentPrincipal(user_id="17", tenant_id="7")
    assert client.post(f"/api/agent/schedules/{schedule_id}/pause").status_code == 200
    assert client.post(f"/api/agent/schedules/{schedule_id}/resume").status_code == 200
    assert client.post(f"/api/agent/schedules/{schedule_id}/cancel").status_code == 200


def test_schedule_migration_upgrades_existing_database_and_matches_model(tmp_path):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    from app.db.models.agent_schedule import AgentScheduleRecord

    path = Path(__file__).resolve().parents[2] / "alembic/versions/2026_09_08_agent_schedules.py"
    spec = importlib.util.spec_from_file_location("schedule_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.sqlite'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE existing_business_data (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO existing_business_data VALUES (17)")
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            module.upgrade()
        inspector = inspect(connection)
        assert {column["name"] for column in inspector.get_columns("agent_schedules")} == {
            column.name for column in AgentScheduleRecord.__table__.columns
        }
        assert {index["name"] for index in inspector.get_indexes("agent_schedules")} == {
            "ix_agent_schedules_due",
            "ix_agent_schedules_account",
        }
        assert connection.exec_driver_sql("SELECT id FROM existing_business_data").scalar() == 17
    engine.dispose()


def test_running_dispatcher_publishes_due_occurrence_without_executing_it(runtime):
    import time
    from unittest.mock import Mock

    from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher
    from app.application.agent_orchestrator.task_execution_repository import (
        InMemoryTaskExecutionRepository,
    )

    service, factory = runtime
    _create(service, scheduled_at="2020-01-01T00:00:00Z")
    runs = SQLAlchemyAgentRunRepository(session_factory=factory)
    executor = Mock()
    dispatcher = AgentTaskDispatcher(
        run_repository=runs,
        execution_repository=InMemoryTaskExecutionRepository(),
        orchestrator_factory=lambda repository: AgentOrchestrator(
            repository=repository, tool_executor=executor
        ),
    )
    dispatcher._schedule_service = service
    dispatcher.start()
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            tasks = runs.list_tasks(user_id="17", tenant_id="7")
            if tasks and tasks[0].status == "waiting_user":
                break
            time.sleep(0.02)
        tasks = runs.list_tasks(user_id="17", tenant_id="7")
        assert len(tasks) == 1 and tasks[0].status == "waiting_user"
        executor.execute.assert_not_called()
    finally:
        dispatcher.stop()
