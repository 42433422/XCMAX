"""Actual registered inventory writes across host and two isolated Mod databases."""

import multiprocessing
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy.orm import sessionmaker

import app.db as db_mod
from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.db.base import Base
from app.db.models import InventoryLedger, InventoryTransaction, Product, Warehouse
from app.db.models.user import Session as UserSession
from app.db.models.user import User
from app.infrastructure.auth.agent_mod_scope import bind_agent_mod_scope
from app.infrastructure.tenant_scope import current_tenant_id, tenant_scope
from app.request_active_mod_ctx import get_request_active_mod_id
from app.utils.time import utc_now_naive


def _stock_in(binding):
    assert current_tenant_id() is None
    assert get_request_active_mod_id() == ""
    step = AgentStep(
        node_id="stock",
        tool_id="inventory",
        action="stock_in",
        params={"model_number": "A100", "warehouse_name": "same warehouse", "quantity": 50},
    )
    result = AgentToolExecutor().execute(
        step, runtime_context={"tenant_id": "1", "_mod_authorization": binding}
    )
    assert current_tenant_id() is None
    assert get_request_active_mod_id() == ""
    return result


def _child_stock_in(binding, results):
    # Use the same configured file databases, without the parent pytest DB manager.
    db_mod._get_test_db_manager = lambda: None
    results.put(_stock_in(binding))


def _child_dispatch(run_id, results):
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher
    from app.application.agent_orchestrator.task_execution_sql_repository import (
        SQLAlchemyTaskExecutionRepository,
    )

    db_mod._get_test_db_manager = lambda: None
    runs = SQLAlchemyAgentRunRepository()
    queue = SQLAlchemyTaskExecutionRepository()
    dispatcher = AgentTaskDispatcher(run_repository=runs, execution_repository=queue, max_workers=1)
    dispatcher.start()
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            execution = queue.get(run_id)
            if execution.state in {"completed", "failed", "blocked"}:
                run = runs.get(run_id)
                assert run is not None
                assert run.status == execution.state
                output = run.tool_calls[-1].output if run.tool_calls else {}
                results.put(
                    {
                        "success": run.status == "completed",
                        "state": run.status,
                        "recovery_count": execution.recovery_count,
                        "error_code": (output or {}).get("error_code", ""),
                    }
                )
                return
            time.sleep(0.03)
        raise AssertionError("dispatcher did not persist terminal state")
    finally:
        dispatcher.stop(timeout=5)


def _child_claim_and_exit(run_id):
    from app.application.agent_orchestrator.task_execution_sql_repository import (
        SQLAlchemyTaskExecutionRepository,
    )

    db_mod._get_test_db_manager = lambda: None
    claimed = SQLAlchemyTaskExecutionRepository().claim("departed-worker", lease_seconds=60)
    assert claimed is not None and claimed.run_id == run_id
    # Exit without finishing ownership or starting the business step.


@pytest.mark.parametrize("worker_kind", ["thread", "process", "dispatcher", "dispatcher_recovery"])
def test_real_inventory_writes_only_authorized_mod_and_rechecks_revocation(
    tmp_path, monkeypatch, worker_kind
):
    urls = {name: f"sqlite:///{tmp_path / (name + '.db')}" for name in ("host", "a", "b")}
    monkeypatch.setenv("DATABASE_URL", urls["host"])
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    monkeypatch.setenv("XCAGI_MOD_DATABASE_URL_PRIVATE_A", urls["a"])
    monkeypatch.setenv("XCAGI_MOD_DATABASE_URL_PRIVATE_B", urls["b"])
    monkeypatch.setattr(db_mod, "_get_test_db_manager", lambda: None)
    monkeypatch.setattr("app.http.request_context.get_current_http_request", lambda: None)
    engines = {name: db_mod._get_engine_for_url(url) for name, url in urls.items()}
    factories = {name: sessionmaker(bind=engine) for name, engine in engines.items()}
    for name, engine in engines.items():
        Base.metadata.create_all(engine)
        with tenant_scope(1), factories[name].begin() as db:
            db.add(Product(name="same product", model_number="A100"))
            db.add(Warehouse(code="MAIN", name="same warehouse", status="active"))
    with factories["host"].begin() as db:
        db.add(User(id=1, username="owner", password="unused", is_active=True))
        db.flush()
        db.add(
            UserSession(
                session_id="private-session",
                user_id=1,
                expires_at=utc_now_naive() + timedelta(hours=1),
                entitled_mod_ids_json='["private-a"]',
            )
        )
    binding = bind_agent_mod_scope(session_id="private-session", user_id="1", mod_id="private-a")

    def execute():
        if worker_kind == "thread":
            with ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(_stock_in, binding).result(timeout=20)
        ctx = multiprocessing.get_context("spawn")
        results = ctx.Queue()
        if worker_kind.startswith("dispatcher"):
            from app.application.agent_orchestrator.run_models import AgentRun
            from app.application.agent_orchestrator.run_sql_repository import (
                SQLAlchemyAgentRunRepository,
            )
            from app.application.agent_orchestrator.task_background import apply_approved_step
            from app.application.agent_orchestrator.task_execution_sql_repository import (
                SQLAlchemyTaskExecutionRepository,
            )

            run = AgentRun(user_id="1", message="approved inbound", status="waiting_user")
            step = AgentStep(
                node_id="stock",
                tool_id="inventory",
                action="stock_in",
                status="waiting_user",
                risk="high",
                idempotent=False,
                params={"model_number": "A100", "warehouse_name": "same warehouse", "quantity": 50},
            )
            run.steps = [step]
            run.metadata["runtime_context"] = {"tenant_id": "1", "_mod_authorization": binding}
            apply_approved_step(run, step, approved_by="1")
            SQLAlchemyAgentRunRepository().save(run)
            queue = SQLAlchemyTaskExecutionRepository()
            queue.enqueue(run)
            if worker_kind == "dispatcher_recovery":
                from app.db.models.agent import AgentTaskExecutionRecord

                departed = ctx.Process(target=_child_claim_and_exit, args=(run.run_id,))
                departed.start()
                departed.join(timeout=15)
                if departed.is_alive():
                    departed.terminate()
                    departed.join(timeout=5)
                    pytest.fail("old claimant did not exit")
                assert departed.exitcode == 0
                assert queue.get(run.run_id).lease_owner == "departed-worker"
                # Expired ownership with no business step started is safe to resume.
                with factories["host"].begin() as db:
                    db.query(AgentTaskExecutionRecord).filter_by(run_id=run.run_id).update(
                        {"lease_expires_at": "2000-01-01T00:00:00+00:00"}
                    )
            child = ctx.Process(target=_child_dispatch, args=(run.run_id, results))
        else:
            child = ctx.Process(target=_child_stock_in, args=(binding, results))
        try:
            child.start()
            result = results.get(timeout=25)
            child.join(timeout=10)
            assert child.exitcode == 0
            if worker_kind.startswith("dispatcher"):
                assert result["recovery_count"] == (
                    1 if worker_kind == "dispatcher_recovery" else 0
                )
            return result
        finally:
            if child.is_alive():
                child.terminate()
                child.join(timeout=5)
            results.close()

    try:
        response = execute()
        assert response["success"], response
        with factories["host"].begin() as db:
            db.query(UserSession).filter_by(
                session_id="private-session"
            ).one().entitled_mod_ids_json = "[]"
        denied = execute()
        assert denied["error_code"] == "mod_authorization_invalid"
        for name, factory in factories.items():
            with tenant_scope(1), factory() as db:
                movements = db.query(InventoryTransaction).all()
                ledgers = db.query(InventoryLedger).all()
                assert len(movements) == len(ledgers) == (1 if name == "a" else 0)
                if name == "a":
                    assert float(movements[0].quantity) == float(ledgers[0].quantity) == 50
    finally:
        for engine in engines.values():
            engine.dispose()
