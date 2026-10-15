"""Tests for app.infrastructure.repositories.product_repository_impl — domain-style SQLAlchemy product repo."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.repositories.product_repository_impl import (
    SQLAlchemyProductRepository,
)


@pytest.fixture
def repo():
    return SQLAlchemyProductRepository()


@pytest.mark.parametrize("price", ["", 0, 12.5])
def test_mod_product_price_roundtrip_sqlite(monkeypatch, price):
    from pathlib import Path

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from app.db.base import Base
    from app.db.models import Product
    from app.infrastructure.mods.mod_manager import import_mod_backend_py
    from app.infrastructure.tenant_scope import tenant_scope
    from app.mod_sdk import erp_products_facade as facade
    from app.services.products_service import ProductsService

    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)

    @contextmanager
    def isolated_db():
        with tenant_scope(1), Session(engine) as session:
            yield session

    monkeypatch.setattr(
        "app.infrastructure.repositories.product_repository_impl.get_db", isolated_db
    )
    service = ProductsService(repository=SQLAlchemyProductRepository())
    service._cache = None
    monkeypatch.setattr(facade, "_service", lambda: service)
    monkeypatch.setattr(facade, "_write_gate", lambda request: None)
    mod_root = Path(__file__).resolve().parents[2] / "mods" / "xcagi-erp-domain-bridge"
    mod = import_mod_backend_py(str(mod_root), "xcagi-erp-domain-bridge", "blueprints")
    monkeypatch.setattr(
        mod,
        "_invoke",
        lambda domain, action, request, body: {
            "add": facade.products_add,
            "update": facade.products_update,
        }[action](request, body),
    )
    app = FastAPI()
    mod.register_fastapi_routes(app, "xcagi-erp-domain-bridge")
    route = "/api/mod/xcagi-erp-domain-bridge/products/"
    with TestClient(app) as client:
        result = client.post(route + "add", json={"name": "商品", "price": price})
        assert result.status_code == 200, result.text
        product_id = result.json()["data"]["id"]
        with isolated_db() as db:
            assert db.scalar(select(Product.price).where(Product.id == product_id)) == (
                0 if price == "" else price
            )
        payload = {"id": product_id, "name": "商品", "price": ""}
        assert client.post(route + "update", json=payload).status_code == 200
        with isolated_db() as db:
            assert db.scalar(select(Product.price).where(Product.id == product_id)) == 0
        payload["price"] = 12.5
        assert client.post(route + "update", json=payload).status_code == 200
        payload.pop("price")
        assert client.post(route + "update", json=payload).status_code == 200
        with isolated_db() as db:
            assert db.scalar(select(Product.price).where(Product.id == product_id)) == 12.5
    engine.dispose()


def _mock_db_ctx(mock_db):

    @contextmanager
    def _ctx():
        yield mock_db

    return _ctx()


def _make_mock_product_model(**overrides):
    defaults = {
        "id": 1,
        "name": "测试产品",
        "model_number": "MOD-001",
        "specification": "100x200",
        "price": 99.5,
        "quantity": 50,
        "description": "描述",
        "category": "电子",
        "brand": "品牌A",
        "unit": "个",
        "is_active": 1,
        "created_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 1, 2),
    }
    defaults.update(overrides)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


class TestToDomainAndToDb:
    @patch("app.infrastructure.repositories.product_repository_impl.product_to_domain")
    def test_to_domain_delegates(self, mock_to_domain, repo):
        mock_model = _make_mock_product_model()
        mock_domain = MagicMock()
        mock_to_domain.return_value = mock_domain

        result = repo._to_domain(mock_model)
        mock_to_domain.assert_called_once_with(mock_model)
        assert result is mock_domain

    @patch("app.infrastructure.repositories.product_repository_impl.product_to_db")
    def test_to_db_model_delegates(self, mock_to_db, repo):
        mock_product = MagicMock()
        mock_to_db.return_value = {"name": "测试"}

        result = repo._to_db_model(mock_product)
        mock_to_db.assert_called_once_with(mock_product)
        assert result == {"name": "测试"}


class TestSave:
    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    @patch("app.infrastructure.repositories.product_repository_impl.product_to_domain")
    @patch("app.infrastructure.repositories.product_repository_impl.product_to_db")
    def test_save_new_product(self, mock_to_db, mock_to_domain, mock_get_db, repo):
        mock_product = MagicMock()
        mock_product.id = None
        mock_to_db.return_value = {"name": "新产品", "price": 10}
        mock_domain = MagicMock()
        mock_to_domain.return_value = mock_domain

        mock_db = MagicMock()
        mock_db_model = MagicMock()
        mock_db_model.id = 1
        mock_db.add.return_value = None
        mock_db.commit.return_value = None
        mock_db.refresh.side_effect = lambda x: None
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        with patch(
            "app.infrastructure.repositories.product_repository_impl.ProductModel",
            return_value=mock_db_model,
        ):
            result = repo.save(mock_product)

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    @patch("app.infrastructure.repositories.product_repository_impl.product_to_domain")
    @patch("app.infrastructure.repositories.product_repository_impl.product_to_db")
    def test_save_existing_product(self, mock_to_db, mock_to_domain, mock_get_db, repo):
        mock_product = MagicMock()
        mock_product.id = 1
        mock_to_db.return_value = {"name": "更新产品", "price": 20}
        mock_domain = MagicMock()
        mock_to_domain.return_value = mock_domain

        mock_existing = MagicMock()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_existing
        mock_db.commit.return_value = None
        mock_db.refresh.side_effect = lambda x: None
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.save(mock_product)

        mock_db.commit.assert_called_once()

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    @patch("app.infrastructure.repositories.product_repository_impl.product_to_domain")
    @patch("app.infrastructure.repositories.product_repository_impl.product_to_db")
    def test_save_product_with_id_not_found_creates_new(
        self, mock_to_db, mock_to_domain, mock_get_db, repo
    ):
        mock_product = MagicMock()
        mock_product.id = 999
        mock_to_db.return_value = {"name": "新产品"}
        mock_domain = MagicMock()
        mock_to_domain.return_value = mock_domain

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db_model = MagicMock()
        mock_db.add.return_value = None
        mock_db.commit.return_value = None
        mock_db.refresh.side_effect = lambda x: None
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        with patch(
            "app.infrastructure.repositories.product_repository_impl.ProductModel",
            return_value=mock_db_model,
        ):
            result = repo.save(mock_product)

        mock_db.add.assert_called_once()


class TestCreate:
    @patch.object(SQLAlchemyProductRepository, "save")
    def test_create_delegates_to_save(self, mock_save, repo):
        mock_product = MagicMock()
        mock_save.return_value = mock_product

        result = repo.create(mock_product)
        mock_save.assert_called_once_with(mock_product)
        assert result is mock_product


class TestFindById:
    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    @patch("app.infrastructure.repositories.product_repository_impl.product_to_domain")
    def test_found(self, mock_to_domain, mock_get_db, repo):
        mock_model = _make_mock_product_model()
        mock_domain = MagicMock()
        mock_to_domain.return_value = mock_domain

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_model
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.find_by_id(1)
        assert result is mock_domain

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    def test_not_found(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.find_by_id(999)
        assert result is None


class TestFindAllRepo:
    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    @patch("app.infrastructure.repositories.product_repository_impl.product_to_domain")
    def test_basic_query(self, mock_to_domain, mock_get_db, repo):
        mock_model = _make_mock_product_model()
        mock_domain = MagicMock()
        mock_to_domain.return_value = mock_domain

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.count.return_value = 1
        mock_query.all.return_value = [mock_model]
        mock_db.query.return_value = mock_query
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.find_all(page=1, per_page=20)
        assert isinstance(result, tuple)
        assert len(result) == 2

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    @patch("app.infrastructure.repositories.product_repository_impl.product_to_domain")
    def test_with_unit_name_filter(self, mock_to_domain, mock_get_db, repo):
        mock_to_domain.return_value = MagicMock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.find_all(page=1, per_page=20, unit_name="箱")
        assert isinstance(result, tuple)

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    @patch("app.infrastructure.repositories.product_repository_impl.product_to_domain")
    def test_with_model_number_filter(self, mock_to_domain, mock_get_db, repo):
        mock_to_domain.return_value = MagicMock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.find_all(page=1, per_page=20, model_number="ABC-123")
        assert isinstance(result, tuple)

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    @patch("app.infrastructure.repositories.product_repository_impl.product_to_domain")
    def test_with_model_number_empty_string(self, mock_to_domain, mock_get_db, repo):
        mock_to_domain.return_value = MagicMock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.find_all(page=1, per_page=20, model_number="  ")
        assert isinstance(result, tuple)

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    @patch("app.infrastructure.repositories.product_repository_impl.product_to_domain")
    def test_with_keyword_single_segment(self, mock_to_domain, mock_get_db, repo):
        mock_to_domain.return_value = MagicMock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.find_all(page=1, per_page=20, keyword="测试")
        assert isinstance(result, tuple)

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    @patch("app.infrastructure.repositories.product_repository_impl.product_to_domain")
    def test_with_keyword_multi_segment(self, mock_to_domain, mock_get_db, repo):
        mock_to_domain.return_value = MagicMock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.find_all(page=1, per_page=20, keyword="测试 9803")
        assert isinstance(result, tuple)

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    @patch("app.infrastructure.repositories.product_repository_impl.product_to_domain")
    def test_with_keyword_empty_after_strip(self, mock_to_domain, mock_get_db, repo):
        mock_to_domain.return_value = MagicMock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.find_all(page=1, per_page=20, keyword="  ")
        assert isinstance(result, tuple)


class TestFindAllDict:
    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    def test_basic_dict_query(self, mock_get_db, repo):
        mock_model = _make_mock_product_model()
        mock_model.created_at = datetime(2026, 1, 1)
        mock_model.updated_at = datetime(2026, 1, 2)

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.count.return_value = 1
        mock_query.all.return_value = [mock_model]
        mock_db.query.return_value = mock_query
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.find_all_dict(page=1, per_page=20)
        assert isinstance(result, tuple)
        dicts, total = result
        assert total == 1
        assert len(dicts) == 1
        assert dicts[0]["name"] == "测试产品"
        assert dicts[0]["id"] == 1

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    def test_dict_with_none_fields(self, mock_get_db, repo):
        mock_model = MagicMock(spec=[])
        mock_model.id = 1
        mock_model.model_number = None
        mock_model.name = None
        mock_model.specification = None
        mock_model.price = None
        mock_model.quantity = None
        mock_model.description = None
        mock_model.category = None
        mock_model.brand = None
        mock_model.unit = None
        mock_model.is_active = None
        mock_model.created_at = None
        mock_model.updated_at = None

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.count.return_value = 1
        mock_query.all.return_value = [mock_model]
        mock_db.query.return_value = mock_query
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        dicts, total = repo.find_all_dict(page=1, per_page=20)
        assert dicts[0]["model_number"] == ""
        assert dicts[0]["name"] == ""
        assert dicts[0]["price"] == 0
        assert dicts[0]["quantity"] == 0
        assert dicts[0]["unit"] == "个"
        assert dicts[0]["is_active"] is False
        assert dicts[0]["created_at"] is None

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    def test_dict_with_unit_name_filter(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.find_all_dict(page=1, per_page=20, unit_name="箱")
        assert isinstance(result, tuple)

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    def test_dict_with_keyword_filter(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.find_all_dict(page=1, per_page=20, keyword="测试")
        assert isinstance(result, tuple)


class TestFindByModelNumber:
    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    @patch("app.infrastructure.repositories.product_repository_impl.product_to_domain")
    def test_found(self, mock_to_domain, mock_get_db, repo):
        mock_model = _make_mock_product_model()
        mock_domain = MagicMock()
        mock_to_domain.return_value = mock_domain

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_model
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.find_by_model_number("MOD-001")
        assert result is mock_domain

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    def test_not_found(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.find_by_model_number("NONEXISTENT")
        assert result is None


class TestFindByName:
    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    @patch("app.infrastructure.repositories.product_repository_impl.product_to_domain")
    def test_found(self, mock_to_domain, mock_get_db, repo):
        mock_model = _make_mock_product_model()
        mock_domain = MagicMock()
        mock_to_domain.return_value = mock_domain

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_model]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.find_by_name("测试")
        assert len(result) == 1
        assert result[0] is mock_domain

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    @patch("app.infrastructure.repositories.product_repository_impl.product_to_domain")
    def test_empty_result(self, mock_to_domain, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.find_by_name("不存在")
        assert result == []


class TestDelete:
    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    def test_delete_success(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_model = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_model
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.delete(1)
        assert result is True
        mock_db.delete.assert_called_once_with(mock_model)
        mock_db.commit.assert_called_once()

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    def test_delete_not_found(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.delete(999)
        assert result is False


class TestCount:
    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    def test_count_returns_number(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.query.return_value.count.return_value = 42
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.count()
        assert result == 42

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    def test_count_zero(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.query.return_value.count.return_value = 0
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.count()
        assert result == 0


class TestFindProductUnits:
    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    def test_fallback_to_products_unit(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.bind = MagicMock()
        mock_db.query.return_value.distinct.return_value.all.return_value = [
            ("七彩乐园",),
            ("件",),
            ("箱",),
        ]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        with patch("app.infrastructure.repositories.product_repository_impl.inspect") as mock_insp:
            mock_insp_obj = MagicMock()
            mock_insp_obj.get_table_names.return_value = ["products"]
            mock_insp.return_value = mock_insp_obj

            with patch(
                "app.application.customer_app_service.get_customers_session",
                side_effect=ImportError("no module"),
            ):
                result = repo.find_product_units()

        assert "七彩乐园" in result
        assert "件" not in result
        assert "箱" not in result

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    def test_purchase_units_authoritative(self, mock_get_db, repo):
        mock_cs = MagicMock()
        mock_cs.bind = MagicMock()
        mock_cs.get_bind.return_value = MagicMock()

        with patch("app.infrastructure.repositories.product_repository_impl.inspect") as mock_insp:
            mock_insp_obj = MagicMock()
            mock_insp_obj.get_table_names.return_value = ["purchase_units"]
            mock_insp.return_value = mock_insp_obj

            with patch(
                "app.application.customer_app_service.get_customers_session",
                return_value=mock_cs,
            ):
                mock_cs.query.return_value.filter.return_value.filter.return_value.distinct.return_value.all.return_value = [
                    ("客户A",),
                ]
                result = repo.find_product_units()

        assert isinstance(result, list)

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    def test_empty_units(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.bind = MagicMock()
        mock_db.query.return_value.distinct.return_value.all.return_value = []
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        with patch("app.infrastructure.repositories.product_repository_impl.inspect") as mock_insp:
            mock_insp_obj = MagicMock()
            mock_insp_obj.get_table_names.return_value = ["products"]
            mock_insp.return_value = mock_insp_obj

            with patch(
                "app.application.customer_app_service.get_customers_session",
                side_effect=ImportError("no module"),
            ):
                result = repo.find_product_units()

        assert result == []

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    def test_deduplication(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.bind = MagicMock()
        mock_db.query.return_value.distinct.return_value.all.return_value = [
            ("客户A",),
            ("客户A",),
            ("客户B",),
        ]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        with patch("app.infrastructure.repositories.product_repository_impl.inspect") as mock_insp:
            mock_insp_obj = MagicMock()
            mock_insp_obj.get_table_names.return_value = ["products"]
            mock_insp.return_value = mock_insp_obj

            with patch(
                "app.application.customer_app_service.get_customers_session",
                side_effect=ImportError("no module"),
            ):
                result = repo.find_product_units()

        assert result.count("客户A") == 1

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    def test_none_values_skipped(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.bind = MagicMock()
        mock_db.query.return_value.distinct.return_value.all.return_value = [
            (None,),
            ("",),
            ("有效单位",),
        ]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        with patch("app.infrastructure.repositories.product_repository_impl.inspect") as mock_insp:
            mock_insp_obj = MagicMock()
            mock_insp_obj.get_table_names.return_value = ["products"]
            mock_insp.return_value = mock_insp_obj

            with patch(
                "app.application.customer_app_service.get_customers_session",
                side_effect=ImportError("no module"),
            ):
                result = repo.find_product_units()

        assert None not in result
        assert "有效单位" in result

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    def test_recoverable_error_in_purchase_units(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.bind = MagicMock()
        mock_db.query.return_value.distinct.return_value.all.return_value = [
            ("产品A",),
        ]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        with patch("app.infrastructure.repositories.product_repository_impl.inspect") as mock_insp:
            mock_insp_obj = MagicMock()
            mock_insp_obj.get_table_names.return_value = ["products"]
            mock_insp.return_value = mock_insp_obj

            with patch(
                "app.application.customer_app_service.get_customers_session",
                side_effect=RuntimeError("session error"),
            ):
                result = repo.find_product_units()

        assert isinstance(result, list)
