"""Tests for app.infrastructure.repositories.product_repository_export_mixin."""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.infrastructure.repositories.product_repository_export_mixin import ProductExportMixin


def _fake_get_db(db: MagicMock):
    """Return a callable that yields ``db`` as a context manager (mimics get_db)."""

    @contextmanager
    def _scope():
        yield db

    return _scope


def _db_with_products() -> tuple[MagicMock, MagicMock]:
    inspector = MagicMock()
    inspector.get_table_names.return_value = ["products"]
    db = MagicMock()
    db.bind = MagicMock()
    query = db.query.return_value
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = [
        SimpleNamespace(model_number="M1", name="产品A", price=10.0),
        SimpleNamespace(model_number="M2", name="产品B", price=20.0),
    ]
    fake_inspect = MagicMock(return_value=inspector)
    return db, fake_inspect


class TestExportToExcel:
    def test_success_writes_workbook(self) -> None:
        db, fake_inspect = _db_with_products()
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch(
                "app.infrastructure.repositories.product_repository_export_mixin.get_db",
                _fake_get_db(db),
            ),
            patch(
                "app.infrastructure.repositories.product_repository_export_mixin.inspect",
                fake_inspect,
            ),
            patch("app.utils.path_io.path_utils.get_data_dir", return_value=tmp),
        ):
            result = ProductExportMixin().export_to_excel(unit_name="蓝天单位")
        assert result["success"] is True
        assert result["count"] == 2
        assert result["filename"].endswith(".xlsx")
        assert result["file_path"]

    def test_products_table_missing_returns_failure(self) -> None:
        inspector = MagicMock()
        inspector.get_table_names.return_value = []
        db = MagicMock()
        db.bind = MagicMock()
        with (
            patch(
                "app.infrastructure.repositories.product_repository_export_mixin.get_db",
                _fake_get_db(db),
            ),
            patch(
                "app.infrastructure.repositories.product_repository_export_mixin.inspect",
                MagicMock(return_value=inspector),
            ),
        ):
            result = ProductExportMixin().export_to_excel()
        assert result["success"] is False
        assert "产品表不存在" in result["message"]

    def test_recoverable_error_returns_failure(self) -> None:
        inspector = MagicMock()
        inspector.get_table_names.side_effect = RuntimeError("db down")
        db = MagicMock()
        db.bind = MagicMock()
        with (
            patch(
                "app.infrastructure.repositories.product_repository_export_mixin.get_db",
                _fake_get_db(db),
            ),
            patch(
                "app.infrastructure.repositories.product_repository_export_mixin.inspect",
                MagicMock(return_value=inspector),
            ),
        ):
            result = ProductExportMixin().export_to_excel()
        assert result["success"] is False
        assert "导出失败" in result["message"]
