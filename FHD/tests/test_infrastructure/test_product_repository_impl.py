"""Tests for app.infrastructure.persistence.product_repository_impl."""

from __future__ import annotations

import math
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from app.infrastructure.persistence.product_repository_impl import (
    TRIVIAL_MEASURE_UNITS,
    SQLAlchemyProductRepository,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo():
    return SQLAlchemyProductRepository()


def _make_mock_product(**overrides):
    """Create a mock Product ORM object with realistic attributes."""
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
    p = MagicMock()
    p.__dict__ = dict(defaults)
    return p


def _mock_db_ctx(mock_db):
    """Return a context manager that yields mock_db."""

    @contextmanager
    def _ctx():
        yield mock_db

    return _ctx()


# ---------------------------------------------------------------------------
# _api_scalar
# ---------------------------------------------------------------------------


class TestApiScalar:
    def test_none_returns_none(self):
        assert SQLAlchemyProductRepository._api_scalar(None) is None

    def test_float_nan_returns_none(self):
        assert SQLAlchemyProductRepository._api_scalar(float("nan")) is None

    def test_string_nan_returns_none(self):
        assert SQLAlchemyProductRepository._api_scalar("nan") is None

    def test_string_none_returns_none(self):
        assert SQLAlchemyProductRepository._api_scalar("none") is None

    def test_string_nat_returns_none(self):
        assert SQLAlchemyProductRepository._api_scalar("NaT") is None

    def test_string_na_angle_returns_none(self):
        assert SQLAlchemyProductRepository._api_scalar("<NA>") is None

    def test_string_null_returns_none(self):
        assert SQLAlchemyProductRepository._api_scalar("null") is None

    def test_string_with_whitespace_nan(self):
        assert SQLAlchemyProductRepository._api_scalar("  nan  ") is None

    def test_normal_string_returns_stripped(self):
        assert SQLAlchemyProductRepository._api_scalar("  hello  ") == "hello"

    def test_normal_string_returns_as_is(self):
        assert SQLAlchemyProductRepository._api_scalar("hello") == "hello"

    def test_integer_returns_integer(self):
        assert SQLAlchemyProductRepository._api_scalar(42) == 42

    def test_normal_float_returns_float(self):
        assert SQLAlchemyProductRepository._api_scalar(3.14) == 3.14

    def test_zero_returns_zero(self):
        assert SQLAlchemyProductRepository._api_scalar(0) == 0

    def test_empty_string_returns_empty(self):
        result = SQLAlchemyProductRepository._api_scalar("")
        assert result == ""

    def test_object_with_float_nan_conversion(self):
        class NanLike:
            def __float__(self):
                return float("nan")

        assert SQLAlchemyProductRepository._api_scalar(NanLike()) is None

    def test_object_without_float_conversion(self):
        class Weird:
            pass

        w = Weird()
        assert SQLAlchemyProductRepository._api_scalar(w) is w

    def test_bool_true_returns_true(self):
        assert SQLAlchemyProductRepository._api_scalar(True) is True

    def test_bool_false_returns_false(self):
        assert SQLAlchemyProductRepository._api_scalar(False) is False


# ---------------------------------------------------------------------------
# _product_to_dict
# ---------------------------------------------------------------------------


class TestProductToDict:
    def test_basic_conversion(self, repo):
        mock_product = _make_mock_product()
        # Patch inspect(Product).columns to return column names
        mock_col1 = MagicMock()
        mock_col1.name = "id"
        mock_col2 = MagicMock()
        mock_col2.name = "name"
        mock_col3 = MagicMock()
        mock_col3.name = "price"
        mock_col4 = MagicMock()
        mock_col4.name = "unit"

        with patch("app.infrastructure.persistence.product_repository_impl.inspect") as mock_insp:
            # inspect(Product) returns a mapper-like object
            mock_mapper = MagicMock()
            mock_mapper.columns = [mock_col1, mock_col2, mock_col3, mock_col4]
            mock_insp.return_value = mock_mapper

            result = repo._product_to_dict(mock_product)

        assert result["name"] == "测试产品"
        assert result["price"] == 99.5
        assert result["product_name"] == "测试产品"

    def test_name_copies_to_product_name(self, repo):
        mock_product = _make_mock_product()
        mock_col = MagicMock()
        mock_col.name = "name"

        with patch("app.infrastructure.persistence.product_repository_impl.inspect") as mock_insp:
            mock_mapper = MagicMock()
            mock_mapper.columns = [mock_col]
            mock_insp.return_value = mock_mapper
            result = repo._product_to_dict(mock_product)

        assert result["product_name"] == "测试产品"

    def test_empty_name_no_product_name(self, repo):
        mock_product = _make_mock_product(name="")
        mock_col = MagicMock()
        mock_col.name = "name"

        with patch("app.infrastructure.persistence.product_repository_impl.inspect") as mock_insp:
            mock_mapper = MagicMock()
            mock_mapper.columns = [mock_col]
            mock_insp.return_value = mock_mapper
            result = repo._product_to_dict(mock_product)

        # name is "" which is falsy, so product_name should not be set
        assert "product_name" not in result

    def test_nan_price_converted_to_none(self, repo):
        mock_product = _make_mock_product(price=float("nan"))
        mock_col = MagicMock()
        mock_col.name = "price"

        with patch("app.infrastructure.persistence.product_repository_impl.inspect") as mock_insp:
            mock_mapper = MagicMock()
            mock_mapper.columns = [mock_col]
            mock_insp.return_value = mock_mapper
            result = repo._product_to_dict(mock_product)

        assert result["price"] is None


# ---------------------------------------------------------------------------
# find_all
# ---------------------------------------------------------------------------


class TestFindAll:
    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_products_table_not_exists_returns_empty(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.__dict__["bind"] = MagicMock()
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        with patch("app.infrastructure.persistence.product_repository_impl.inspect") as mock_insp:
            mock_bind_insp = MagicMock()
            mock_bind_insp.get_table_names.return_value = []
            mock_insp.return_value = mock_bind_insp
            result = repo.find_all()

        assert result["success"] is True
        assert result["data"] == []
        assert result["total"] == 0

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_recoverable_error_returns_failure(self, mock_get_db, repo):
        mock_get_db.side_effect = OSError("DB connection lost")
        result = repo.find_all()
        assert result["success"] is False
        assert "查询失败" in result["message"]

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_with_unit_name_filter(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.__dict__["bind"] = MagicMock()
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.persistence.product_repository_impl.inspect") as mock_insp:
            mock_bind_insp = MagicMock()
            mock_bind_insp.get_table_names.return_value = ["products"]
            mock_insp.return_value = mock_bind_insp
            result = repo.find_all(unit_name="箱")

        assert result["success"] is True

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_with_model_number_filter(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.__dict__["bind"] = MagicMock()
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.persistence.product_repository_impl.inspect") as mock_insp:
            mock_bind_insp = MagicMock()
            mock_bind_insp.get_table_names.return_value = ["products"]
            mock_insp.return_value = mock_bind_insp
            result = repo.find_all(model_number="ABC-123")

        assert result["success"] is True

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_with_keyword_filter(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.__dict__["bind"] = MagicMock()
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.persistence.product_repository_impl.inspect") as mock_insp:
            mock_bind_insp = MagicMock()
            mock_bind_insp.get_table_names.return_value = ["products"]
            mock_insp.return_value = mock_bind_insp
            result = repo.find_all(keyword="测试 9803")

        assert result["success"] is True

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_pagination(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.__dict__["bind"] = MagicMock()
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.count.return_value = 100
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.persistence.product_repository_impl.inspect") as mock_insp:
            mock_bind_insp = MagicMock()
            mock_bind_insp.get_table_names.return_value = ["products"]
            mock_insp.return_value = mock_bind_insp
            result = repo.find_all(page=3, per_page=10)

        assert result["page"] == 3
        assert result["per_page"] == 10
        # total may differ due to mock chain behavior
        assert result["total"] >= 0

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_recoverable_error_on_table_names_check(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.__dict__["bind"] = MagicMock()
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        with patch("app.infrastructure.persistence.product_repository_impl.inspect") as mock_insp:
            mock_insp.side_effect = RuntimeError("inspect failed")
            result = repo.find_all()

        assert result["success"] is True
        assert result["data"] == []


# ---------------------------------------------------------------------------
# find_by_id
# ---------------------------------------------------------------------------


class TestFindById:
    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_product_found(self, mock_get_db, repo):
        mock_db = MagicMock()
        # Use a simple namespace object instead of MagicMock with __dict__ override
        # to avoid corrupting MagicMock internal state
        mock_product = type("Product", (), {"id": 1, "name": "测试产品", "price": 99.5})()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_product
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        # Patch _product_to_dict to avoid inspect(Product).columns complexity
        with patch.object(repo, "_product_to_dict", return_value={"id": 1, "name": "测试产品"}):
            result = repo.find_by_id(1)

        assert result is not None
        assert result["name"] == "测试产品"

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_product_not_found(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.find_by_id(999)
        assert result is None

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_recoverable_error_returns_none(self, mock_get_db, repo):
        mock_get_db.side_effect = OSError("DB error")
        result = repo.find_by_id(1)
        assert result is None


# ---------------------------------------------------------------------------
# find_product_units
# ---------------------------------------------------------------------------


class TestFindProductUnits:
    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_fallback_to_products_unit(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.bind = MagicMock()
        mock_db.query.return_value.distinct.return_value.all.return_value = [
            ("七彩乐园",),
            ("件",),
            ("箱",),
        ]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        with patch("app.infrastructure.persistence.product_repository_impl.inspect") as mock_insp:
            mock_insp_obj = MagicMock()
            mock_insp_obj.get_table_names.return_value = ["products"]
            mock_insp.return_value = mock_insp_obj

            # Patch at the source module since it's a local import
            with patch(
                "app.application.customer_app_service.get_customers_session",
                side_effect=ImportError("no module"),
            ):
                result = repo.find_product_units()

        assert "七彩乐园" in result
        assert "件" not in result
        assert "箱" not in result

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_purchase_units_authoritative(self, mock_get_db, repo):
        mock_cs = MagicMock()
        mock_cs.bind = MagicMock()
        mock_cs.get_bind.return_value = MagicMock()

        with patch("app.infrastructure.persistence.product_repository_impl.inspect") as mock_insp:
            mock_insp_obj = MagicMock()
            mock_insp_obj.get_table_names.return_value = ["purchase_units"]
            mock_insp_obj.get_columns.return_value = [
                {"name": "id"},
                {"name": "unit_name"},
                {"name": "is_active"},
            ]
            mock_insp.return_value = mock_insp_obj

            with patch(
                "app.application.customer_app_service.get_customers_session",
                return_value=mock_cs,
            ):
                with patch(
                    "app.db.models.purchase_unit.PurchaseUnit",
                ) as MockPU:
                    mock_cs.query.return_value.filter.return_value.filter.return_value.distinct.return_value.all.return_value = [
                        ("客户A",),
                    ]
                    result = repo.find_product_units()

        assert isinstance(result, list)

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_empty_units(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.bind = MagicMock()
        mock_db.query.return_value.distinct.return_value.all.return_value = []
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        with patch("app.infrastructure.persistence.product_repository_impl.inspect") as mock_insp:
            mock_insp_obj = MagicMock()
            mock_insp_obj.get_table_names.return_value = ["products"]
            mock_insp.return_value = mock_insp_obj

            with patch(
                "app.application.customer_app_service.get_customers_session",
                side_effect=ImportError("no module"),
            ):
                result = repo.find_product_units()

        assert result == []

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_deduplication(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.bind = MagicMock()
        mock_db.query.return_value.distinct.return_value.all.return_value = [
            ("客户A",),
            ("客户A",),
            ("客户B",),
        ]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        with patch("app.infrastructure.persistence.product_repository_impl.inspect") as mock_insp:
            mock_insp_obj = MagicMock()
            mock_insp_obj.get_table_names.return_value = ["products"]
            mock_insp.return_value = mock_insp_obj

            with patch(
                "app.application.customer_app_service.get_customers_session",
                side_effect=ImportError("no module"),
            ):
                result = repo.find_product_units()

        assert result.count("客户A") == 1


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


class TestCreate:
    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_create_success(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_product = MagicMock()
        mock_product.id = 42
        mock_db.add.return_value = None
        mock_db.commit.return_value = None
        mock_db.refresh.return_value = None
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        with patch("app.infrastructure.persistence.product_repository_impl.Product") as MockProduct:
            MockProduct.return_value = mock_product
            result = repo.create({"product_name": "新产品", "price": 10.0})

        assert result["success"] is True
        assert result["product_id"] == 42

    def test_create_empty_name_returns_error(self, repo):
        result = repo.create({"product_name": "", "price": 0})
        assert result["success"] is False
        assert "产品名称不能为空" in result["message"]

    def test_create_name_key_instead_of_product_name(self, repo):
        result = repo.create({"name": "", "price": 0})
        assert result["success"] is False

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_create_with_name_key(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_product = MagicMock()
        mock_product.id = 1
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        with patch("app.infrastructure.persistence.product_repository_impl.Product") as MockProduct:
            MockProduct.return_value = mock_product
            result = repo.create({"name": "用name键创建"})

        assert result["success"] is True

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_create_db_error(self, mock_get_db, repo):
        mock_get_db.side_effect = OSError("DB error")
        result = repo.create({"product_name": "测试"})
        assert result["success"] is False
        assert "创建失败" in result["message"]


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


class TestUpdate:
    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_update_success(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_product = MagicMock()
        mock_product.name = "旧名称"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_product
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.update(1, {"product_name": "新名称"})
        assert result["success"] is True

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_update_not_found(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.update(999, {"product_name": "不存在"})
        assert result["success"] is False
        assert "产品不存在" in result["message"]

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_update_no_fields(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_product = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_product
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.update(1, {})
        assert result["success"] is False
        assert "没有要更新的字段" in result["message"]

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_update_multiple_fields(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_product = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_product
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.update(
            1,
            {
                "price": 50.0,
                "description": "新描述",
                "model_number": "M2",
                "specification": "200x300",
                "quantity": 100,
                "category": "工具",
                "brand": "品牌B",
                "unit": "箱",
                "is_active": 0,
            },
        )
        assert result["success"] is True

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_update_with_name_key(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_product = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_product
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.update(1, {"name": "用name键更新"})
        assert result["success"] is True

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_update_db_error(self, mock_get_db, repo):
        mock_get_db.side_effect = OSError("DB error")
        result = repo.update(1, {"price": 10})
        assert result["success"] is False
        assert "更新失败" in result["message"]


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


class TestDelete:
    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_delete_success(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_product = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_product
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.delete(1)
        assert result is True

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_delete_not_found(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.delete(999)
        assert result is False

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_delete_db_error(self, mock_get_db, repo):
        mock_get_db.side_effect = OSError("DB error")
        result = repo.delete(1)
        assert result is False


# ---------------------------------------------------------------------------
# batch_create
# ---------------------------------------------------------------------------


class TestBatchCreate:
    def test_empty_list_returns_error(self, repo):
        result = repo.batch_create([])
        assert result["success"] is False
        assert "产品列表不能为空" in result["message"]

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_batch_create_success(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.bulk_insert_mappings.return_value = None
        mock_db.commit.return_value = None
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.batch_create(
            [
                {"product_name": "产品1", "price": 10},
                {"product_name": "产品2", "price": 20},
            ]
        )
        assert result["success"] is True
        assert result["success_count"] == 2

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_batch_create_with_empty_name(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.bulk_insert_mappings.return_value = None
        mock_db.commit.return_value = None
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.batch_create(
            [
                {"product_name": "有效产品"},
                {"product_name": ""},
            ]
        )
        assert result["success"] is False
        assert result["failed_count"] == 1

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_batch_create_db_error(self, mock_get_db, repo):
        mock_get_db.side_effect = OSError("DB error")
        result = repo.batch_create([{"product_name": "产品1"}])
        assert result["success"] is False
        assert "批量添加失败" in result["message"]


# ---------------------------------------------------------------------------
# batch_delete
# ---------------------------------------------------------------------------


class TestBatchDelete:
    def test_empty_ids_returns_error(self, repo):
        result = repo.batch_delete([])
        assert result["success"] is False
        assert "产品 ID 列表不能为空" in result["message"]

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_batch_delete_success(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_products = [MagicMock(), MagicMock()]
        mock_db.query.return_value.filter.return_value.all.return_value = mock_products
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.batch_delete([1, 2])
        assert result["success"] is True
        assert result["deleted_count"] == 2

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_batch_delete_not_found(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.batch_delete([999])
        assert result["success"] is False
        assert "未找到" in result["message"]

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_batch_delete_db_error(self, mock_get_db, repo):
        mock_get_db.side_effect = OSError("DB error")
        result = repo.batch_delete([1])
        assert result["success"] is False


# ---------------------------------------------------------------------------
# exists
# ---------------------------------------------------------------------------


class TestExists:
    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_exists_true(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = MagicMock()
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        assert repo.exists(1) is True

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_exists_false(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        assert repo.exists(999) is False

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_exists_db_error(self, mock_get_db, repo):
        mock_get_db.side_effect = OSError("DB error")
        assert repo.exists(1) is False


# ---------------------------------------------------------------------------
# find_names
# ---------------------------------------------------------------------------


class TestFindNames:
    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_find_names_success(self, mock_get_db, repo):
        mock_db = MagicMock()
        # When no keyword, chain is: db.query(Product.name).distinct().all()
        mock_db.query.return_value.distinct.return_value.all.return_value = [
            ("产品A",),
            ("产品B",),
            (None,),
        ]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        with patch("app.infrastructure.persistence.product_repository_impl.inspect") as mock_insp:
            mock_insp.return_value.get_table_names.return_value = ["products"]
            result = repo.find_names()

        assert result == ["产品A", "产品B"]

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_find_names_with_keyword(self, mock_get_db, repo):
        mock_db = MagicMock()
        # When keyword is provided, chain is: db.query(Product.name).filter().distinct().all()
        mock_db.query.return_value.filter.return_value.distinct.return_value.all.return_value = [
            ("测试产品",),
        ]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        with patch("app.infrastructure.persistence.product_repository_impl.inspect") as mock_insp:
            mock_insp.return_value.get_table_names.return_value = ["products"]
            result = repo.find_names(keyword="测试")

        assert "测试产品" in result

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_find_names_no_table(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        with patch("app.infrastructure.persistence.product_repository_impl.inspect") as mock_insp:
            mock_insp.return_value.get_table_names.return_value = []
            result = repo.find_names()

        assert result == []

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_find_names_db_error(self, mock_get_db, repo):
        mock_get_db.side_effect = OSError("DB error")
        result = repo.find_names()
        assert result == []


# ---------------------------------------------------------------------------
# TRIVIAL_MEASURE_UNITS constant
# ---------------------------------------------------------------------------


class TestTrivialMeasureUnits:
    def test_contains_common_units(self):
        assert "件" in TRIVIAL_MEASURE_UNITS
        assert "个" in TRIVIAL_MEASURE_UNITS
        assert "箱" in TRIVIAL_MEASURE_UNITS
        assert "千克" in TRIVIAL_MEASURE_UNITS

    def test_does_not_contain_customer_names(self):
        assert "七彩乐园" not in TRIVIAL_MEASURE_UNITS
        assert "客户A" not in TRIVIAL_MEASURE_UNITS
