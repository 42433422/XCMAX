import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import Customer, Product
from app.infrastructure.tenant_scope import tenant_scope
from tests.benchmarks.task_fixtures import seed_initial_state


def test_initial_records_persist_and_invalid_batch_rolls_back():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with tenant_scope(1):
        with factory.begin() as db:
            seed_initial_state(
                db,
                [
                    {"entity": "customers", "values": {"id": 1, "customer_name": "星光贸易"}},
                    {"entity": "products", "values": {"id": 1, "name": "A100", "price": 25.5}},
                ],
                1,
            )
        with factory() as db:
            assert db.query(Customer).one().customer_name == "星光贸易"
            assert float(db.query(Product).one().price) == 25.5
        for invalid in [
            {"entity": "customers", "values": {"tenant_id": 2}},
            {"entity": "customers", "values": {"unknown": "x"}},
            {"entity": "users", "values": {}},
        ]:
            with pytest.raises(ValueError), factory.begin() as db:
                seed_initial_state(
                    db,
                    [
                        {"entity": "customers", "values": {"id": 2, "customer_name": "回滚客户"}},
                        invalid,
                    ],
                    1,
                )
            with factory() as db:
                assert db.query(Customer).count() == 1
    with tenant_scope(2), factory() as db:
        assert db.query(Customer).count() == 0
        assert db.query(Product).count() == 0
    engine.dispose()
