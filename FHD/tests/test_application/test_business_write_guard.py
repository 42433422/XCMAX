from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
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


@pytest.mark.parametrize("separate_mod_database", [False, True])
@pytest.mark.parametrize("expired", [False, True])
def test_inventory_commit_requires_live_claim_without_rerouting_mod_data(
    tmp_path, monkeypatch, separate_mod_database, expired
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
            assert db.query(InventoryTransaction).count() == (0 if expired else 1)
            assert db.query(InventoryLedger).count() == (0 if expired else 1)
            if not expired:
                assert float(db.query(InventoryLedger).one().quantity) == 50
    finally:
        business_engine.dispose()
        ownership_engine.dispose()
