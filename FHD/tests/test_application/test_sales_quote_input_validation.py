from unittest.mock import patch

import pytest

from app.application.sales_app_service import SalesAppService


@pytest.mark.parametrize(
    "item",
    [
        None,
        {},
        {"quantity": 1},
        {"unit_price": 25},
        {"quantity": 0, "unit_price": 25},
        {"quantity": -1, "unit_price": 25},
        {"quantity": "NaN", "unit_price": 25},
        {"quantity": "Infinity", "unit_price": 25},
        {"quantity": 1, "unit_price": -1},
        {"quantity": 1, "unit_price": "NaN"},
        {"quantity": 1, "unit_price": "Infinity"},
    ],
)
def test_invalid_quote_rejected_before_database_access(item):
    with patch("app.application.sales_app_service.get_db") as db:
        result = SalesAppService().quote({"customer_id": 1, "items": [item]})
    assert result["success"] is False
    db.assert_not_called()


def test_quote_validation_with_real_database_preserves_valid_zero_price(monkeypatch):
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base
    from app.db.models import Customer, Product, SalesOrder, SalesOrderItem
    from app.infrastructure.tenant_scope import tenant_scope

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    @contextmanager
    def database():
        with factory() as db:
            yield db

    monkeypatch.setattr("app.application.sales_app_service.get_db", database)
    with tenant_scope(1):
        with factory.begin() as db:
            db.add(Customer(id=1, tenant_id=1, customer_name="星光贸易"))
            db.add(Product(id=1, tenant_id=1, name="A100"))
        service = SalesAppService()
        rejected = service.quote(
            {
                "customer_id": 1,
                "items": [
                    {"product_id": 1, "quantity": 2, "unit_price": 25},
                    {"product_id": 1, "quantity": 0, "unit_price": 25},
                ],
            }
        )
        assert not rejected["success"]
        with factory() as db:
            assert db.query(SalesOrder).count() == 0
            assert db.query(SalesOrderItem).count() == 0
        accepted = service.quote(
            {
                "customer_id": 1,
                "items": [
                    {"product_id": 1, "quantity": "2.5", "unit_price": "0"},
                ],
            }
        )
        assert accepted["success"], accepted
        with factory() as db:
            order = db.query(SalesOrder).one()
            line = db.query(SalesOrderItem).one()
            assert order.state == "quote" and order.customer_id == 1
            assert float(line.quantity) == 2.5
            assert float(line.unit_price) == 0
            assert float(order.total_amount) == 0
    engine.dispose()
