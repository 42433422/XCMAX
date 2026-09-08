from unittest.mock import Mock, patch

import pytest

from app.services.tools_workflow_registered import _registered_router_products


@pytest.mark.parametrize("field", ["measure_unit", "unit_name", "measurement_unit"])
def test_ai_measurement_update_preserves_legacy_customer_column(field):
    service = Mock()
    service.update_product.return_value = {"success": True}
    with patch("app.services.get_products_service", return_value=service):
        result = _registered_router_products("update", {"id": 1, field: "桶"}, {}, "normal", "")
    assert result["success"]
    service.update_product.assert_called_once_with(1, {"measurement_unit": "桶"})


def test_ai_customer_update_does_not_replace_unit_with_default():
    service = Mock()
    with patch("app.services.get_products_service", return_value=service):
        result = _registered_router_products(
            "update", {"id": 1, "unit_name": "客户公司"}, {}, "normal", ""
        )
    assert result["error_code"] == "customer_product_link_unsupported"
    service.update_product.assert_not_called()


@pytest.mark.parametrize("field", ["measure_unit", "unit_name", "measurement_unit"])
def test_ai_measurement_update_persists_through_product_service(tmp_path, monkeypatch, field):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.application.product_measurement import product_measurement_unit
    from app.db.base import Base
    from app.db.models import Product
    from app.infrastructure.repositories.product_repository_impl import SQLAlchemyProductRepository
    from app.infrastructure.tenant_scope import tenant_scope
    from app.services.products_service import ProductsService

    engine = create_engine(f"sqlite:///{tmp_path / 'products.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    with factory.begin() as db:
        db.add(Product(id=1, tenant_id=1, name="产品", unit="客户公司", measurement_unit="箱"))
        db.add(Product(id=2, tenant_id=2, name="其他产品", unit="其他客户", measurement_unit="箱"))
    repository = SQLAlchemyProductRepository()
    with patch(
        "app.utils.performance.performance_initializer.get_performance_optimizer",
        return_value=Mock(
            redis_cache=None,
            query_optimizer=None,
            request_deduplicator=None,
            performance_monitor=None,
        ),
    ):
        service = ProductsService(repository)
    with patch("app.services.get_products_service", return_value=service), tenant_scope(1):
        result = _registered_router_products("update", {"id": 1, field: "桶"}, {}, "normal", "")
        assert result["success"], result
        product = repository.find_by_id(1)
        assert product.unit == "客户公司"
        assert product.to_dict()["measurement_unit"] == "桶"
        assert product_measurement_unit(product) == "桶"
        foreign = _registered_router_products("update", {"id": 2, field: "桶"}, {}, "normal", "")
        assert not foreign["success"]
    with factory() as db, tenant_scope(1):
        assert db.get(Product, 1).measurement_unit == "桶"
    with factory() as db, tenant_scope(2):
        assert db.get(Product, 2).measurement_unit == "箱"
    engine.dispose()
