from app.application.etl.product_unit_migration import classify_product_units


def test_classification_keeps_tenants_and_ambiguous_units_separate():
    customers = [
        {"id": 1, "tenant_id": 1, "unit_name": "公司A"},
        {"id": 2, "tenant_id": 2, "unit_name": "公司A"},
        {"id": 3, "tenant_id": 1, "unit_name": "公司B"},
        {"id": 4, "tenant_id": 1, "unit_name": "公司B"},
        {"id": 5, "tenant_id": 1, "unit_name": "桶"},
    ]
    units = ["公司A", "公司B", "桶", "个", "未知", "公司A"]
    rows = [{"id": i, "tenant_id": 1 if i < 5 else None, "unit": u} for i, u in enumerate(units)]
    result = classify_product_units(rows, customers)
    assert [r["classification"] for r in result] == [
        "customer_link_requires_measurement",
        "ambiguous_customer",
        "ambiguous_measure_or_customer",
        "measurement_unit",
        "unresolved_unit",
        "missing_tenant",
    ]
    assert result[0]["candidate_customer_ids"] == [1]
    assert result[-1]["candidate_customer_ids"] == []
    assert rows[0]["unit"] == "公司A"


def test_database_inspection_is_tenant_local_and_does_not_flush():
    import pytest
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.application.etl.product_unit_migration import inspect_product_units
    from app.db.base import Base
    from app.db.models.product import Product
    from app.db.models.purchase_unit import PurchaseUnit
    from app.infrastructure.tenant_scope import TenantScopeError, tenant_scope

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        db.add_all(
            [
                PurchaseUnit(id=1, tenant_id=1, unit_name="公司A"),
                PurchaseUnit(id=2, tenant_id=2, unit_name="公司A"),
                Product(id=1, tenant_id=1, name="产品A", unit="公司A"),
                Product(id=2, tenant_id=2, name="产品B", unit="公司A"),
            ]
        )
        db.commit()
        pending = Product(tenant_id=1, name="尚未提交", unit="公司A")
        db.add(pending)
        with tenant_scope(1):
            report = inspect_product_units(db)
        assert report == [
            {
                "product_id": 1,
                "tenant_id": 1,
                "classification": "customer_link_requires_measurement",
                "candidate_customer_ids": [1],
            }
        ]
        assert pending.id is None and pending in db.new
        with tenant_scope(None), pytest.raises(TenantScopeError):
            inspect_product_units(db)
        db.rollback()
    engine.dispose()


def test_backfill_is_idempotent_scoped_and_preserves_legacy_unit():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.application.etl.product_unit_migration import backfill_product_links
    from app.db.base import Base
    from app.db.models.customer_product_link import CustomerProductLink
    from app.db.models.product import Product
    from app.db.models.purchase_unit import PurchaseUnit
    from app.infrastructure.tenant_scope import tenant_scope

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db, tenant_scope(1):
        db.add_all(
            [
                PurchaseUnit(id=1, tenant_id=1, unit_name="公司A"),
                Product(id=1, tenant_id=1, name="旧产品", unit="公司A"),
                Product(id=2, tenant_id=2, name="其他租户", unit="公司A"),
                Product(id=3, tenant_id=1, name="普通产品", unit="桶"),
            ]
        )
        db.commit()
        results = backfill_product_links(db, [1, 2, 3, 1])
        assert [r["status"] for r in results] == ["created", "unavailable", "needs_review"]
        assert backfill_product_links(db, [1])[0]["status"] == "existing"
        assert db.get(Product, 1).unit == "公司A"
        db.rollback()
        assert db.query(CustomerProductLink).count() == 0
    engine.dispose()
