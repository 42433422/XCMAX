import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.customer_product_links import ensure_customer_product_link
from app.db.base import Base
from app.db.models.customer_product_link import CustomerProductLink
from app.db.models.product import Product
from app.db.models.purchase_unit import PurchaseUnit
from app.infrastructure.tenant_scope import TenantScopeError, tenant_scope


def test_link_write_is_scoped_idempotent_and_caller_transactional():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add_all(
            [
                PurchaseUnit(id=1, tenant_id=1, unit_name="A"),
                PurchaseUnit(id=2, tenant_id=2, unit_name="A"),
                Product(id=1, tenant_id=1, name="P", unit="桶"),
                Product(id=2, tenant_id=2, name="P", unit="桶"),
            ]
        )
        db.commit()
        with tenant_scope(1):
            first, created = ensure_customer_product_link(db, 1, 1)
            assert created
            second, created = ensure_customer_product_link(db, 1, 1)
            assert not created and second.id == first.id
            for customer, product in [(2, 1), (1, 2), (True, 1)]:
                with pytest.raises(ValueError):
                    ensure_customer_product_link(db, customer, product)
        db.rollback()
        assert db.query(CustomerProductLink).count() == 0
        with tenant_scope(1):
            link, _ = ensure_customer_product_link(db, 1, 1)
            link_id = link.id
        db.commit()
        with tenant_scope(None), pytest.raises(TenantScopeError):
            ensure_customer_product_link(db, 1, 1)
    with factory() as db:
        assert db.get(CustomerProductLink, link_id).tenant_id == 1
        assert db.get(Product, 1).unit == "桶"
    engine.dispose()


def test_parallel_link_requests_share_one_committed_row(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    engine = create_engine("sqlite:///" + str(tmp_path / "links.sqlite3"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add_all(
            [
                PurchaseUnit(id=1, tenant_id=1, unit_name="A"),
                Product(id=1, tenant_id=1, name="P", unit="桶"),
            ]
        )
        db.commit()
    ready = Barrier(2)

    def create():
        with factory() as db, tenant_scope(1):
            ready.wait(timeout=5)
            link, created = ensure_customer_product_link(db, 1, 1)
            result = (link.id, created)
            db.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create(), range(2)))
    assert results[0][0] == results[1][0]
    assert sorted(row[1] for row in results) == [False, True]
    with factory() as db:
        assert db.query(CustomerProductLink).count() == 1
    engine.dispose()
