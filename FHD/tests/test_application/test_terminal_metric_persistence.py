import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator import (
    AgentRun,
    InMemoryAgentRunRepository,
    SQLAlchemyAgentRunRepository,
)
from app.application.agent_orchestrator import run_terminal_metrics as metrics


@pytest.mark.parametrize("sql", [False, True])
@pytest.mark.parametrize("terminal", ["failed", "rejected", "cancelled", "completed"])
def test_terminal_transitions_count_once_at_persistence(tmp_path, monkeypatch, sql, terminal):
    seen = []
    monkeypatch.setattr(metrics, "observe_run_terminal", lambda **kw: seen.append(kw["status"]))
    engine = create_engine(f"sqlite:///{tmp_path}/runs.db")
    repo = (
        SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=engine))
        if sql
        else InMemoryAgentRunRepository()
    )
    run = AgentRun(user_id="test", message="reject/budget terminal persistence")
    repo.save(run)
    run.status = terminal
    repo.save(run)
    repo.save(run)
    repo.save(repo.get(run.run_id))
    assert seen == [terminal]
    run.status = "running"
    repo.save(run)
    run.status = "completed"
    repo.save(run)
    assert repo.get(run.run_id).status == terminal
    assert seen == [terminal], "plain saves cannot resurrect a terminal run or inflate metrics"
    completed = AgentRun(user_id="test", message="a distinct completed run", status="completed")
    repo.save(completed)
    repo.save(repo.get(completed.run_id))
    assert seen == [terminal, "completed"]
    engine.dispose()


def test_rolled_back_terminal_is_not_counted(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(metrics, "observe_run_terminal", lambda **kw: seen.append(kw["status"]))
    engine = create_engine(f"sqlite:///{tmp_path}/rollback.db")
    factory = sessionmaker(bind=engine)
    repo = SQLAlchemyAgentRunRepository(session_factory=factory)
    run = AgentRun(user_id="test", message="rollback")
    repo.save(run)
    with factory() as db:
        run.status = "failed"
        repo.save_in_session(db, run)
        assert seen == []
        db.rollback()
    assert seen == []
    assert repo.get(run.run_id).status != "failed"
    repo.save(run)
    assert seen == ["failed"]
    engine.dispose()


@pytest.mark.parametrize("commit_savepoint", [False, True])
def test_savepoint_keeps_only_metrics_that_reach_outer_commit(
    tmp_path, monkeypatch, commit_savepoint
):
    seen = []
    monkeypatch.setattr(metrics, "observe_run_terminal", lambda **kw: seen.append(kw["status"]))
    engine = create_engine(f"sqlite:///{tmp_path}/savepoint.db")
    factory = sessionmaker(bind=engine)
    repo = SQLAlchemyAgentRunRepository(session_factory=factory)
    outer = repo.save(AgentRun(user_id="u", message="outer"))
    inner = repo.save(AgentRun(user_id="u", message="savepoint"))
    with factory.begin() as db:
        outer.status = "failed"
        repo.save_in_session(db, outer)
        savepoint = db.begin_nested()
        inner.status = "cancelled"
        repo.save_in_session(db, inner)
        savepoint.commit() if commit_savepoint else savepoint.rollback()
        assert seen == [], "savepoint release is not the business commit"
    assert seen == (["failed", "cancelled"] if commit_savepoint else ["failed"])
    assert repo.get(inner.run_id).status == ("cancelled" if commit_savepoint else "queued")
    engine.dispose()


@pytest.mark.parametrize("sql", [False, True])
def test_metric_failure_cannot_turn_a_committed_task_into_execution_failure(
    tmp_path, monkeypatch, caplog, sql
):
    def broken(**kwargs):
        raise OSError("private metrics storage details")

    monkeypatch.setattr(metrics, "observe_run_terminal", broken)
    engine = create_engine(f"sqlite:///{tmp_path}/metric-error.db")
    repo = (
        SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=engine))
        if sql
        else InMemoryAgentRunRepository()
    )
    run = repo.save(AgentRun(user_id="u", message="already committed", status="completed"))
    assert repo.get(run.run_id).status == "completed"
    assert "metric unavailable" in caplog.text
    assert "private metrics storage details" not in caplog.text
    engine.dispose()
