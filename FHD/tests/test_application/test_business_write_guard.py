import multiprocessing
import os
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.business_write_guard import worker_claim_scope
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.worker_repository import WorkerLeaseLost
from app.db.base import Base
from app.db.models import InventoryLedger, InventoryTransaction, Product, Warehouse
from app.db.models.agent import AgentTaskExecutionRecord
from app.services.inventory_service import InventoryService


def _inbound_paused_before_commit(
    owner_url, business_url, ready, release, result, crash_after_commit=False
):
    import app.services.inventory_service as facade
    from app.infrastructure.tenant_scope import tenant_scope

    owner_engine = create_engine(owner_url)
    business_engine = owner_engine if owner_url == business_url else create_engine(business_url)
    owner_factory = sessionmaker(bind=owner_engine)
    business_factory = sessionmaker(bind=business_engine)
    runs = SQLAlchemyAgentRunRepository(session_factory=owner_factory, auto_create=False)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=owner_factory, auto_create=False)
    execution = queue.claim("writer", lease_seconds=60)

    @contextmanager
    def business_session():
        with business_factory() as db:

            def pause_before_commit(session):
                session.flush()
                assert session.query(InventoryTransaction).count() == 1
                assert float(session.query(InventoryLedger).one().quantity) == 50
                ready.put(execution.run_id)
                if not release.wait(20):
                    raise RuntimeError("commit barrier timed out")

            event.listen(db, "before_commit", pause_before_commit, once=True)
            yield db
            db.commit()

    facade.get_db = business_session
    try:
        with tenant_scope(1), worker_claim_scope(runs, execution, "writer"):
            response = InventoryService().inventory_in(
                product_id=None,
                warehouse_id=None,
                model_number="A100",
                warehouse_name="主仓库",
                quantity=50,
            )
        if crash_after_commit:
            assert response["success"], response
            os._exit(73)
        result.put(response)
    finally:
        business_engine.dispose()
        owner_engine.dispose()


@pytest.mark.parametrize("separate_mod_database", [False, True])
@pytest.mark.parametrize("crash_after_commit", [False, True])
def test_takeover_cannot_cross_inventory_commit(
    tmp_path, separate_mod_database, crash_after_commit
):
    owner_url = f"sqlite:///{tmp_path / 'owner.db'}"
    business_url = f"sqlite:///{tmp_path / 'mod.db'}" if separate_mod_database else owner_url
    owner_engine = create_engine(owner_url, connect_args={"timeout": 0.1})
    business_engine = create_engine(business_url)
    owner_factory = sessionmaker(bind=owner_engine)
    business_factory = sessionmaker(bind=business_engine)
    Base.metadata.create_all(business_engine)
    runs = SQLAlchemyAgentRunRepository(session_factory=owner_factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=owner_factory)
    run = AgentRun(user_id="owner", message="inbound", status="queued")
    from app.application.agent_orchestrator.run_models import AgentStep

    run.status = "running"
    run.steps = [
        AgentStep(
            node_id="inbound",
            tool_id="inventory",
            action="stock_in",
            status="running",
            idempotent=True,
        )
    ]
    runs.save(run)
    queue.enqueue(run)
    with business_factory.begin() as db:
        db.add_all(
            [
                Product(name="产品", model_number="A100"),
                Warehouse(code="MAIN", name="主仓库", status="active"),
            ]
        )
    ctx = multiprocessing.get_context("spawn")
    ready, result, release = ctx.Queue(), ctx.Queue(), ctx.Event()
    process = ctx.Process(
        target=_inbound_paused_before_commit,
        args=(owner_url, business_url, ready, release, result, crash_after_commit),
    )
    # Advance the claimant clock beyond expiry without a timing-dependent sleep.
    after_expiry = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    try:
        process.start()
        assert ready.get(timeout=20) == run.run_id
        with pytest.raises(OperationalError, match="locked"):
            queue.claim("replacement", lease_seconds=60, now=after_expiry)
        assert queue.get(run.run_id).lease_owner == "writer"
        with business_factory() as db:
            assert db.query(InventoryTransaction).count() == 0
        release.set()
        if not crash_after_commit:
            response = result.get(timeout=20)
            assert response["success"], response
        process.join(timeout=20)
        assert process.exitcode == (73 if crash_after_commit else 0)
        replacement = queue.claim("replacement", lease_seconds=60, now=after_expiry)
        assert replacement is not None and replacement.recovery_count == 1
        if crash_after_commit:
            from unittest.mock import Mock

            from app.application.agent_orchestrator import AgentOrchestrator
            from app.application.agent_orchestrator.worker_repository import ClaimedRunRepository

            executor = Mock()
            recovered = AgentOrchestrator(
                repository=ClaimedRunRepository(runs, replacement, "replacement"),
                tool_executor=executor,
            ).execute_dispatched_run(run.run_id, recovered=True)
            assert recovered.status == "blocked"
            assert recovered.metadata["recovery"]["state"] == "manual_reconciliation_required"
            executor.execute.assert_not_called()

        with business_factory() as db:
            assert db.query(InventoryTransaction).count() == 1
            assert float(db.query(InventoryLedger).one().quantity) == 50
    finally:
        release.set()
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        ready.close()
        result.close()
        business_engine.dispose()
        owner_engine.dispose()


@pytest.mark.parametrize("separate_mod_database", [False, True])
@pytest.mark.parametrize("expired", [False, True])
@pytest.mark.parametrize("operation", ["in", "out", "transfer"])
def test_inventory_commit_requires_live_claim_without_rerouting_mod_data(
    tmp_path, monkeypatch, separate_mod_database, expired, operation
):
    ownership_engine = create_engine(f"sqlite:///{tmp_path / 'queue.db'}")
    business_engine = (
        create_engine(f"sqlite:///{tmp_path / 'mod.db'}")
        if separate_mod_database
        else ownership_engine
    )
    owner_factory = sessionmaker(bind=ownership_engine)
    business_factory = sessionmaker(bind=business_engine)
    Base.metadata.create_all(business_engine)
    runs = SQLAlchemyAgentRunRepository(session_factory=owner_factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=owner_factory)
    run = AgentRun(user_id="owner", message="inbound", status="queued")
    runs.save(run)
    queue.enqueue(run)
    execution = queue.claim("worker", lease_seconds=60)
    with business_factory.begin() as db:
        db.add_all(
            [
                Product(name="产品", model_number="A100"),
                Warehouse(code="MAIN", name="主仓库", status="active"),
            ]
        )
    with business_factory.begin() as db:
        product_id = db.query(Product).one().id
        warehouse_id = db.query(Warehouse).one().id
        destination = Warehouse(code="SECOND", name="副仓库", status="active")
        db.add(destination)
        db.flush()
        destination_id = destination.id
        if operation != "in":
            db.add(
                InventoryLedger(
                    product_id=product_id,
                    warehouse_id=warehouse_id,
                    quantity=100,
                    available_quantity=100,
                    reserved_quantity=0,
                    unit="个",
                )
            )
    if expired:
        with owner_factory.begin() as db:
            db.query(AgentTaskExecutionRecord).filter_by(run_id=run.run_id).update(
                {"lease_expires_at": "2000-01-01T00:00:00+00:00"}
            )

    @contextmanager
    def business_session():
        with business_factory() as db:
            yield db
            db.commit()

    monkeypatch.setattr("app.services.inventory_service.get_db", business_session)
    try:
        with worker_claim_scope(runs, execution, "worker"):

            def inbound():
                if operation == "out":
                    return InventoryService().inventory_out(product_id, warehouse_id, 50)
                if operation == "transfer":
                    return InventoryService().inventory_transfer(
                        product_id, warehouse_id, destination_id, 50
                    )
                return InventoryService().inventory_in(
                    product_id=None,
                    warehouse_id=None,
                    model_number="A100",
                    warehouse_name="主仓库",
                    quantity=50,
                )

            if expired:
                with pytest.raises(WorkerLeaseLost):
                    inbound()
            else:
                assert inbound()["success"]
        with business_factory() as db:
            expected_movements = 0 if expired else (2 if operation == "transfer" else 1)
            assert db.query(InventoryTransaction).count() == expected_movements
            ledgers = {
                row.warehouse_id: float(row.quantity) for row in db.query(InventoryLedger).all()
            }
            expected = (
                ({} if operation == "in" else {warehouse_id: 100})
                if expired
                else {warehouse_id: 50}
            )
            if operation == "transfer" and not expired:
                expected[destination_id] = 50
            assert ledgers == expected
    finally:
        business_engine.dispose()
        ownership_engine.dispose()
