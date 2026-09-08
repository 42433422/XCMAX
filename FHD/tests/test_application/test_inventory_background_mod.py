"""Actual registered inventory writes across host and two isolated Mod databases."""

import multiprocessing
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
    step = AgentStep(node_id="stock", tool_id="inventory", action="stock_in",
                     params={"model_number": "A100", "warehouse_name": "same warehouse", "quantity": 50})
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


@pytest.mark.parametrize("worker_kind", ["thread", "process"])
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
        db.add(UserSession(session_id="private-session", user_id=1,
                           expires_at=utc_now_naive() + timedelta(hours=1),
                           entitled_mod_ids_json='["private-a"]'))
    binding = bind_agent_mod_scope(session_id="private-session", user_id="1", mod_id="private-a")

    def execute():
        if worker_kind == "thread":
            with ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(_stock_in, binding).result(timeout=20)
        ctx = multiprocessing.get_context("spawn")
        results = ctx.Queue()
        child = ctx.Process(target=_child_stock_in, args=(binding, results))
        try:
            child.start()
            result = results.get(timeout=25)
            child.join(timeout=10)
            assert child.exitcode == 0
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
            db.query(UserSession).filter_by(session_id="private-session").one().entitled_mod_ids_json = "[]"
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
