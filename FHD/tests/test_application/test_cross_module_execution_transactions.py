"""Real SQLite and PostgreSQL transactions for claimed cross-module execution.

PostgreSQL runs only when XCAGI_TEST_AGENT_POSTGRES_URL is set. CI's Agent
PostgreSQL transactions job sets that URL. A missing URL skips the PostgreSQL
parameter; it does not replace these cases with an in-memory database.
"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine

from app.db.models.task_lifecycle import TaskLifecycleIdempotency, TaskLifecycleRecord
from tests.test_application.test_core_execution_reliability import (
    _client,
    _models,
    _post_task,
    _product_models,
)


@pytest.fixture(autouse=True)
def _reset_agent_repositories():
    from app.application.agent_orchestrator.run_repository import (
        set_agent_run_repository_for_tests,
    )
    from app.application.agent_orchestrator.task_dispatcher import (
        set_agent_task_dispatcher_for_tests,
    )
    from app.application.agent_orchestrator.task_execution_repository import (
        set_task_execution_repository_for_tests,
    )

    yield
    set_agent_run_repository_for_tests(None)
    set_task_execution_repository_for_tests(None)
    set_agent_task_dispatcher_for_tests(None)


def _dialects():
    cases = [pytest.param("sqlite", id="sqlite")]
    if os.environ.get("XCAGI_TEST_AGENT_POSTGRES_URL", "").strip():
        cases.append(pytest.param("postgresql", id="postgresql"))
    else:
        cases.append(
            pytest.param(
                "postgresql",
                marks=pytest.mark.skip(reason="XCAGI_TEST_AGENT_POSTGRES_URL is absent"),
                id="postgresql",
            )
        )
    return cases


@contextmanager
def _execution_database(tmp_path, monkeypatch, dialect: str):
    admin = None
    schema = ""
    engine = None
    env = None
    if dialect == "postgresql":
        url = os.environ["XCAGI_TEST_AGENT_POSTGRES_URL"]
        schema = "agent_xmod_" + uuid.uuid4().hex
        admin = create_engine(url)
        with admin.begin() as db:
            db.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        engine = create_engine(
            url,
            connect_args={
                "options": (
                    f"-csearch_path={schema} -clock_timeout=3000 -cstatement_timeout=60000"
                ),
            },
        )
    try:
        env = _client(tmp_path, monkeypatch, engine=engine)
        yield env
    finally:
        if env is not None:
            env["engine"].dispose()
        elif engine is not None:
            engine.dispose()
        if admin is not None:
            with admin.begin() as db:
                db.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
            admin.dispose()


def _queue_for_execution(env, created: dict):
    run = env["runs"].get(created["data"]["run_id"])
    assert run is not None
    run.metadata["cross_module_dispatch"] = "approved"
    run.status = "queued"
    env["runs"].save(run)
    released = env["queue"].enqueue(run, requested_by="agent-task-queue", priority=1)
    assert released is not None and released.state == "queued"
    stored = env["runs"].get(run.run_id)
    assert stored is not None
    return stored


def _lifecycle_counts(env) -> tuple[int, int]:
    session = env["factory"]()
    try:
        return (
            session.query(TaskLifecycleRecord).count(),
            session.query(TaskLifecycleIdempotency).count(),
        )
    finally:
        session.close()


def _business_lifecycle(env) -> tuple[list[str], int]:
    """Import and HTTP-response rows only. The queue log is a separate module."""
    session = env["factory"]()
    try:
        modules = sorted(
            row.module
            for row in session.query(TaskLifecycleRecord).all()
            if str(row.module).startswith("cross_module_")
        )
        return modules, session.query(TaskLifecycleIdempotency).count()
    finally:
        session.close()


@pytest.mark.parametrize("dialect", _dialects())
def test_drive_parks_when_dispatcher_already_owns_the_queue(tmp_path, monkeypatch, dialect):
    from app.application.agent_orchestrator.cross_module_execution import (
        drive_cross_module_execution,
    )
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.task_dispatcher import (
        AgentTaskDispatcher,
        set_agent_task_dispatcher_for_tests,
    )

    with _execution_database(tmp_path, monkeypatch, dialect) as env:
        created = _post_task(env, "task-exec-park", _models("PARK"))
        run = _queue_for_execution(env, created)
        claimed = env["queue"].claim("worker-a", lease_seconds=60, run_id=run.run_id)
        assert claimed is not None and claimed.state == "running"
        assert claimed.lease_owner == "worker-a"
        dispatcher = AgentTaskDispatcher(
            execution_repository=env["queue"],
            run_repository=env["runs"],
            poll_seconds=30,
            max_workers=1,
        )
        set_agent_task_dispatcher_for_tests(dispatcher)
        dispatcher.start()
        try:
            assert dispatcher.snapshot()["running"] is True
            receipt = drive_cross_module_execution(
                AgentOrchestrator(),
                run,
                env["queue"],
                str(run.metadata["approval_request_id"]),
            )
        finally:
            dispatcher.stop(timeout=2)
        assert receipt["success"] is False
        assert receipt["execution_accepted"] is True
        assert receipt["queue_state"] == "running"
        parked = env["queue"].get(run.run_id)
        assert parked is not None
        assert parked.state == "running"
        assert parked.lease_owner == "worker-a"
        assert parked.execution_count == 1
        assert _product_models(env) == []
        assert _business_lifecycle(env) == ([], 0)


@pytest.mark.parametrize("dialect", _dialects())
def test_rejected_approval_finishes_the_claim_without_import(tmp_path, monkeypatch, dialect):
    from app.application.agent_orchestrator.cross_module_execution import (
        execute_claimed_cross_module,
    )
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator

    with _execution_database(tmp_path, monkeypatch, dialect) as env:
        created = _post_task(env, "task-exec-reject", _models("REJX"))
        run = _queue_for_execution(env, created)
        claimed = env["queue"].claim("worker-reject", lease_seconds=60, run_id=run.run_id)
        assert claimed is not None
        run.status = "rejected"
        run.error = "不得写入"
        env["runs"].save(run)
        receipt = execute_claimed_cross_module(
            AgentOrchestrator(),
            env["runs"].get(run.run_id),
            owner="worker-reject",
            queue=env["queue"],
            request_id=str(run.metadata["approval_request_id"]),
            finish=True,
        )
        assert receipt["success"] is False
        assert receipt["loaded_from_storage"] is True
        finished = env["queue"].get(run.run_id)
        assert finished is not None
        assert finished.state == "failed"
        assert finished.last_error_code == "approval_rejected"
        assert finished.execution_count == 1
        assert env["runs"].get(run.run_id).status == "rejected"
        assert _product_models(env) == []
        assert _business_lifecycle(env) == ([], 0)


@pytest.mark.parametrize("dialect", _dialects())
def test_http_result_persists_and_reload_ignores_a_later_body(tmp_path, monkeypatch, dialect):
    from app.application.agent_orchestrator.cross_module_execution import (
        _persist_http_result,
        load_cross_module_http_result,
    )

    with _execution_database(tmp_path, monkeypatch, dialect) as env:
        checkpoint = {
            "tenant_id": "1",
            "user_id": "7",
            "run_id": "run-exec-body",
            "task_id": "task-exec-body",
            "idempotency_key": "task-exec-body-key",
            "approval_fingerprint": "b" * 64,
        }
        body = {
            "success": True,
            "idempotency_key": checkpoint["idempotency_key"],
            "request_digest": checkpoint["approval_fingerprint"],
            "execution_status": "committed",
            "data": {"run_id": "run-exec-body", "stored_count": 2, "replayed": False},
        }
        with env["factory"].begin() as db:
            _persist_http_result(
                db,
                checkpoint,
                http_status=200,
                execution_status="committed",
                body=body,
                overwrite=False,
            )
        stored = load_cross_module_http_result("1", checkpoint["idempotency_key"])
        assert stored is not None
        assert stored["http_status"] == 200
        assert stored["execution_status"] == "committed"
        assert stored["request_digest"] == checkpoint["approval_fingerprint"]
        assert stored["body"]["data"]["stored_count"] == 2
        replaced = {
            **body,
            "data": {"run_id": "run-exec-body", "stored_count": 9, "replayed": True},
        }
        with env["factory"].begin() as db:
            _persist_http_result(
                db,
                checkpoint,
                http_status=500,
                execution_status="failed",
                body=replaced,
                overwrite=False,
            )
        again = load_cross_module_http_result("1", checkpoint["idempotency_key"])
        assert again is not None
        assert again["http_status"] == 200
        assert again["body"]["data"]["stored_count"] == 2
        assert again["body"]["data"]["replayed"] is False
        records, keys = _lifecycle_counts(env)
        assert records == 1
        assert keys == 0


@pytest.mark.parametrize("dialect", _dialects())
def test_rollback_before_commit_leaves_no_rows_and_recovery_inserts_once(
    tmp_path, monkeypatch, dialect
):
    from app.application.agent_orchestrator.cross_module_execution import (
        InjectedTransactionFault,
        execute_claimed_cross_module,
    )
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator

    with _execution_database(tmp_path, monkeypatch, dialect) as env:
        created = _post_task(env, "task-exec-rollback", _models("ROLL"))
        run = _queue_for_execution(env, created)
        claimed = env["queue"].claim("worker-a", lease_seconds=60, run_id=run.run_id)
        assert claimed is not None and claimed.execution_count == 1
        monkeypatch.setenv("XCAGI_TX_FAULT", "rollback_before_commit")
        with pytest.raises(InjectedTransactionFault):
            execute_claimed_cross_module(
                AgentOrchestrator(),
                run,
                owner="worker-a",
                queue=env["queue"],
                request_id=str(run.metadata["approval_request_id"]),
                finish=True,
            )
        assert _product_models(env) == []
        assert _business_lifecycle(env) == ([], 0)
        assert env["queue"].get(run.run_id).state == "running"
        monkeypatch.delenv("XCAGI_TX_FAULT")
        recovered = env["queue"].claim(
            "worker-b",
            lease_seconds=60,
            run_id=run.run_id,
            now="2099-01-01T00:00:00+00:00",
        )
        assert recovered is not None
        assert recovered.lease_owner == "worker-b"
        assert recovered.recovery_count == 1
        receipt = execute_claimed_cross_module(
            AgentOrchestrator(),
            env["runs"].get(run.run_id),
            owner="worker-b",
            queue=env["queue"],
            request_id=str(run.metadata["approval_request_id"]),
            finish=True,
        )
        assert receipt["success"] is True
        assert receipt["replayed"] is False
        assert receipt["stored_count"] == 2
        assert _product_models(env) == ["ROLL-1", "ROLL-2"]
        assert env["queue"].get(run.run_id).state == "succeeded"
        assert env["queue"].get(run.run_id).execution_count == 2
        assert _business_lifecycle(env) == (
            ["cross_module_http_response", "cross_module_import"],
            1,
        )


@pytest.mark.parametrize("dialect", _dialects())
def test_crash_after_commit_replays_the_stored_response(tmp_path, monkeypatch, dialect):
    from app.application.agent_orchestrator.cross_module_execution import (
        InjectedTransactionFault,
        execute_claimed_cross_module,
        load_cross_module_http_result,
    )
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator

    with _execution_database(tmp_path, monkeypatch, dialect) as env:
        created = _post_task(env, "task-exec-crash", _models("CRASH"))
        run = _queue_for_execution(env, created)
        claimed = env["queue"].claim("worker-a", lease_seconds=60, run_id=run.run_id)
        assert claimed is not None
        monkeypatch.setenv("XCAGI_TX_FAULT", "crash_after_commit")
        with pytest.raises(InjectedTransactionFault):
            execute_claimed_cross_module(
                AgentOrchestrator(),
                run,
                owner="worker-a",
                queue=env["queue"],
                request_id=str(run.metadata["approval_request_id"]),
                finish=True,
            )
        assert _product_models(env) == ["CRASH-1", "CRASH-2"]
        committed_records, committed_keys = _lifecycle_counts(env)
        assert committed_records >= 1
        assert committed_keys == 1
        checkpoint = run.metadata["runtime_context"]["cross_module_checkpoint"]
        stored = load_cross_module_http_result(
            checkpoint["tenant_id"], checkpoint["idempotency_key"]
        )
        assert stored is not None
        assert stored["http_status"] == 200
        assert stored["execution_status"] == "committed"
        assert stored["request_digest"] == checkpoint["approval_fingerprint"]
        assert stored["business_result_ref"]["task_id"] == "task-exec-crash"
        assert stored["body"]["data"]["stored_count"] == 2
        assert stored["body"]["data"]["replayed"] is False
        monkeypatch.delenv("XCAGI_TX_FAULT")
        recovered = env["queue"].claim(
            "worker-b",
            lease_seconds=60,
            run_id=run.run_id,
            now="2099-01-01T00:00:00+00:00",
        )
        assert recovered is not None and recovered.recovery_count == 1
        receipt = execute_claimed_cross_module(
            AgentOrchestrator(),
            env["runs"].get(run.run_id),
            owner="worker-b",
            queue=env["queue"],
            request_id=str(run.metadata["approval_request_id"]),
            finish=True,
        )
        assert receipt["success"] is True
        assert receipt["replayed"] is True
        assert receipt["stored_count"] == 2
        assert _product_models(env) == ["CRASH-1", "CRASH-2"]
        replayed = load_cross_module_http_result(
            checkpoint["tenant_id"], checkpoint["idempotency_key"]
        )
        assert replayed is not None
        assert replayed["body"]["data"]["replayed"] is True
        assert replayed["body"]["data"]["stored_count"] == 2
        assert _lifecycle_counts(env) == (committed_records, committed_keys)
