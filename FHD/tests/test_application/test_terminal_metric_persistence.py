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
    assert seen == [terminal]
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
