import multiprocessing

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.approval_consumption_repository import (
    SQLAlchemyApprovalConsumptionRepository,
)
from app.db.models.agent_approval import AgentApprovalConsumption


def _consume_in_process(url, ready, start, results):
    engine = create_engine(url)
    try:
        repository = SQLAlchemyApprovalConsumptionRepository(sessionmaker(bind=engine))
        ready.put(True)
        if not start.wait(15):
            raise RuntimeError("approval barrier timed out")
        results.put(repository.consume(jti="a" * 64, run_id="run", step_id="step"))
    finally:
        engine.dispose()


def test_approval_consumption_is_atomic_across_processes_and_restart(tmp_path):
    url = f"sqlite:///{tmp_path / 'approvals.db'}"
    engine = create_engine(url)
    AgentApprovalConsumption.__table__.create(engine)
    ctx = multiprocessing.get_context("spawn")
    ready, results = ctx.Queue(), ctx.Queue()
    start = ctx.Event()
    processes = [
        ctx.Process(target=_consume_in_process, args=(url, ready, start, results)) for _ in range(2)
    ]
    try:
        for process in processes:
            process.start()
        for _ in processes:
            assert ready.get(timeout=15)
        start.set()
        assert sorted(results.get(timeout=15) for _ in processes) == [False, True]
        for process in processes:
            process.join(timeout=15)
            assert process.exitcode == 0
        # A new connection/repository after both workers exit still rejects replay.
        repository = SQLAlchemyApprovalConsumptionRepository(sessionmaker(bind=engine))
        assert repository.consume(jti="a" * 64, run_id="run", step_id="step") is False
        with sessionmaker(bind=engine)() as db:
            assert db.query(AgentApprovalConsumption).count() == 1
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        ready.close()
        results.close()
        engine.dispose()


def test_missing_storage_never_reports_success(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'missing-schema.db'}")
    try:
        repository = SQLAlchemyApprovalConsumptionRepository(sessionmaker(bind=engine))
        with pytest.raises(OperationalError):
            repository.consume(jti="a" * 64, run_id="run", step_id="step")
    finally:
        engine.dispose()
