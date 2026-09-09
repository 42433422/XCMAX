from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.product import Product
from app.infrastructure.repositories.product_repository_impl import SQLAlchemyProductRepository
from app.infrastructure.tenant_scope import tenant_scope


def test_explicit_measurement_unit_survives_create_and_update(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    @contextmanager
    def database():
        with factory() as db:
            yield db

    monkeypatch.setattr("app.infrastructure.repositories.product_repository_impl.get_db", database)
    repo = SQLAlchemyProductRepository()
    with tenant_scope(1):
        result = repo.create_from_dict({"name": "P", "unit": "旧客户", "measurement_unit": "桶"})
        assert result["success"]
        product_id = result["product_id"]
        assert repo.update(product_id, {"measurement_unit": "箱"})["success"]
    with factory() as db:
        product = db.get(Product, product_id)
        assert product.measurement_unit == "箱"
        assert product.unit == "旧客户"
    engine.dispose()
