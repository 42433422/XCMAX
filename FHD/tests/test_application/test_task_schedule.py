from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.task_execution_repository import (
    InMemoryTaskExecutionRepository,
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.task_schedule import normalize_scheduled_at


@pytest.mark.parametrize("value", [True, 7, {}, "tomorrow", "2030-01-01T08:00:00"])
def test_schedule_requires_explicit_valid_timezone(value):
    with pytest.raises(ValueError):
        normalize_scheduled_at(value)


def test_schedule_normalizes_same_instant():
    assert normalize_scheduled_at("2030-01-01T08:00:00+08:00") == (
        normalize_scheduled_at("2030-01-01T00:00:00Z")
    )


@pytest.mark.parametrize("persistent", [False, True])
def test_due_task_survives_reload_pause_resume_and_is_claimed_once(tmp_path, persistent):
    engine = create_engine(f"sqlite:///{tmp_path / 'schedule.db'}")
    factory = sessionmaker(bind=engine)
    repo = (
        SQLAlchemyTaskExecutionRepository(session_factory=factory)
        if persistent
        else InMemoryTaskExecutionRepository()
    )
    due = datetime.now(UTC) + timedelta(days=1)
    run = AgentRun(user_id="17", message="明天生成报表", status="queued")
    run.metadata.update(
        {
            "runtime_context": {"tenant_id": "7"},
            "task_context": {"task_id": "tomorrow-report"},
            "schedule": {"kind": "once", "scheduled_at": due.isoformat()},
        }
    )
    repo.enqueue(run, requested_by="17")
    if persistent:
        repo = SQLAlchemyTaskExecutionRepository(session_factory=factory)
    assert repo.claim("early", lease_seconds=10) is None
    repo.transition(run.run_id, "paused")
    assert repo.claim("paused", lease_seconds=10, now=due.isoformat()) is None
    repo.enqueue(run, requested_by="17")
    assert repo.get(run.run_id).available_at == due.isoformat()
    assert repo.claim("early", lease_seconds=10) is None
    claimed = repo.claim("due", lease_seconds=10, now=due.isoformat())
    assert claimed.user_id == "17" and claimed.tenant_id == "7"
    assert repo.claim("duplicate", lease_seconds=10, now=due.isoformat()) is None
    repo.finish(run.run_id, "due", "completed")
    assert repo.claim("later", lease_seconds=10, now=(due + timedelta(days=1)).isoformat()) is None
    engine.dispose()


def test_overdue_task_runs_once_after_restart(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'overdue.db'}")
    factory = sessionmaker(bind=engine)
    run = AgentRun(user_id="17", message="过期任务", status="queued")
    run.metadata["schedule"] = {"scheduled_at": "2020-01-01T00:00:00Z"}
    SQLAlchemyTaskExecutionRepository(session_factory=factory).enqueue(run)
    repo = SQLAlchemyTaskExecutionRepository(session_factory=factory)
    assert repo.claim("restarted", lease_seconds=10).run_id == run.run_id
    assert repo.claim("other", lease_seconds=10) is None
    engine.dispose()
