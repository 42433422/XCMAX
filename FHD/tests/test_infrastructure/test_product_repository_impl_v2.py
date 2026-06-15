"""Tests for app.infrastructure.persistence.product_repository_impl — coverage ramp."""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.persistence.product_repository_impl import (
    SQLAlchemyProductRepository,
    TRIVIAL_MEASURE_UNITS,
)


def _mock_db_ctx(mock_db):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _make_product(**overrides):
    m = MagicMock()
    defaults = dict(
        id=1,
        name="测试产品",
        model_number="M-001",
        specification="25kg",
        price=100.0,
        quantity=50,
        unit="测试客户",
        category="化工",
        brand="品牌A",
        description="描述",
        is_active=1,
        created_at="2026-01-01",
        updated_at="2026-06-01",
    )
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(m, k, v)
    m.__dict__ = dict(defaults)
    return m


@pytest.fixture
def repo():
    return SQLAlchemyProductRepository()


class TestApiScalar:
    def test_none(self):
        assert SQLAlchemyProductRepository._api_scalar(None) is None

    def test_nan_float(self):
        assert SQLAlchemyProductRepository._api_scalar(float("nan")) is None

    def test_nan_string(self):
        assert SQLAlchemyProductRepository._api_scalar("nan") is None
        assert SQLAlchemyProductRepository._api_scalar("NaN") is None

    def test_none_string(self):
        assert SQLAlchemyProductRepository._api_scalar("none") is None
        assert SQLAlchemyProductRepository._api_scalar("None") is None

    def test_nat_string(self):
        assert SQLAlchemyProductRepository._api_scalar("NaT") is None

    def test_null_string(self):
        assert SQLAlchemyProductRepository._api_scalar("null") is None

    def test_na_string(self):
        assert SQLAlchemyProductRepository._api_scalar("<NA>") is None

    def test_normal_string(self):
        assert SQLAlchemyProductRepository._api_scalar("hello") == "hello"

    def test_integer(self):
        assert SQLAlchemyProductRepository._api_scalar(42) == 42

    def test_normal_float(self):
        assert SQLAlchemyProductRepository._api_scalar(3.14) == 3.14

    def test_object_with_nan_float_conversion(self):
        class NanLike:
            def __float__(self):
                return float("nan")

        assert SQLAlchemyProductRepository._api_scalar(NanLike()) is None


class TestProductToDict:
    def test_converts_product(self, repo):
        p = _make_product()
        with patch(
            "app.infrastructure.persistence.product_repository_impl.inspect",
        ) as mock_inspect:
            mock_col1 = MagicMock()
            mock_col1.name = "id"
            mock_col2 = MagicMock()
            mock_col2.name = "name"
            mock_inspect.return_value.columns = [mock_col1, mock_col2]
            result = repo._product_to_dict(p)
        assert result["id"] == 1
        assert result["name"] == "测试产品"
        assert result["product_name"] == "测试产品"


class TestFindAll:
    def test_table_not_found(self, repo):
        mock_db = MagicMock()
        mock_db.__dict__ = {}
        with patch(
            "app.infrastructure.persistence.product_repository_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = repo.find_all()
        assert result["success"] is True
        assert result["data"] == []

    def test_db_error(self, repo):
        with patch(
            "app.infrastructure.persistence.product_repository_impl.get_db",
            side_effect=Exception("fail"),
        ):
            result = repo.find_all()
        assert result["success"] is False


class TestFindById:
    def test_found(self, repo):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = _make_product()
        with patch(
            "app.infrastructure.persistence.product_repository_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ), patch(
            "app.infrastructure.persistence.product_repository_impl.inspect",
        ) as mock_inspect:
            mock_col = MagicMock()
            mock_col.name = "id"
            mock_inspect.return_value.columns = [mock_col]
            result = repo.find_by_id(1)
        assert result is not None
        assert result["id"] == 1

    def test_not_found(self, repo):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        with patch(
            "app.infrastructure.persistence.product_repository_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = repo.find_by_id(999)
        assert result is None

    def test_db_error(self, repo):
        with patch(
            "app.infrastructure.persistence.product_repository_impl.get_db",
            side_effect=Exception("err"),
        ):
            result = repo.find_by_id(1)
        assert result is None


class TestCreate:
    def test_success(self, repo):
        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()
        with patch(
            "app.infrastructure.persistence.product_repository_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ), patch(
            "app.infrastructure.persistence.product_repository_impl.Product",
            return_value=_make_product(),
        ):
            result = repo.create({"name": "新产品", "price": 10.0})
        assert result["success"] is True

    def test_empty_name(self, repo):
        result = repo.create({"name": ""})
        assert result["success"] is False

    def test_db_error(self, repo):
        with patch(
            "app.infrastructure.persistence.product_repository_impl.get_db",
            side_effect=Exception("fail"),
        ):
            result = repo.create({"name": "x"})
        assert result["success"] is False


class TestUpdate:
    def test_success(self, repo):
        mock_db = MagicMock()
        p = _make_product()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = p
        mock_db.commit = MagicMock()
        with patch(
            "app.infrastructure.persistence.product_repository_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = repo.update(1, {"name": "更新后"})
        assert result["success"] is True

    def test_not_found(self, repo):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        with patch(
            "app.infrastructure.persistence.product_repository_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = repo.update(999, {"name": "x"})
        assert result["success"] is False

    def test_no_update_fields(self, repo):
        mock_db = MagicMock()
        p = _make_product()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = p
        with patch(
            "app.infrastructure.persistence.product_repository_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = repo.update(1, {})
        assert result["success"] is False

    def test_db_error(self, repo):
        with patch(
            "app.infrastructure.persistence.product_repository_impl.get_db",
            side_effect=Exception("fail"),
        ):
            result = repo.update(1, {"name": "x"})
        assert result["success"] is False


class TestDelete:
    def test_success(self, repo):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = _make_product()
        mock_db.delete = MagicMock()
        mock_db.commit = MagicMock()
        with patch(
            "app.infrastructure.persistence.product_repository_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = repo.delete(1)
        assert result is True

    def test_not_found(self, repo):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        with patch(
            "app.infrastructure.persistence.product_repository_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = repo.delete(999)
        assert result is False


class TestExists:
    def test_exists(self, repo):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = _make_product()
        with patch(
            "app.infrastructure.persistence.product_repository_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = repo.exists(1)
        assert result is True

    def test_not_exists(self, repo):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        with patch(
            "app.infrastructure.persistence.product_repository_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = repo.exists(999)
        assert result is False


class TestBatchCreate:
    def test_empty_list(self, repo):
        result = repo.batch_create([])
        assert result["success"] is False

    def test_db_error(self, repo):
        with patch(
            "app.infrastructure.persistence.product_repository_impl.get_db",
            side_effect=Exception("fail"),
        ):
            result = repo.batch_create([{"name": "x"}])
        assert result["success"] is False


class TestBatchDelete:
    def test_empty_ids(self, repo):
        result = repo.batch_delete([])
        assert result["success"] is False

    def test_db_error(self, repo):
        with patch(
            "app.infrastructure.persistence.product_repository_impl.get_db",
            side_effect=Exception("fail"),
        ):
            result = repo.batch_delete([1])
        assert result["success"] is False


class TestFindNames:
    def test_db_error(self, repo):
        with patch(
            "app.infrastructure.persistence.product_repository_impl.get_db",
            side_effect=Exception("fail"),
        ):
            result = repo.find_names()
        assert result == []


class TestTrivialMeasureUnits:
    def test_contains_common_units(self):
        assert "件" in TRIVIAL_MEASURE_UNITS
        assert "个" in TRIVIAL_MEASURE_UNITS
        assert "箱" in TRIVIAL_MEASURE_UNITS
        assert "桶" in TRIVIAL_MEASURE_UNITS
        assert "千克" in TRIVIAL_MEASURE_UNITS
