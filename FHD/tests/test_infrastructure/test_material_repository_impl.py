"""Tests for app.infrastructure.persistence.material_repository_impl — coverage ramp."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.persistence.material_repository_impl import SQLAlchemyMaterialRepository


@pytest.fixture
def repo():
    return SQLAlchemyMaterialRepository()


def _make_material(**overrides):
    m = MagicMock()
    defaults = dict(
        id=1,
        material_code="MAT-001",
        name="测试原材料",
        category="化工",
        specification="25kg/桶",
        unit="kg",
        quantity=100.0,
        unit_price=50.0,
        supplier="供应商A",
        warehouse_location="A-01",
        min_stock=10.0,
        max_stock=500.0,
        description="测试描述",
        is_active=1,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 6, 1),
    )
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _mock_db_ctx(mock_db):
    """Return a context manager that yields mock_db."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


class TestMaterialToDict:
    def test_converts_all_fields(self, repo):
        m = _make_material()
        d = repo._material_to_dict(m)
        assert d["id"] == 1
        assert d["material_code"] == "MAT-001"
        assert d["name"] == "测试原材料"
        assert d["quantity"] == 100.0
        assert d["is_active"] == 1
        assert d["created_at"] == "2026-01-01T00:00:00"
        assert d["updated_at"] == "2026-06-01T00:00:00"

    def test_none_dates(self, repo):
        m = _make_material(created_at=None, updated_at=None)
        d = repo._material_to_dict(m)
        assert d["created_at"] is None
        assert d["updated_at"] is None


class TestFindAll:
    def test_returns_success_with_data(self, repo):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 1
        mock_query.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [
            _make_material()
        ]
        with patch(
            "app.infrastructure.persistence.material_repository_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = repo.find_all()
        assert result["success"] is True
        assert result["total"] == 1
        assert len(result["data"]) == 1

    def test_search_filter(self, repo):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []
        with patch(
            "app.infrastructure.persistence.material_repository_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = repo.find_all(search="测试", category="化工")
        assert result["success"] is True

    def test_db_error_returns_failure(self, repo):
        with patch(
            "app.infrastructure.persistence.material_repository_impl.get_db",
            side_effect=Exception("DB error"),
        ):
            result = repo.find_all()
        assert result["success"] is False
        assert "DB error" in result["message"]


class TestFindById:
    def test_found(self, repo):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = _make_material()
        with patch(
            "app.infrastructure.persistence.material_repository_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
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
            "app.infrastructure.persistence.material_repository_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = repo.find_by_id(999)
        assert result is None

    def test_db_error(self, repo):
        with patch(
            "app.infrastructure.persistence.material_repository_impl.get_db",
            side_effect=Exception("err"),
        ):
            result = repo.find_by_id(1)
        assert result is None


class TestCreate:
    def test_success(self, repo):
        mock_db = MagicMock()
        mat = _make_material()
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()
        with patch(
            "app.infrastructure.persistence.material_repository_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ), patch(
            "app.infrastructure.persistence.material_repository_impl.Material",
            return_value=mat,
        ):
            result = repo.create({"name": "新原材料", "category": "化工"})
        assert result["success"] is True

    def test_db_error(self, repo):
        with patch(
            "app.infrastructure.persistence.material_repository_impl.get_db",
            side_effect=Exception("fail"),
        ):
            result = repo.create({"name": "x"})
        assert result["success"] is False


class TestUpdate:
    def test_success(self, repo):
        mock_db = MagicMock()
        mat = _make_material()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = mat
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()
        with patch(
            "app.infrastructure.persistence.material_repository_impl.get_db",
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
            "app.infrastructure.persistence.material_repository_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = repo.update(999, {"name": "x"})
        assert result["success"] is False

    def test_db_error(self, repo):
        with patch(
            "app.infrastructure.persistence.material_repository_impl.get_db",
            side_effect=Exception("fail"),
        ):
            result = repo.update(1, {"name": "x"})
        assert result["success"] is False


class TestDelete:
    def test_success(self, repo):
        mock_db = MagicMock()
        mat = _make_material()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = mat
        mock_db.commit = MagicMock()
        with patch(
            "app.infrastructure.persistence.material_repository_impl.get_db",
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
            "app.infrastructure.persistence.material_repository_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = repo.delete(999)
        assert result is False


class TestBatchDelete:
    def test_success(self, repo):
        mock_db = MagicMock()
        mat = _make_material()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [mat]
        mock_db.commit = MagicMock()
        with patch(
            "app.infrastructure.persistence.material_repository_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = repo.batch_delete([1, 2])
        assert result == 1

    def test_db_error(self, repo):
        with patch(
            "app.infrastructure.persistence.material_repository_impl.get_db",
            side_effect=Exception("fail"),
        ):
            result = repo.batch_delete([1])
        assert result == 0


class TestFindLowStock:
    def test_with_threshold(self, repo):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value.all.return_value = [_make_material()]
        with patch(
            "app.infrastructure.persistence.material_repository_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = repo.find_low_stock(threshold=5.0)
        assert len(result) == 1

    def test_without_threshold(self, repo):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value.all.return_value = []
        with patch(
            "app.infrastructure.persistence.material_repository_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = repo.find_low_stock()
        assert result == []

    def test_db_error(self, repo):
        with patch(
            "app.infrastructure.persistence.material_repository_impl.get_db",
            side_effect=Exception("fail"),
        ):
            result = repo.find_low_stock()
        assert result == []
