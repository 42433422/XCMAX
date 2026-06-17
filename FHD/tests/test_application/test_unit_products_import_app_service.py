"""Tests for app.application.unit_products_import_app_service — unit products import."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from app.application.unit_products_import_app_service import UnitProductsImportService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def service():
    with patch(
        "app.application.unit_products_import_app_service.get_upload_dir",
        return_value="/tmp/test_uploads",
    ):
        svc = UnitProductsImportService()
    return svc


def _mock_db_ctx(mock_db):
    """Return a context manager that yields mock_db."""

    @contextmanager
    def _ctx():
        yield mock_db

    return _ctx()


def _create_test_sqlite_db(db_path: str, products: list[dict] | None = None):
    """Create a test SQLite database with a products table."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            model_number TEXT,
            specification TEXT,
            price REAL,
            quantity INTEGER,
            description TEXT,
            category TEXT,
            brand TEXT,
            unit TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        )"""
    )
    if products:
        for p in products:
            cur.execute(
                "INSERT INTO products (name, model_number, specification, price, quantity, description, category, brand, unit, is_active) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    p.get("name"),
                    p.get("model_number"),
                    p.get("specification"),
                    p.get("price"),
                    p.get("quantity"),
                    p.get("description"),
                    p.get("category"),
                    p.get("brand"),
                    p.get("unit"),
                    p.get("is_active", 1),
                ),
            )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# _validate_params
# ---------------------------------------------------------------------------


class TestValidateParams:
    """_validate_params() — 输入参数验证"""

    def test_empty_saved_name(self, service):
        """saved_name 为空"""
        result = service._validate_params("", "unit1")
        assert result is not None
        assert result["success"] is False
        assert "saved_name" in result["message"]

    def test_none_saved_name(self, service):
        """saved_name 为 None"""
        result = service._validate_params(None, "unit1")
        assert result is not None
        assert result["success"] is False

    def test_empty_unit_name(self, service):
        """unit_name 为空"""
        result = service._validate_params("file.db", "")
        assert result is not None
        assert result["success"] is False
        assert "unit_name" in result["message"]

    def test_none_unit_name(self, service):
        """unit_name 为 None"""
        result = service._validate_params("file.db", None)
        assert result is not None
        assert result["success"] is False

    def test_path_traversal_saved_name(self, service):
        """saved_name 包含路径穿越"""
        result = service._validate_params("../etc/passwd", "unit1")
        assert result is not None
        assert result["success"] is False
        assert "路径穿越" in result["message"]

    def test_slash_in_saved_name(self, service):
        """saved_name 包含路径分隔符"""
        result = service._validate_params("sub/file.db", "unit1")
        assert result is not None
        assert result["success"] is False
        # The source checks basename first, then slash
        assert "不合法" in result["message"]

    def test_backslash_in_saved_name(self, service):
        """saved_name 包含反斜杠"""
        result = service._validate_params("sub\\file.db", "unit1")
        assert result is not None
        assert result["success"] is False

    def test_valid_params(self, service):
        """合法参数返回 None"""
        result = service._validate_params("file.db", "unit1")
        assert result is None


# ---------------------------------------------------------------------------
# _parse_float / _parse_int
# ---------------------------------------------------------------------------


class TestParseHelpers:
    """_parse_float() / _parse_int() — 数值解析"""

    def test_parse_float_valid(self, service):
        assert service._parse_float("3.14") == 3.14

    def test_parse_float_none(self, service):
        assert service._parse_float(None) == 0.0

    def test_parse_float_empty_string(self, service):
        assert service._parse_float("") == 0.0

    def test_parse_float_whitespace(self, service):
        assert service._parse_float("  ") == 0.0

    def test_parse_float_invalid(self, service):
        assert service._parse_float("abc") == 0.0

    def test_parse_float_integer(self, service):
        assert service._parse_float(42) == 42.0

    def test_parse_int_valid(self, service):
        assert service._parse_int("42") == 42

    def test_parse_int_none(self, service):
        assert service._parse_int(None) is None

    def test_parse_int_empty_string(self, service):
        assert service._parse_int("") is None

    def test_parse_int_whitespace(self, service):
        assert service._parse_int("  ") is None

    def test_parse_int_invalid(self, service):
        assert service._parse_int("abc") is None

    def test_parse_int_float_string(self, service):
        assert service._parse_int("3.14") is None


# ---------------------------------------------------------------------------
# _read_source_products
# ---------------------------------------------------------------------------


class TestReadSourceProducts:
    """_read_source_products() — 读取源产品数据"""

    def test_read_products_from_sqlite(self, tmp_path):
        """从 SQLite 读取产品"""
        db_path = str(tmp_path / "test.db")
        _create_test_sqlite_db(
            db_path,
            [
                {"name": "产品A", "model_number": "M-001", "price": 10.5, "quantity": 100},
                {"name": "产品B", "model_number": "M-002", "price": 20.0, "quantity": 50},
            ],
        )

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        service = UnitProductsImportService.__new__(UnitProductsImportService)
        result = service._read_source_products(cur, "测试单位")
        conn.close()

        assert len(result) == 2
        assert result[0]["product_name"] == "产品A"
        assert result[0]["unit"] == "测试单位"
        assert result[0]["price"] == 10.5

    def test_read_products_no_name_skipped(self, tmp_path):
        """无名称的产品被跳过"""
        db_path = str(tmp_path / "test.db")
        _create_test_sqlite_db(
            db_path,
            [
                {"name": "", "model_number": "M-001", "price": 10.0, "quantity": 5},
                {"name": "有效产品", "model_number": "M-002", "price": 20.0, "quantity": 10},
            ],
        )

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        service = UnitProductsImportService.__new__(UnitProductsImportService)
        result = service._read_source_products(cur, "单位")
        conn.close()

        assert len(result) == 1
        assert result[0]["product_name"] == "有效产品"

    def test_read_products_no_products_table(self, tmp_path):
        """无 products 表时返回空列表"""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        # Create a different table
        cur.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY)")
        conn.commit()

        service = UnitProductsImportService.__new__(UnitProductsImportService)
        result = service._read_source_products(cur, "单位")
        conn.close()

        assert result == []

    def test_read_products_no_name_column(self, tmp_path):
        """products 表无 name 列时返回空列表"""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, price REAL)")
        conn.commit()

        service = UnitProductsImportService.__new__(UnitProductsImportService)
        result = service._read_source_products(cur, "单位")
        conn.close()

        assert result == []

    def test_read_products_with_all_fields(self, tmp_path):
        """包含所有字段的产品"""
        db_path = str(tmp_path / "test.db")
        _create_test_sqlite_db(
            db_path,
            [
                {
                    "name": "完整产品",
                    "model_number": "FULL-001",
                    "specification": "100x200",
                    "price": 99.99,
                    "quantity": 200,
                    "description": "测试描述",
                    "category": "电子",
                    "brand": "品牌A",
                    "is_active": 1,
                },
            ],
        )

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        service = UnitProductsImportService.__new__(UnitProductsImportService)
        result = service._read_source_products(cur, "单位")
        conn.close()

        assert len(result) == 1
        p = result[0]
        assert p["product_name"] == "完整产品"
        assert p["model_number"] == "FULL-001"
        assert p["specification"] == "100x200"
        assert p["price"] == 99.99
        assert p["quantity"] == 200
        assert p["description"] == "测试描述"
        assert p["category"] == "电子"
        assert p["brand"] == "品牌A"
        assert p["is_active"] == 1


# ---------------------------------------------------------------------------
# _ensure_unit_exists
# ---------------------------------------------------------------------------


class TestEnsureUnitExists:
    """_ensure_unit_exists() — 确保购买单位存在"""

    @patch("app.application.unit_products_import_app_service.get_db")
    def test_existing_customer_returns_true(self, mock_get_db):
        """客户已存在时返回 True"""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = MagicMock()
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        service = UnitProductsImportService.__new__(UnitProductsImportService)
        result = service._ensure_unit_exists("已有单位", True)
        assert result is True

    @patch("app.application.unit_products_import_app_service.get_db")
    def test_no_existing_create_disabled(self, mock_get_db):
        """客户不存在且不创建时返回 False"""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        service = UnitProductsImportService.__new__(UnitProductsImportService)
        result = service._ensure_unit_exists("新单位", False)
        assert result is False

    @patch("app.application.unit_products_import_app_service.get_db")
    def test_create_new_customer_success(self, mock_get_db):
        """创建新客户成功时返回 True"""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        mock_customer_service = MagicMock()
        mock_customer_service.create.return_value = {"success": True}

        service = UnitProductsImportService.__new__(UnitProductsImportService)
        with patch(
            "app.bootstrap.get_customer_app_service",
            return_value=mock_customer_service,
        ):
            result = service._ensure_unit_exists("新单位", True)
        assert result is True

    @patch("app.application.unit_products_import_app_service.get_db")
    def test_create_customer_name_exists_error(self, mock_get_db):
        """创建客户时名称已存在仍返回 True"""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        mock_customer_service = MagicMock()
        mock_customer_service.create.return_value = {
            "success": False,
            "message": "客户名称已存在",
        }

        service = UnitProductsImportService.__new__(UnitProductsImportService)
        with patch(
            "app.bootstrap.get_customer_app_service",
            return_value=mock_customer_service,
        ):
            result = service._ensure_unit_exists("已存在单位", True)
        assert result is True

    @patch("app.application.unit_products_import_app_service.get_db")
    def test_create_customer_other_error(self, mock_get_db):
        """创建客户其他错误返回 False"""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        mock_customer_service = MagicMock()
        mock_customer_service.create.return_value = {
            "success": False,
            "message": "数据库错误",
        }

        service = UnitProductsImportService.__new__(UnitProductsImportService)
        with patch(
            "app.bootstrap.get_customer_app_service",
            return_value=mock_customer_service,
        ):
            result = service._ensure_unit_exists("错误单位", True)
        assert result is False


# ---------------------------------------------------------------------------
# _deduplicate_products
# ---------------------------------------------------------------------------


class TestDeduplicateProducts:
    """_deduplicate_products() — 产品去重"""

    @patch("app.application.unit_products_import_app_service.get_db")
    def test_no_duplicates(self, mock_get_db):
        """无重复产品"""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        service = UnitProductsImportService.__new__(UnitProductsImportService)
        products = [
            {"product_name": "产品A", "model_number": "M-001"},
            {"product_name": "产品B", "model_number": "M-002"},
        ]
        deduped, skipped = service._deduplicate_products(products, "单位")
        assert len(deduped) == 2
        assert skipped == 0

    @patch("app.application.unit_products_import_app_service.get_db")
    def test_duplicate_by_model_number(self, mock_get_db):
        """按型号去重"""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [
            ("M-001", "产品A", ""),
        ]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        service = UnitProductsImportService.__new__(UnitProductsImportService)
        products = [
            {"product_name": "产品A", "model_number": "M-001"},
            {"product_name": "产品B", "model_number": "M-002"},
        ]
        deduped, skipped = service._deduplicate_products(products, "单位")
        assert len(deduped) == 1
        assert skipped == 1

    @patch("app.application.unit_products_import_app_service.get_db")
    def test_duplicate_by_name_spec(self, mock_get_db):
        """按名称+规格去重（无型号时）"""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [
            (None, "产品A", "100x200"),
        ]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        service = UnitProductsImportService.__new__(UnitProductsImportService)
        products = [
            {"product_name": "产品A", "model_number": None, "specification": "100x200"},
            {"product_name": "产品B", "model_number": None, "specification": "200x300"},
        ]
        deduped, skipped = service._deduplicate_products(products, "单位")
        assert len(deduped) == 1
        assert skipped == 1

    @patch("app.application.unit_products_import_app_service.get_db")
    def test_import_list_dedup(self, mock_get_db):
        """导入列表内部去重"""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        service = UnitProductsImportService.__new__(UnitProductsImportService)
        products = [
            {"product_name": "产品A", "model_number": "M-001"},
            {"product_name": "产品A重复", "model_number": "M-001"},
        ]
        deduped, skipped = service._deduplicate_products(products, "单位")
        assert len(deduped) == 1
        assert skipped == 1


# ---------------------------------------------------------------------------
# import_unit_products (integration-level with mocks)
# ---------------------------------------------------------------------------


class TestImportUnitProducts:
    """import_unit_products() — 完整导入流程"""

    def test_empty_saved_name(self, service):
        """saved_name 为空时返回错误"""
        result = service.import_unit_products("", "unit1")
        assert result["success"] is False

    def test_empty_unit_name(self, service):
        """unit_name 为空时返回错误"""
        result = service.import_unit_products("file.db", "")
        assert result["success"] is False

    def test_source_file_not_exists(self, service, tmp_path):
        """源文件不存在时返回错误"""
        with patch.object(service, "upload_dir", str(tmp_path)):
            result = service.import_unit_products("nonexistent.db", "单位")
        assert result["success"] is False
        assert "不存在" in result["message"]

    @patch("app.application.unit_products_import_app_service.get_db")
    @patch("app.application.unit_products_import_app_service.sqlite_conn")
    def test_no_products_in_source(self, mock_sqlite_conn, mock_get_db, service, tmp_path):
        """源数据库无产品数据"""
        db_path = str(tmp_path / "empty.db")
        _create_test_sqlite_db(db_path)

        # Mock sqlite_conn to return a real connection
        real_conn = sqlite3.connect(db_path)

        @contextmanager
        def _ctx(path):
            yield real_conn

        mock_sqlite_conn.side_effect = _ctx

        with patch.object(service, "upload_dir", str(tmp_path)):
            result = service.import_unit_products("empty.db", "单位")

        real_conn.close()
        assert result["success"] is True
        assert result["imported"] == 0

    @patch("app.application.unit_products_import_app_service.get_db")
    @patch("app.application.unit_products_import_app_service.sqlite_conn")
    def test_successful_import(self, mock_sqlite_conn, mock_get_db, service, tmp_path):
        """成功导入产品"""
        db_path = str(tmp_path / "products.db")
        _create_test_sqlite_db(
            db_path,
            [
                {"name": "产品A", "model_number": "M-001", "price": 10.0, "quantity": 100},
            ],
        )

        real_conn = sqlite3.connect(db_path)

        @contextmanager
        def _ctx(path):
            yield real_conn

        mock_sqlite_conn.side_effect = _ctx

        # Mock _ensure_unit_exists
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        with (
            patch.object(service, "upload_dir", str(tmp_path)),
            patch.object(service, "_ensure_unit_exists", return_value=True),
            patch.object(
                service,
                "_batch_import_products",
                return_value={"imported": 1, "message": "导入完成", "failed_products": []},
            ),
        ):
            result = service.import_unit_products("products.db", "单位")

        real_conn.close()
        assert result["success"] is True
        assert result["imported"] == 1

    @patch("app.application.unit_products_import_app_service.get_db")
    @patch("app.application.unit_products_import_app_service.sqlite_conn")
    def test_all_duplicates_skipped(self, mock_sqlite_conn, mock_get_db, service, tmp_path):
        """全部重复时跳过"""
        db_path = str(tmp_path / "dup.db")
        _create_test_sqlite_db(
            db_path,
            [
                {"name": "产品A", "model_number": "M-001", "price": 10.0, "quantity": 100},
            ],
        )

        real_conn = sqlite3.connect(db_path)

        @contextmanager
        def _ctx(path):
            yield real_conn

        mock_sqlite_conn.side_effect = _ctx

        # All products are duplicates
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [
            ("M-001", "产品A", ""),
        ]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        with (
            patch.object(service, "upload_dir", str(tmp_path)),
            patch.object(service, "_ensure_unit_exists", return_value=True),
        ):
            result = service.import_unit_products("dup.db", "单位", skip_duplicates=True)

        real_conn.close()
        assert result["success"] is True
        assert result["imported"] == 0
        assert result["skipped_duplicates"] == 1

    @patch("app.application.unit_products_import_app_service.sqlite_conn")
    def test_recoverable_error(self, mock_sqlite_conn, service, tmp_path):
        """导入过程抛出 RECOVERABLE_ERRORS"""
        db_path = str(tmp_path / "error.db")
        _create_test_sqlite_db(
            db_path,
            [
                {"name": "产品A", "model_number": "M-001", "price": 10.0, "quantity": 100},
            ],
        )

        @contextmanager
        def _ctx(path):
            raise RuntimeError("DB connection lost")

        mock_sqlite_conn.side_effect = _ctx

        with patch.object(service, "upload_dir", str(tmp_path)):
            result = service.import_unit_products("error.db", "单位")

        assert result["success"] is False
        assert "导入失败" in result["message"]

    @patch("app.application.unit_products_import_app_service.get_db")
    @patch("app.application.unit_products_import_app_service.sqlite_conn")
    def test_skip_duplicates_false(self, mock_sqlite_conn, mock_get_db, service, tmp_path):
        """skip_duplicates=False 时不跳过重复"""
        db_path = str(tmp_path / "nodup.db")
        _create_test_sqlite_db(
            db_path,
            [
                {"name": "产品A", "model_number": "M-001", "price": 10.0, "quantity": 100},
            ],
        )

        real_conn = sqlite3.connect(db_path)

        @contextmanager
        def _ctx(path):
            yield real_conn

        mock_sqlite_conn.side_effect = _ctx

        with (
            patch.object(service, "upload_dir", str(tmp_path)),
            patch.object(service, "_ensure_unit_exists", return_value=True),
            patch.object(
                service,
                "_batch_import_products",
                return_value={"imported": 1, "message": "导入完成", "failed_products": []},
            ),
        ):
            result = service.import_unit_products("nodup.db", "单位", skip_duplicates=False)

        real_conn.close()
        assert result["success"] is True
        assert result["skipped_duplicates"] == 0


# ---------------------------------------------------------------------------
# _batch_import_products
# ---------------------------------------------------------------------------


class TestBatchImportProducts:
    """_batch_import_products() — 批量导入产品"""

    def test_delegates_to_products_service(self):
        """委托给 products_service.batch_add_products"""
        service = UnitProductsImportService.__new__(UnitProductsImportService)
        mock_products_service = MagicMock()
        mock_products_service.batch_add_products.return_value = {
            "imported": 3,
            "message": "ok",
            "failed_products": [],
        }

        with patch(
            "app.bootstrap.get_products_service",
            return_value=mock_products_service,
        ):
            result = service._batch_import_products(
                [{"product_name": "产品1"}, {"product_name": "产品2"}]
            )

        mock_products_service.batch_add_products.assert_called_once()
        assert result["imported"] == 3


# ---------------------------------------------------------------------------
# get_unit_products_import_app_service
# ---------------------------------------------------------------------------


class TestGetService:
    """get_unit_products_import_app_service() — 获取服务单例"""

    def test_returns_service_instance(self):
        """返回 UnitProductsImportService 实例"""
        mock_registry = MagicMock()
        mock_registry.unit_products_import_application_service = MagicMock(
            spec=UnitProductsImportService
        )

        with patch(
            "app.di.registry.get_service_registry",
            return_value=mock_registry,
        ):
            from app.application.unit_products_import_app_service import (
                get_unit_products_import_app_service,
            )

            result = get_unit_products_import_app_service()
        assert result is not None
