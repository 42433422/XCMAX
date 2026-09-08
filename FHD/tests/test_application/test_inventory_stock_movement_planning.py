from app.application.workflow.inventory_stock_in_planning import (
    inventory_stock_in_nodes,
    inventory_stock_out_nodes,
)


def test_stock_out_missing_slots_asks_clarification():
    nodes = inventory_stock_out_nodes("出库10件A100")
    assert [(n.tool_id, n.action) for n in nodes] == [("clarify", "ask")]
    assert "产品" in nodes[0].params["question"]


def test_stock_out_negation_and_database_not_claimed():
    assert inventory_stock_out_nodes("不要出库 A100 10 件") == []
    assert inventory_stock_out_nodes("把数据出库到数据库") == []
    assert inventory_stock_out_nodes("你好") == []


def test_stock_in_and_out_directions_do_not_cross():
    assert inventory_stock_in_nodes("产品 A100 出库 50 件") == []
    assert inventory_stock_out_nodes("产品 A100 入库 50 件") == []


def test_stock_out_resolves_product_and_warehouse(monkeypatch):
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base
    from app.db.models import Product, Warehouse

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as db:
        db.add_all(
            [
                Product(id=201, tenant_id=1, name="A100", model_number="A100"),
                Warehouse(id=401, tenant_id=1, code="WH01", name="主仓库", status="active"),
            ]
        )

    @contextmanager
    def fake_get_db():
        with factory() as session:
            yield session

    import app.db.session as session_module

    monkeypatch.setattr(session_module, "get_db", fake_get_db)
    from app.infrastructure.tenant_scope import tenant_scope

    with tenant_scope(1):
        nodes = inventory_stock_out_nodes("产品 A100 出库 50 件")
    assert [(n.tool_id, n.action) for n in nodes] == [("inventory", "stock_out")]
    assert nodes[0].params["product_id"] == 201
    assert nodes[0].params["warehouse_id"] == 401
    assert nodes[0].params["quantity"] == 50.0
    assert nodes[0].risk == "high" and not nodes[0].idempotent
