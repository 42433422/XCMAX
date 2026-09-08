from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import Product, PurchaseUnit
from app.db.models.customer_product_link import CustomerProductLink
from app.infrastructure.repositories.product_repository_impl import SQLAlchemyProductRepository
from app.infrastructure.tenant_scope import tenant_scope


def test_customer_export_includes_explicit_links_and_excludes_other_tenants(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'export.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    monkeypatch.setattr("app.utils.path_io.path_utils.get_data_dir", lambda: str(tmp_path))
    with factory.begin() as db:
        db.add_all(
            [
                Product(id=1, tenant_id=1, name="关联产品", unit="桶", price=10),
                Product(id=2, tenant_id=1, name="历史产品", unit="客户A", price=20),
                Product(id=3, tenant_id=2, name="其他租户产品", unit="客户A", price=30),
                PurchaseUnit(id=1, tenant_id=1, unit_name="客户A", is_active=True),
            ]
        )
        db.flush()
        db.add(CustomerProductLink(tenant_id=1, product_id=1, purchase_unit_id=1))
    with tenant_scope(1):
        result = SQLAlchemyProductRepository().export_to_excel(unit_name="客户A")
    assert result["success"], result
    workbook = load_workbook(result["file_path"], read_only=True, data_only=True)
    rows = list(workbook.active.values)
    assert {row[1] for row in rows[1:]} == {"关联产品", "历史产品"}
    assert len(rows) == 3
    workbook.close()
    engine.dispose()
