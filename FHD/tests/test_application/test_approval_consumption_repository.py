import importlib.util
import multiprocessing
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.approval_consumption_repository import (
    SQLAlchemyApprovalConsumptionRepository,
)
from app.db.models.agent_approval import AgentApprovalConsumption


def _approval_run():
    from app.application.agent_orchestrator.run_models import AgentRun, AgentStep

    return AgentRun(
        user_id="owner",
        message="create order",
        run_id="durable-run",
        status="waiting_user",
        steps=[
            AgentStep(
                node_id="node",
                tool_id="sales",
                action="create_order",
                step_id="durable-step",
                status="waiting_user",
                params={"quantity": 2},
            )
        ],
    )


def _consume_signed_in_process(url, token, ready, start, results):
    import app.db
    from app.application.agent_orchestrator.approval_grant import (
        ApprovalGrantError,
        consume_approval_grant,
    )

    engine = create_engine(url)
    app.db.SessionLocal = sessionmaker(bind=engine)
    try:
        ready.put(True)
        if not start.wait(15):
            raise RuntimeError("approval barrier timed out")
        try:
            consume_approval_grant(token, run=_approval_run(), principal_id="owner")
            results.put("consumed")
        except ApprovalGrantError as exc:
            results.put(str(exc))
    finally:
        engine.dispose()


def test_signed_grant_race_and_renewal_after_process_restart(tmp_path, monkeypatch):
    from app.application.agent_orchestrator.approval_grant import issue_approval_grant

    monkeypatch.setenv("SECRET_KEY", "isolated-approval-test-key-" * 3)
    url = f"sqlite:///{tmp_path / 'signed.db'}"
    engine = create_engine(url)
    AgentApprovalConsumption.__table__.create(engine)
    ctx = multiprocessing.get_context("spawn")
    ready, results, start = ctx.Queue(), ctx.Queue(), ctx.Event()
    token = issue_approval_grant(_approval_run(), principal_id="owner")["grant"]
    processes = [
        ctx.Process(target=_consume_signed_in_process, args=(url, token, ready, start, results))
        for _ in range(2)
    ]
    try:
        for process in processes:
            process.start()
        for _ in processes:
            assert ready.get(timeout=15)
        start.set()
        assert sorted(results.get(timeout=15) for _ in processes) == [
            "approval_grant 已使用",
            "consumed",
        ]
        for process in processes:
            process.join(timeout=15)
            assert process.exitcode == 0
        renewed = issue_approval_grant(_approval_run(), principal_id="owner", ttl_seconds=900)[
            "grant"
        ]
        assert renewed != token
        restarted = ctx.Process(
            target=_consume_signed_in_process, args=(url, renewed, ready, start, results)
        )
        processes.append(restarted)
        restarted.start()
        assert ready.get(timeout=15)
        assert results.get(timeout=15) == "approval_grant 已使用"
        restarted.join(timeout=15)
        assert restarted.exitcode == 0
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


def test_approval_migration_upgrade_and_downgrade(tmp_path, monkeypatch):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    path = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/2026_09_08_agent_approval_consumption.py"
    )
    spec = importlib.util.spec_from_file_location("approval_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    try:
        with engine.begin() as connection:
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            assert inspect(connection).get_pk_constraint("agent_approval_consumptions")[
                "constrained_columns"
            ] == ["jti"]
        repository = SQLAlchemyApprovalConsumptionRepository(sessionmaker(bind=engine))
        assert repository.consume(jti="migration", run_id="run", step_id="step")
        assert not repository.consume(jti="migration", run_id="run", step_id="step")
        with engine.begin() as connection:
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.downgrade()
            assert "agent_approval_consumptions" not in inspect(connection).get_table_names()
    finally:
        engine.dispose()


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
