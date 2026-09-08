import pytest
from openpyxl import Workbook

from app.application.etl.parsers import parse_file
from app.application.etl.service_preview_helpers import suggest_mappings
from app.application.etl.targets.customer_products import CustomerProductsAdapter


@pytest.mark.parametrize("unit_header", ["计量单位", "数量单位", "库存单位"])
def test_workbook_preserves_customer_and_measurement_as_separate_columns(
    tmp_path, unit_header, monkeypatch
):
    path = tmp_path / "customer-products.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["客户名称", "产品型号", "产品名称", unit_header, "价格"])
    sheet.append(["测试客户", "P100", "测试产品", "桶", 20])
    workbook.save(path)
    workbook.close()
    dataset = parse_file(path, target_type="customer_products")
    mappings = suggest_mappings(dataset, CustomerProductsAdapter())
    by_target = {mapping["target"]: mapping["source"] for mapping in mappings}
    assert "customer_name" in by_target
    assert "measurement_unit" in by_target
    assert by_target["customer_name"] != by_target["measurement_unit"]
    assert len(dataset.rows) == 1
    row = dataset.rows[0].values
    assert row[by_target["customer_name"]] == "测试客户"
    assert row[by_target["measurement_unit"]] == "桶"

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base
    from app.db.models import (
        InventoryLedger,
        InventoryTransaction,
        Product,
        PurchaseUnit,
        Warehouse,
    )
    from app.db.models.customer_product_link import CustomerProductLink
    from app.infrastructure.tenant_scope import tenant_scope
    from app.services.inventory_service import InventoryService

    engine = create_engine("sqlite:///" + str(tmp_path / "business.sqlite3"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    mapped = {target: row[source] for target, source in by_target.items() if source}
    adapter = CustomerProductsAdapter()
    with factory() as db, tenant_scope(1):
        preview = adapter.preview(db, mapped, allowed_update_fields=set(), context={})
        assert preview.action == "new"
        adapter.execute_row(
            db,
            mapped,
            action="new",
            match_ref=preview.match_ref,
            allowed_update_fields=set(),
            context={},
        )
        db.add(Warehouse(id=1, tenant_id=1, name="测试仓", code="TEST"))
        db.commit()
        product = db.query(Product).one()
        product_id = product.id
        assert product.measurement_unit == "桶"
        assert product.unit == "测试客户"
        link = db.query(CustomerProductLink).one()
        assert link.product_id == product_id
        assert db.get(PurchaseUnit, link.purchase_unit_id).unit_name == "测试客户"
    from app.infrastructure.repositories.product_repository_impl import SQLAlchemyProductRepository

    with tenant_scope(1):
        repository = SQLAlchemyProductRepository()
        domain = repository.find_by_id(product_id)
        assert domain.to_dict()["measurement_unit"] == "桶"
        assert domain.unit == "测试客户"
        domain.description = "修改描述后仍保留计量单位"
        saved = repository.save(domain)
        assert saved.measurement_unit == "桶"
        rows, total = repository.find_all_dict()
        assert total == 1 and rows[0]["measurement_unit"] == "桶"
        assert rows[0]["unit"] == "测试客户"
        batch = repository.batch_create(
            [{"name": "第二产品", "unit": "测试客户", "measurement_unit": "箱"}]
        )
        assert batch["success"], batch
        rows, total = repository.find_all_dict()
        assert total == 2
        assert next(row for row in rows if row["name"] == "第二产品")["measurement_unit"] == "箱"
        result = InventoryService().inventory_in(
            product_id=product_id, warehouse_id=1, quantity=3, requested_unit="桶"
        )
        assert result["success"], result
        repeated = InventoryService().inventory_in(
            product_id=product_id, warehouse_id=1, quantity=2, requested_unit="桶", unit_price=0
        )
        assert repeated["success"], repeated
    with factory() as db:
        ledger = db.query(InventoryLedger).one()
        assert ledger.unit == "桶" and float(ledger.quantity) == 5
        receipts = db.query(InventoryTransaction).order_by(InventoryTransaction.id).all()
        assert receipts[0].unit_price is None and receipts[0].total_amount is None
        assert float(receipts[1].unit_price) == 0 and float(receipts[1].total_amount) == 0
    engine.dispose()
