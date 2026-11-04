"""Real SQLite fencing; helpers do not activate dispatch or trust caller claims."""

import multiprocessing

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator import business_write_guard as guard
from app.application.agent_orchestrator.run_sql_repository import (
    SQLAlchemyAgentRunRepository,
)
from app.application.agent_orchestrator.task_execution_models import AgentTaskExecution
from app.application.agent_orchestrator.worker_repository import (
    ClaimedRunRepository,
    WorkerLeaseLost,
)
from app.db.db_base import Base
from app.db.models.agent import AgentTaskExecutionRecord


@pytest.fixture
def claim_db(tmp_path, monkeypatch):
    from app import db as host_db

    engine = create_engine(f"sqlite:///{tmp_path / 'host.sqlite'}")
    mod = create_engine(f"sqlite:///{tmp_path / 'mod.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(host_db, "HostSessionLocal", factory)
    for bind in (engine, mod):
        with bind.begin() as db:
            db.execute(text("CREATE TABLE effects (value INTEGER)"))
    with factory.begin() as db:
        db.add(
            AgentTaskExecutionRecord(
                run_id="run",
                task_id="task",
                user_id="user",
                state="claimed",
                available_at="",
                created_at="",
                updated_at="",
                lease_owner="owner",
                lease_expires_at="2999-01-01T00:00:00+00:00",
                execution_count=1,
            )
        )
    execution = AgentTaskExecution(run_id="run", task_id="task", user_id="user", execution_count=1)
    try:
        yield (
            SQLAlchemyAgentRunRepository(session_factory=factory, auto_create=False),
            execution,
            mod,
        )
    finally:
        engine.dispose()
        mod.dispose()


@pytest.mark.parametrize("separate", [False, True])
@pytest.mark.parametrize(
    "change",
    [
        {"lease_owner": "other"},
        {"execution_count": 2},
        {"lease_expires_at": "2000-01-01T00:00:00+00:00"},
        {"state": "completed"},
    ],
)
def test_stale_claim_prevents_business_effects(claim_db, separate, change):
    repository, execution, mod = claim_db
    factory = sessionmaker(bind=mod) if separate else repository._session_factory
    with repository.transaction() as db:
        db.query(AgentTaskExecutionRecord).filter_by(run_id="run").update(change)
    with guard.worker_claim_scope(repository, execution, "owner"):
        with pytest.raises(WorkerLeaseLost), factory.begin() as business:
            with guard.worker_write_guard(business):
                business.execute(text("INSERT INTO effects VALUES (1)"))
    for sessions in (factory, repository._session_factory):
        with sessions() as db:
            assert db.execute(text("SELECT COUNT(*) FROM effects")).scalar_one() == 0


def test_caller_mutation_cannot_upgrade_held_claim(claim_db):
    repository, execution, _ = claim_db
    with guard.worker_claim_scope(repository, execution, "owner"):
        execution.execution_count = 2
        with repository.transaction() as db:
            db.query(AgentTaskExecutionRecord).filter_by(run_id="run").update(
                {"execution_count": 2}
            )
        with (
            pytest.raises(WorkerLeaseLost),
            repository._session_factory.begin() as business,
        ):
            with guard.worker_write_guard(business):
                business.execute(text("INSERT INTO effects VALUES (1)"))
    with repository.transaction(read_only=True) as db:
        assert db.execute(text("SELECT COUNT(*) FROM effects")).scalar_one() == 0


def _restore_claim_in_spawned_worker(reference, output):
    assert guard.capture_worker_claim() is None
    with guard.restore_worker_claim(reference):
        output.send(guard.capture_worker_claim())
    assert guard.capture_worker_claim() is None
    output.close()


@pytest.mark.parametrize("separate", [False, True])
def test_reference_roundtrip_and_nested_restoration(claim_db, separate):
    repository, execution, mod = claim_db
    factory = sessionmaker(bind=mod) if separate else repository._session_factory
    assert guard.capture_worker_claim() is None
    with guard.worker_claim_scope(repository, execution, "owner"):
        context = multiprocessing.get_context("spawn")
        received, sending = context.Pipe(duplex=False)
        worker = context.Process(
            target=_restore_claim_in_spawned_worker,
            args=(guard.capture_worker_claim(), sending),
        )
        worker.start()
        sending.close()
        try:
            assert received.poll(30), "spawned claim roundtrip timed out"
            reference = received.recv()
            worker.join(30)
            assert worker.exitcode == 0
        finally:
            if worker.is_alive():
                worker.terminate()
                worker.join(10)
            received.close()
        execution.run_id = "caller-mutated"
        assert reference == guard.capture_worker_claim() == ("run", "owner", 1)
        with guard.restore_worker_claim(None):
            assert guard.capture_worker_claim() == reference
        with (
            pytest.raises(RuntimeError),
            guard.restore_worker_claim(("inner", "other", 2)),
        ):
            assert guard.capture_worker_claim() == ("inner", "other", 2)
            raise RuntimeError("unwind nested scope")
        assert guard.capture_worker_claim() == reference
    assert guard.capture_worker_claim() is None
    with (
        guard.restore_worker_claim(reference),
        factory.begin() as business,
    ):
        with guard.worker_write_guard(business):
            business.execute(text("INSERT INTO effects VALUES (1)"))
    assert guard.capture_worker_claim() is None
    with factory() as db:
        assert db.execute(text("SELECT COUNT(*) FROM effects")).scalar_one() == 1
    if separate:
        with repository.transaction(read_only=True) as db:
            assert db.execute(text("SELECT COUNT(*) FROM effects")).scalar_one() == 0


def test_claimed_repository_snapshots_execution(claim_db):
    repository, execution, _ = claim_db
    bound = ClaimedRunRepository(repository, execution, "owner")
    execution.execution_count = 2
    execution.run_id = "other"
    assert bound._execution.execution_count == 1 and bound._execution.run_id == "run"
    with pytest.raises(WorkerLeaseLost, match="another run"):
        bound.save(execution)
