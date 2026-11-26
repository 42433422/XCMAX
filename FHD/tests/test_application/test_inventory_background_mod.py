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
from app.db.db_base import Base
from app.db.models import InventoryLedger, InventoryTransaction, Product, Warehouse
from app.db.models.permission import Permission, Role
from app.db.models.user import Session as UserSession
from app.db.models.user import User
from app.infrastructure.auth.agent_mod_scope import (
    bind_agent_actor_scope,
    bind_agent_mod_scope,
)
from app.infrastructure.tenant_scope import current_tenant_id, tenant_scope
from app.request_active_mod_ctx import get_request_active_mod_id
from app.utils.time import utc_now_naive


def _stock_in(context):
    assert current_tenant_id() is None
    assert get_request_active_mod_id() == ""
    step = AgentStep(
        node_id="stock",
        tool_id="inventory",
        action="stock_in",
        params={
            "model_number": "A100",
            "warehouse_name": "same warehouse",
            "quantity": 50,
        },
    )
    result = AgentToolExecutor().execute(step, runtime_context=context)
    assert current_tenant_id() is None
    assert get_request_active_mod_id() == ""
    return result


def _child_stock_in(context, results):
    # Use the same configured file databases, without the parent pytest DB manager.
    db_mod._get_test_db_manager = lambda: None
    results.put(_stock_in(context))


def _child_dispatch(run_id, results):
    from app.application.agent_orchestrator.run_sql_repository import (
        SQLAlchemyAgentRunRepository,
    )
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
            if execution.state in {
                "succeeded",
                "failed",
                "blocked",
                "rejected",
                "cancelled",
                "timed_out",
            }:
                run = runs.get(run_id)
                assert run is not None
                expected_run_state = (
                    "completed" if execution.state == "succeeded" else execution.state
                )
                assert run.status == expected_run_state
                output = run.tool_calls[-1].output if run.tool_calls else {}
                denial = next(
                    (
                        event.data
                        for event in reversed(run.events)
                        if event.event_type == "workflow.plan_audit_rejected"
                    ),
                    {},
                )
                if execution.state == "blocked" and not run.tool_calls:
                    assert denial.get("execution_started") is False
                results.put(
                    {
                        "success": execution.state == "succeeded",
                        "state": execution.state,
                        "recovery_count": execution.recovery_count,
                        "error_code": (output or {}).get("error_code")
                        or denial.get("error_code", ""),
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


def _inventory_scope(tmp_path, monkeypatch):
    urls = {name: f"sqlite:///{tmp_path / (name + '.db')}" for name in ("host", "a", "b")}
    monkeypatch.setenv("DATABASE_URL", urls["host"])
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "stock-claims.sqlite"))
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
        db.add(
            Role(
                name="inventory-owner",
                permissions=[
                    Permission(code=code, name=code)
                    for code in (
                        "tool.inventory.stock_in",
                        "tool.inventory.stock_out",
                        "tool.inventory.query_transactions",
                        "approval.workflow",
                    )
                ],
            )
        )
        db.add(
            User(
                id=1,
                username="owner",
                password="unused",
                is_active=True,
                tenant_id=1,
                role="inventory-owner",
                tier="enterprise",
            )
        )
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

    context = {
        "user_id": "1",
        "actor_id": "1",
        "tenant_id": "1",
        "mod_id": "private-a",
        "_mod_authorization": binding,
        "_actor_authorization": bind_agent_actor_scope(
            session_id="private-session",
            user_id="1",
            execution_tenant_id="1",
            mod_id="private-a",
        ),
    }
    return engines, factories, context


@pytest.mark.parametrize("worker_kind", ["thread", "process", "dispatcher", "dispatcher_recovery"])
def test_real_inventory_writes_only_authorized_mod_and_rechecks_revocation(
    tmp_path, monkeypatch, worker_kind
):
    engines, factories, context = _inventory_scope(tmp_path, monkeypatch)

    def execute():
        if worker_kind == "thread":
            with ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(_stock_in, context).result(timeout=20)
        ctx = multiprocessing.get_context("spawn")
        results = ctx.Queue()
        if worker_kind.startswith("dispatcher"):
            from app.application.agent_orchestrator.run_models import AgentRun
            from app.application.agent_orchestrator.run_sql_repository import (
                SQLAlchemyAgentRunRepository,
            )
            from app.application.agent_orchestrator.task_background import (
                apply_approved_step,
            )
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
                params={
                    "model_number": "A100",
                    "warehouse_name": "same warehouse",
                    "quantity": 50,
                },
            )
            from app.application.workflow.workflow_types import (
                PlanGraph,
                WorkflowNode,
                plan_to_dict,
            )

            run.steps = [step]
            run.metadata["plan"] = plan_to_dict(
                PlanGraph(
                    plan_id=run.run_id,
                    intent="approved inventory inbound",
                    nodes=[
                        WorkflowNode(
                            node_id=step.node_id,
                            tool_id=step.tool_id,
                            action=step.action,
                            params=step.params,
                            risk=step.risk,
                            idempotent=step.idempotent,
                        )
                    ],
                    metadata={"approval_required_node_ids": [step.node_id]},
                )
            )
            run.metadata["runtime_context"] = dict(context)
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
            child = ctx.Process(target=_child_stock_in, args=(context, results))
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
        assert denied["success"] is False
        assert denied["error_code"] == "tool_identity_required"
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


@pytest.fixture(params=["stock_in", "stock_out"])
def verified_inventory(tmp_path, monkeypatch, request):
    from types import SimpleNamespace

    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import (
        InMemoryAgentRunRepository,
    )
    from app.application.inventory_app_service import InventoryAppService
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    engines, factories, context = _inventory_scope(tmp_path, monkeypatch)
    if request.param == "stock_out":
        with tenant_scope(1), factories["a"].begin() as db:
            db.add(
                InventoryLedger(
                    product_id=1,
                    warehouse_id=1,
                    quantity=10,
                    available_quantity=10,
                    reserved_quantity=0,
                )
            )
    params = {
        "product_id": 1,
        "warehouse_id": 1,
        "quantity": 2.5,
        "reference_type": "verification-test",
        "reference_id": 9,
        "operator": "owner",
        "remark": "original approved movement",
    }
    if request.param == "stock_in":
        params["unit_price"] = 4
    orchestrator = AgentOrchestrator(
        repository=InMemoryAgentRunRepository(),
        tool_executor=SimpleNamespace(execute=AgentToolExecutor().execute),
    )
    try:
        run = orchestrator.start_run_from_plan(
            user_id="1",
            message="Original inventory movement",
            runtime_context=context,
            plan=PlanGraph(
                plan_id="inventory-proof",
                intent="inventory",
                nodes=[WorkflowNode("stock", "inventory", request.param, params=params)],
            ),
        )
        assert run.status == "waiting_user" and not run.tool_calls
        run = orchestrator.continue_run(run.run_id, approved_by="1")
        assert run.status == "completed", run.to_dict()
        for action in ("inventory_in", "inventory_out"):
            monkeypatch.setattr(
                InventoryAppService,
                action,
                lambda *_a, **_k: pytest.fail("Readback must never post stock"),
            )
        yield engines, factories, run
    finally:
        for engine in engines.values():
            engine.dispose()


@pytest.mark.parametrize(
    "change",
    [
        None,
        "receipt",
        "fingerprint",
        "tenant",
        "quantity",
        "available",
        "movement",
        "movement_reference",
        "permission",
        "mod",
    ],
)
def test_inventory_readback_binds_original_receipt_and_live_mod_stock(verified_inventory, change):
    import copy
    import sqlite3

    from sqlalchemy import event

    from app.application.agent_orchestrator.result_verification import (
        verify_step_result,
    )
    from app.application.agent_orchestrator.task_background import (
        task_execution_context,
    )
    from app.application.agent_orchestrator.tool_permission import _idempotency_path

    engines, factories, run = verified_inventory
    step, call = run.steps[0], run.tool_calls[0]
    original = copy.deepcopy(call.output)
    if change in {"receipt", "fingerprint"}:
        with sqlite3.connect(_idempotency_path(create_parent=False)) as db:
            db.execute(
                "DELETE FROM tool_idempotency"
                if change == "receipt"
                else "UPDATE tool_idempotency SET fingerprint = 'different-call'"
            )
    elif change in {"permission", "mod"}:
        with factories["host"].begin() as db:
            if change == "mod":
                db.query(UserSession).one().entitled_mod_ids_json = "[]"
            else:
                role = db.query(Role).filter_by(name="inventory-owner").one()
                role.permissions = [
                    p for p in role.permissions if p.code != "tool.inventory.query_transactions"
                ]
    elif change is not None:
        with tenant_scope(1), factories["a"].begin() as db:
            ledger = db.query(InventoryLedger).one()
            if change == "tenant":
                ledger.tenant_id = 2
            elif change == "quantity":
                ledger.quantity = 99
            elif change == "available":
                ledger.available_quantity = 0
            elif change == "movement":
                db.delete(db.query(InventoryTransaction).one())
            elif change == "movement_reference":
                db.query(InventoryTransaction).one().reference_id = 10
    writes = []

    def observe(_connection, _cursor, statement, _params, _context, _many):
        if statement.split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    for engine in engines.values():
        event.listen(engine, "before_cursor_execute", observe)
    try:
        for _ in range(2):
            report = verify_step_result(
                run=run,
                step=step,
                call=call,
                context={
                    **run.metadata["runtime_context"],
                    "run_id": run.run_id,
                    "step_id": step.step_id,
                    **task_execution_context(run, step),
                },
            )
            assert report["accepted"] is (change is None), report
            assert report["code"] != "verification_binding_invalid"
            if change is None:
                assert report["checks"][0]["evidence"]["scope"] == "current_inventory_state"
        assert writes == [] and call.output == original and len(run.tool_calls) == 1
        with tenant_scope(1), factories["b"]() as db:
            assert db.query(InventoryLedger).count() == db.query(InventoryTransaction).count() == 0
    finally:
        for engine in engines.values():
            event.remove(engine, "before_cursor_execute", observe)


def test_inventory_claimed_verified_cannot_borrow_another_call_or_ledger(
    verified_inventory,
):
    import copy
    from types import SimpleNamespace

    from tests.test_application.test_verification_readback import invocation, verify

    _engines, _factories, run = verified_inventory
    actor = SimpleNamespace(user_id=run.user_id, context=run.metadata["runtime_context"])
    case = invocation(
        actor,
        tool="inventory",
        action=run.steps[0].action,
        params=copy.deepcopy(run.steps[0].params),
    )
    assert (
        verify(case, {**copy.deepcopy(run.tool_calls[0].output), "verified": True})["code"]
        == "result_receipt_unavailable"
    )
    case.run, case.step, case.call = run, run.steps[0], run.tool_calls[0]
    from app.application.agent_orchestrator.task_background import (
        task_execution_context,
    )

    case.context = {
        **actor.context,
        "run_id": run.run_id,
        "step_id": case.step.step_id,
        **task_execution_context(run, case.step),
    }
    for override in (
        {"verified": True},
        {"data": {**case.call.output["data"], "ledger_id": 999}},
    ):
        assert (
            verify(case, {**copy.deepcopy(case.call.output), **override})["code"]
            == "result_receipt_mismatch"
        )
