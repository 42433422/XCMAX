from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.db.base import Base
from app.db.models import InventoryLedger, InventoryTransaction, Product, Warehouse
from app.infrastructure.tenant_scope import current_tenant_id, tenant_scope


def test_fresh_thread_inventory_executor_writes_only_recorded_tenant(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'tenants.db'}")
    factory = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    identities = {}
    for tenant in (1, 2):
        with tenant_scope(tenant), factory.begin() as db:
            product = Product(name="同名产品", model_number="A100")
            warehouse = Warehouse(code=f"MAIN-{tenant}", name="同名仓库", status="active")
            db.add_all([product, warehouse])
            db.flush()
            identities[tenant] = (product.id, warehouse.id)

    @contextmanager
    def business_session():
        with factory() as db:
            yield db
            db.commit()

    monkeypatch.setattr("app.services.inventory_service.get_db", business_session)
    step = AgentStep(
        node_id="stock",
        tool_id="inventory",
        action="stock_in",
        params={"model_number": "A100", "warehouse_name": "同名仓库", "quantity": 50},
    )

    def execute():
        assert current_tenant_id() is None
        response = AgentToolExecutor().execute(step, runtime_context={"tenant_id": "2"})
        assert current_tenant_id() is None
        return response

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            response = pool.submit(execute).result(timeout=20)
            # Reusing the same worker for an unscoped task must not inherit tenant 2.
            unscoped = pool.submit(AgentToolExecutor().execute, step, runtime_context={}).result(
                timeout=20
            )
        assert response["success"], response
        assert unscoped["success"] is False
        for tenant in (1, 2):
            with tenant_scope(tenant), factory() as db:
                ledgers = db.query(InventoryLedger).all()
                movements = db.query(InventoryTransaction).all()
                assert len(ledgers) == len(movements) == (1 if tenant == 2 else 0)
                if tenant == 2:
                    assert (ledgers[0].product_id, ledgers[0].warehouse_id) == identities[2]
                    assert float(ledgers[0].quantity) == 50
                    assert float(movements[0].quantity) == 50
    finally:
        engine.dispose()
