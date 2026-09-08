from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.customer_product_link import CustomerProductLink
from app.db.models.product import Product
from app.db.models.purchase_unit import PurchaseUnit
from app.infrastructure.repositories.product_query_helpers import apply_product_filters


def test_customer_query_reads_explicit_and_legacy_products_without_cross_tenant_link():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        db.add_all(
            [
                PurchaseUnit(id=1, tenant_id=1, unit_name="客户A"),
                PurchaseUnit(id=2, tenant_id=2, unit_name="客户A"),
                Product(id=1, tenant_id=1, name="独立关联", unit="桶"),
                Product(id=2, tenant_id=1, name="旧数据", unit="客户A"),
                Product(id=3, tenant_id=1, name="错误跨租户关联", unit="桶"),
            ]
        )
        db.flush()
        db.add_all(
            [
                CustomerProductLink(tenant_id=1, purchase_unit_id=1, product_id=1),
                CustomerProductLink(tenant_id=1, purchase_unit_id=2, product_id=3),
            ]
        )
        db.commit()
        rows = apply_product_filters(
            db.query(Product).filter(Product.tenant_id == 1), unit_name="客户A"
        ).all()
        assert {row.id for row in rows} == {1, 2}
        assert db.get(Product, 1).unit == "桶"
    engine.dispose()
