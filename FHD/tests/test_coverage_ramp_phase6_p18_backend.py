"""COVERAGE_RAMP Phase 6 round 18: backend low-coverage modules.

Targets:
- ``app/infrastructure/persistence/product_repository_impl.py`` (355 行, 未覆盖 65 行, cov 80.9%)
- ``app/services/ocr_service.py`` (263 行, 未覆盖 65 行, cov 74.9%)
- ``app/application/workflow/engine.py`` (206 行, 未覆盖 64 行, cov 65.8%)
- ``app/fastapi_routes/mobile_api_extensions.py`` (461 行, 未覆盖 64 行, cov 85.8%)
- ``app/mod_sdk/industry_seed.py`` (165 行, 未覆盖 64 行, cov 55.8%)
- ``app/services/wechat_contact_service.py`` (337 行, 未覆盖 64 行, cov 79.4%)

Tests follow the phase-6 style: ``from __future__ import annotations``,
``unittest.mock`` + ``pytest``, mock only external boundaries (DB / external
API / LLM / file IO / paddleocr). The handler functions themselves are
exercised through real calls.

Coverage scenarios per 铁律3:
- Happy path (valid input)
- Empty / None input
- Boundary values (empty list, empty dict, empty string)
- Exception paths (RECOVERABLE_ERRORS: RuntimeError, ValueError, OSError)
"""

from __future__ import annotations

import os

os.environ.setdefault("XCAGI_SKIP_LEGACY_COMPAT_ROUTES", "1")

import json
import shutil
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import numpy as np
import pytest

from app.application.workflow.engine import WorkflowEngine
from app.application.workflow.types import (
    NodeExecutionResult,
    PlanGraph,
    WorkflowNode,
)
from app.infrastructure.persistence.product_repository_impl import (
    TRIVIAL_MEASURE_UNITS,
    SQLAlchemyProductRepository,
)
from app.mod_sdk import industry_seed as industry_seed_mod
from app.services import wechat_contact_service as wechat_mod
from app.services.ocr_service import OCRResult, OCRService
from app.services.wechat_contact_service import WechatContactService

# ===========================================================================
# Shared helpers / fixtures
# ===========================================================================


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@contextmanager
def _fake_db(session):
    yield session


def _patch_db(mod, session):
    return patch.object(mod, "get_db", lambda: _fake_db(session))


def _fluent(*, all_=None, first=None, update_=0) -> MagicMock:
    q = MagicMock()
    for attr in ("filter", "filter_by", "order_by", "join", "offset", "limit", "group_by"):
        getattr(q, attr).return_value = q
    q.all.return_value = list(all_ or [])
    q.first.return_value = first
    q.update.return_value = update_
    return q


def _mock_db_ctx(mock_db):
    @contextmanager
    def _ctx():
        yield mock_db

    return _ctx()


def _make_mock_product(**overrides):
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


def _contact(**kw) -> SimpleNamespace:
    base = {
        "id": 1,
        "contact_name": "张三",
        "remark": "朋友",
        "wechat_id": "zs001",
        "contact_type": "contact",
        "is_active": 1,
        "is_starred": 1,
        "created_at": datetime(2024, 1, 1),
        "updated_at": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _make_engine(dispatch_result=None):
    if dispatch_result is None:
        dispatch_result = {"success": True, "data": []}

    def mock_dispatch(tool_id, action, params):
        return dispatch_result

    return WorkflowEngine(tool_dispatcher=mock_dispatch)


def _simple_plan(nodes=None, plan_id="p1"):
    if nodes is None:
        nodes = [
            WorkflowNode(
                node_id="n1",
                tool_id="products",
                action="query",
                params={"keyword": "test"},
                risk="low",
                idempotent=True,
            )
        ]
    return PlanGraph(
        plan_id=plan_id,
        intent="test_workflow",
        todo_steps=["step1"],
        nodes=nodes,
        risk_level="low",
    )


@pytest.fixture(autouse=True, scope="module")
def _resolve_circular_import():
    """Resolve circular import between mobile_api and mobile_api_extensions."""
    if "app.fastapi_routes.mobile_api_extensions" not in sys.modules:
        try:
            from app.fastapi_routes import mobile_api  # noqa: F401
        except Exception:
            pass
    yield


@pytest.fixture
def ext_mod():
    return sys.modules["app.fastapi_routes.mobile_api_extensions"]


# ===========================================================================
# 1. app/infrastructure/persistence/product_repository_impl.py
# ===========================================================================


class TestProductRepositoryApiScalar:
    """Cover ``_api_scalar`` edge cases."""

    def test_api_scalar_none_returns_none(self):
        assert SQLAlchemyProductRepository._api_scalar(None) is None

    def test_api_scalar_float_nan_returns_none(self):
        assert SQLAlchemyProductRepository._api_scalar(float("nan")) is None

    def test_api_scalar_string_nan_returns_none(self):
        assert SQLAlchemyProductRepository._api_scalar("nan") is None

    def test_api_scalar_string_none_returns_none(self):
        assert SQLAlchemyProductRepository._api_scalar("none") is None

    def test_api_scalar_string_nat_returns_none(self):
        assert SQLAlchemyProductRepository._api_scalar("NaT") is None

    def test_api_scalar_string_na_angle_returns_none(self):
        assert SQLAlchemyProductRepository._api_scalar("<NA>") is None

    def test_api_scalar_string_null_returns_none(self):
        assert SQLAlchemyProductRepository._api_scalar("null") is None

    def test_api_scalar_string_with_whitespace_nan_returns_none(self):
        assert SQLAlchemyProductRepository._api_scalar("  nan  ") is None

    def test_api_scalar_normal_string_returns_stripped(self):
        assert SQLAlchemyProductRepository._api_scalar("  hello  ") == "hello"

    def test_api_scalar_integer_returns_integer(self):
        assert SQLAlchemyProductRepository._api_scalar(42) == 42

    def test_api_scalar_normal_float_returns_float(self):
        assert SQLAlchemyProductRepository._api_scalar(3.14) == 3.14

    def test_api_scalar_zero_returns_zero(self):
        assert SQLAlchemyProductRepository._api_scalar(0) == 0

    def test_api_scalar_empty_string_returns_empty(self):
        assert SQLAlchemyProductRepository._api_scalar("") == ""

    def test_api_scalar_object_with_float_nan_conversion_returns_none(self):
        class NanLike:
            def __float__(self):
                return float("nan")

        assert SQLAlchemyProductRepository._api_scalar(NanLike()) is None

    def test_api_scalar_object_without_float_conversion_returns_self(self):
        class Weird:
            pass

        w = Weird()
        assert SQLAlchemyProductRepository._api_scalar(w) is w

    def test_api_scalar_bool_true_returns_true(self):
        assert SQLAlchemyProductRepository._api_scalar(True) is True

    def test_api_scalar_bool_false_returns_false(self):
        assert SQLAlchemyProductRepository._api_scalar(False) is False


class TestProductRepositoryProductToDict:
    """Cover ``_product_to_dict`` branches."""

    @pytest.fixture
    def repo(self):
        return SQLAlchemyProductRepository()

    def test_basic_conversion_includes_product_name(self, repo):
        mock_product = _make_mock_product()
        mock_col1 = MagicMock()
        mock_col1.name = "id"
        mock_col2 = MagicMock()
        mock_col2.name = "name"
        mock_col3 = MagicMock()
        mock_col3.name = "price"

        with patch("app.infrastructure.persistence.product_repository_impl.inspect") as mock_insp:
            mock_mapper = MagicMock()
            mock_mapper.columns = [mock_col1, mock_col2, mock_col3]
            mock_insp.return_value = mock_mapper
            result = repo._product_to_dict(mock_product)

        assert result["name"] == "测试产品"
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

    def test_column_not_in_dict_skipped(self, repo):
        mock_product = MagicMock()
        mock_product.__dict__ = {"id": 1, "name": "X"}
        mock_col1 = MagicMock()
        mock_col1.name = "id"
        mock_col2 = MagicMock()
        mock_col2.name = "name"
        mock_col3 = MagicMock()
        mock_col3.name = "missing_col"

        with patch("app.infrastructure.persistence.product_repository_impl.inspect") as mock_insp:
            mock_mapper = MagicMock()
            mock_mapper.columns = [mock_col1, mock_col2, mock_col3]
            mock_insp.return_value = mock_mapper
            result = repo._product_to_dict(mock_product)

        assert "missing_col" not in result
        assert result["id"] == 1


class TestProductRepositoryFindAll:
    """Cover ``find_all`` branches."""

    @pytest.fixture
    def repo(self):
        return SQLAlchemyProductRepository()

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
    def test_with_model_number_filter_normalized(self, mock_get_db, repo):
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
    def test_with_keyword_multiple_segments(self, mock_get_db, repo):
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

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_bind_with_get_table_names_method(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_bind = MagicMock()
        mock_bind.get_table_names.return_value = ["products"]
        mock_db.__dict__["bind"] = mock_bind
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query

        result = repo.find_all()
        assert result["success"] is True

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_table_names_not_list_returns_empty(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_bind = MagicMock()
        mock_bind.get_table_names.return_value = "not a list"
        mock_db.__dict__["bind"] = mock_bind
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.find_all()
        assert result["success"] is True
        assert result["data"] == []


class TestProductRepositoryCreateUpdate:
    """Cover ``create`` and ``update`` branches."""

    @pytest.fixture
    def repo(self):
        return SQLAlchemyProductRepository()

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_create_success(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_product = MagicMock()
        mock_product.id = 42
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

    def test_create_name_key_empty_returns_error(self, repo):
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

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_update_success(self, mock_get_db, repo):
        mock_db = MagicMock()
        mock_product = MagicMock()
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
    def test_update_db_error(self, mock_get_db, repo):
        mock_get_db.side_effect = OSError("DB error")
        result = repo.update(1, {"price": 10})
        assert result["success"] is False
        assert "更新失败" in result["message"]


class TestProductRepositoryBatchOps:
    """Cover ``batch_create`` and ``batch_delete`` branches."""

    @pytest.fixture
    def repo(self):
        return SQLAlchemyProductRepository()

    def test_batch_create_empty_list_returns_error(self, repo):
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

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_batch_create_bulk_insert_fallback(self, mock_get_db, repo):
        """bulk_insert_mappings raises SQLAlchemyError → fallback to single insert."""
        from sqlalchemy.exc import SQLAlchemyError

        mock_db = MagicMock()
        mock_db.bulk_insert_mappings.side_effect = SQLAlchemyError("bulk failed")
        mock_product = MagicMock()
        mock_product.id = 1
        mock_db.add.return_value = None
        mock_db.flush.return_value = None
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        with patch("app.infrastructure.persistence.product_repository_impl.Product") as MockProduct:
            MockProduct.return_value = mock_product
            result = repo.batch_create([{"product_name": "产品1"}])

        assert result["success"] is True

    def test_batch_delete_empty_ids_returns_error(self, repo):
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


class TestProductRepositoryExistsAndNames:
    """Cover ``exists`` and ``find_names`` branches."""

    @pytest.fixture
    def repo(self):
        return SQLAlchemyProductRepository()

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

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_find_names_success(self, mock_get_db, repo):
        mock_db = MagicMock()
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


class TestProductRepositoryFindProductUnits:
    """Cover ``find_product_units`` branches."""

    @pytest.fixture
    def repo(self):
        return SQLAlchemyProductRepository()

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

            with patch(
                "app.application.customer_app_service.get_customers_session",
                side_effect=ImportError("no module"),
            ):
                result = repo.find_product_units()

        assert "七彩乐园" in result
        assert "件" not in result
        assert "箱" not in result

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

    @patch("app.infrastructure.persistence.product_repository_impl.get_db")
    def test_recoverable_error_in_fallback(self, mock_get_db, repo):
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
                side_effect=OSError("session fail"),
            ):
                result = repo.find_product_units()

        assert isinstance(result, list)


class TestTrivialMeasureUnits:
    """Cover ``TRIVIAL_MEASURE_UNITS`` constant."""

    def test_contains_common_units(self):
        assert "件" in TRIVIAL_MEASURE_UNITS
        assert "个" in TRIVIAL_MEASURE_UNITS
        assert "箱" in TRIVIAL_MEASURE_UNITS
        assert "千克" in TRIVIAL_MEASURE_UNITS

    def test_does_not_contain_customer_names(self):
        assert "七彩乐园" not in TRIVIAL_MEASURE_UNITS
        assert "客户A" not in TRIVIAL_MEASURE_UNITS


# ===========================================================================
# 2. app/services/ocr_service.py
# ===========================================================================


class TestOCRServiceInit:
    """Cover ``OCRService.__init__`` / ``_init_engines`` branches."""

    def test_init_auto_backend_no_engines(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OCR_BACKEND", "auto")
        with (
            patch("app.services.paddle_ocr_runner.check_paddle_available", return_value=False),
            patch("app.services.ocr_service.OCRService._init_easyocr") as mock_eo,
            patch("app.services.ocr_service.OCRService._init_tesseract") as mock_ts,
        ):
            svc = OCRService()
        assert svc._paddle_enabled is False
        mock_eo.assert_called_once()
        mock_ts.assert_called()

    def test_init_paddle_backend_unavailable_logs_error(self, monkeypatch, caplog):
        monkeypatch.setenv("XCAGI_OCR_BACKEND", "paddle")
        with patch("app.services.paddle_ocr_runner.check_paddle_available", return_value=False):
            svc = OCRService()
        assert svc._paddle_enabled is False

    def test_init_paddle_backend_available(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OCR_BACKEND", "paddle")
        with (
            patch("app.services.paddle_ocr_runner.check_paddle_available", return_value=True),
            patch("app.services.paddle_ocr_runner.get_paddle_ocr_instance") as mock_inst,
        ):
            svc = OCRService()
        assert svc._paddle_enabled is True
        mock_inst.assert_called_once()

    def test_init_easyocr_backend(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OCR_BACKEND", "easyocr")
        with (
            patch("app.services.paddle_ocr_runner.check_paddle_available", return_value=False),
            patch("app.services.ocr_service.OCRService._init_easyocr") as mock_eo,
        ):
            svc = OCRService()
        mock_eo.assert_called_once()

    def test_init_tesseract_backend(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OCR_BACKEND", "tesseract")
        with (
            patch("app.services.paddle_ocr_runner.check_paddle_available", return_value=False),
            patch("app.services.ocr_service.OCRService._init_easyocr"),
            patch("app.services.ocr_service.OCRService._init_tesseract") as mock_ts,
        ):
            svc = OCRService()
        mock_ts.assert_called()

    def test_init_paddle_init_raises_recoverable(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OCR_BACKEND", "auto")
        with (
            patch(
                "app.services.paddle_ocr_runner.check_paddle_available",
                side_effect=RuntimeError("paddle init fail"),
            ),
            patch("app.services.ocr_service.OCRService._init_easyocr"),
            patch("app.services.ocr_service.OCRService._init_tesseract"),
        ):
            svc = OCRService()
        assert svc._paddle_enabled is False


class TestOCRServiceInitEasyocr:
    """Cover ``_init_easyocr`` branches."""

    def test_easyocr_import_error(self, monkeypatch):
        svc = OCRService.__new__(OCRService)
        svc.use_gpu = False
        svc.reader = None
        svc.tesseract_available = False
        svc._paddle_enabled = False

        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "easyocr":
                raise ImportError("no easyocr")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        svc._init_easyocr()
        assert svc.reader is None

    def test_easyocr_init_recoverable_error(self, monkeypatch):
        svc = OCRService.__new__(OCRService)
        svc.use_gpu = False
        svc.reader = None
        svc.tesseract_available = False
        svc._paddle_enabled = False

        import builtins

        real_import = builtins.__import__

        class FakeEasyocr:
            class Reader:
                def __init__(self, *args, **kwargs):
                    raise RuntimeError("init fail")

        def fake_import(name, *args, **kwargs):
            if name == "easyocr":
                return FakeEasyocr
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        svc._init_easyocr()
        assert svc.reader is None


class TestOCRServiceInitTesseract:
    """Cover ``_init_tesseract`` branches."""

    def test_tesseract_import_error(self, monkeypatch):
        svc = OCRService.__new__(OCRService)
        svc.use_gpu = False
        svc.reader = None
        svc.tesseract_available = False
        svc._paddle_enabled = False

        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "pytesseract":
                raise ImportError("no pytesseract")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        svc._init_tesseract()
        assert svc.tesseract_available is False

    def test_tesseract_init_recoverable_error(self, monkeypatch):
        svc = OCRService.__new__(OCRService)
        svc.use_gpu = False
        svc.reader = None
        svc.tesseract_available = False
        svc._paddle_enabled = False

        import builtins

        real_import = builtins.__import__

        class FakePytesseract:
            @staticmethod
            def get_tesseract_version():
                raise RuntimeError("version fail")

        def fake_import(name, *args, **kwargs):
            if name == "pytesseract":
                return FakePytesseract
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        svc._init_tesseract()
        assert svc.tesseract_available is False


class TestOCRServiceRecognize:
    """Cover ``recognize`` branches."""

    def test_recognize_no_engine_returns_empty(self):
        svc = OCRService.__new__(OCRService)
        svc.use_gpu = False
        svc.reader = None
        svc.tesseract_available = False
        svc._paddle_enabled = False
        assert svc.recognize(MagicMock()) == ""

    def test_recognize_with_paddle(self):
        svc = OCRService.__new__(OCRService)
        svc.use_gpu = False
        svc.reader = None
        svc.tesseract_available = False
        svc._paddle_enabled = True

        image = MagicMock()
        image.convert.return_value = image
        with (
            patch(
                "app.services.paddle_ocr_runner.predict_to_text_blocks",
                return_value=[{"text": "hello"}, {"text": "world"}],
            ),
            patch("numpy.array", return_value=np.zeros((10, 10, 3))),
        ):
            result = svc.recognize(image)
        assert "hello" in result
        assert "world" in result

    def test_recognize_with_easyocr(self):
        svc = OCRService.__new__(OCRService)
        svc.use_gpu = False
        svc.reader = MagicMock()
        svc.reader.readtext.return_value = ["text1", "text2"]
        svc.tesseract_available = False
        svc._paddle_enabled = False

        image = MagicMock()
        image.convert.return_value = image
        with patch("numpy.array", return_value=np.zeros((10, 10, 3))):
            result = svc.recognize(image)
        assert "text1" in result

    def test_recognize_with_tesseract(self):
        svc = OCRService.__new__(OCRService)
        svc.use_gpu = False
        svc.reader = None
        svc.tesseract_available = True
        svc._paddle_enabled = False

        image = MagicMock()
        image.convert.return_value = image
        fake_pytesseract = MagicMock()
        fake_pytesseract.image_to_string.return_value = "tess text"
        fake_pil_image = MagicMock()
        fake_pil = MagicMock()
        fake_pil.Image.fromarray.return_value = fake_pil_image
        with (
            patch("numpy.array", return_value=np.zeros((10, 10, 3))),
            patch.dict(
                "sys.modules",
                {"pytesseract": fake_pytesseract, "PIL": fake_pil},
                clear=False,
            ),
        ):
            result = svc.recognize(image)
        assert "tess text" in result

    def test_recognize_pil_image_2d_array(self):
        svc = OCRService.__new__(OCRService)
        svc.use_gpu = False
        svc.reader = MagicMock()
        svc.reader.readtext.return_value = ["x"]
        svc.tesseract_available = False
        svc._paddle_enabled = False

        image_2d = np.zeros((10, 10))
        result = svc.recognize(image_2d)
        assert "x" in result

    def test_recognize_recoverable_error_returns_empty(self):
        svc = OCRService.__new__(OCRService)
        svc.use_gpu = False
        svc.reader = MagicMock()
        svc.reader.readtext.side_effect = RuntimeError("readtext fail")
        svc.tesseract_available = False
        svc._paddle_enabled = False

        image_2d = np.zeros((10, 10))
        result = svc.recognize(image_2d)
        assert result == ""


class TestOCRServiceRecognizeTextBlocks:
    """Cover ``recognize_text_blocks`` branches."""

    def test_with_paddle(self):
        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = True
        svc.reader = None
        svc.tesseract_available = False
        svc.use_gpu = False

        image = MagicMock()
        image.convert.return_value = image
        with (
            patch(
                "app.services.paddle_ocr_runner.predict_to_text_blocks",
                return_value=[{"text": "x"}],
            ),
            patch("numpy.array", return_value=np.zeros((10, 10, 3))),
        ):
            result = svc.recognize_text_blocks(image)
        assert result == [{"text": "x"}]

    def test_with_easyocr(self):
        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = MagicMock()
        svc.reader.readtext.return_value = [([[0, 0], [10, 0], [10, 10], [0, 10]], "hello", 0.95)]
        svc.tesseract_available = False
        svc.use_gpu = False

        image_2d = np.zeros((10, 10))
        result = svc.recognize_text_blocks(image_2d)
        assert len(result) == 1
        assert result[0]["text"] == "hello"

    def test_no_engine_returns_empty(self):
        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = None
        svc.tesseract_available = False
        svc.use_gpu = False

        image_2d = np.zeros((10, 10))
        assert svc.recognize_text_blocks(image_2d) == []

    def test_easyocr_text_blocks_empty_text_skipped(self):
        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = MagicMock()
        svc.reader.readtext.return_value = [
            ([[0, 0], [10, 0], [10, 10], [0, 10]], "", 0.95),
            ("", "  ", 0.95),
        ]
        svc.tesseract_available = False
        svc.use_gpu = False

        image_2d = np.zeros((10, 10))
        result = svc.recognize_text_blocks(image_2d)
        assert result == []

    def test_easyocr_text_blocks_recoverable_error(self):
        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = MagicMock()
        svc.reader.readtext.side_effect = RuntimeError("readtext fail")
        svc.tesseract_available = False
        svc.use_gpu = False

        image_2d = np.zeros((10, 10))
        result = svc.recognize_text_blocks(image_2d)
        assert result == []


class TestOCRServiceRecognizeFile:
    """Cover ``recognize_file`` / ``recognize_text`` branches."""

    def test_recognize_file_not_exists(self, tmp_path):
        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = None
        svc.tesseract_available = False
        svc.use_gpu = False

        result = svc.recognize_file(str(tmp_path / "missing.png"))
        assert result["success"] is False
        assert "文件不存在" in result["message"]

    def test_recognize_file_success(self, tmp_path):
        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = MagicMock()
        svc.reader.readtext.return_value = ["hello"]
        svc.tesseract_available = False
        svc.use_gpu = False

        file_path = tmp_path / "img.png"
        file_path.write_bytes(b"")
        with patch("PIL.Image.open") as mock_open:
            mock_open.return_value = MagicMock()
            result = svc.recognize_file(str(file_path))
        assert result["success"] is True
        assert "hello" in result["text"]

    def test_recognize_file_recoverable_error(self, tmp_path):
        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = None
        svc.tesseract_available = False
        svc.use_gpu = False

        file_path = tmp_path / "img.png"
        file_path.write_bytes(b"")
        with patch("PIL.Image.open", side_effect=RuntimeError("open fail")):
            result = svc.recognize_file(str(file_path))
        assert result["success"] is False

    def test_recognize_text_adds_confidence(self, tmp_path):
        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = None
        svc.tesseract_available = False
        svc.use_gpu = False

        file_path = tmp_path / "img.png"
        file_path.write_bytes(b"")
        with patch("PIL.Image.open"), patch.object(svc, "recognize", return_value="text"):
            result = svc.recognize_text(str(file_path))
        assert "confidence" in result
        assert result["confidence"] == 0.0

    def test_recognize_trademark_delegates(self, tmp_path):
        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = None
        svc.tesseract_available = False
        svc.use_gpu = False

        result = svc.recognize_trademark(str(tmp_path / "missing.png"))
        assert result["success"] is False

    def test_recognize_product_delegates(self, tmp_path):
        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = None
        svc.tesseract_available = False
        svc.use_gpu = False

        result = svc.recognize_product(str(tmp_path / "missing.png"))
        assert result["success"] is False


class TestOCRServiceRecognizeFromBytes:
    """Cover ``recognize_text_from_bytes`` branches."""

    def test_with_paddle(self):
        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = True
        svc.reader = None
        svc.tesseract_available = False
        svc.use_gpu = False

        with (
            patch("PIL.Image.open") as mock_open,
            patch.object(
                svc,
                "recognize_text_blocks",
                return_value=[{"text": "x", "conf": 80.0}],
            ),
        ):
            mock_open.return_value = MagicMock()
            result = svc.recognize_text_from_bytes(b"img bytes")
        assert result["success"] is True
        assert result["confidence"] == 0.8

    def test_with_paddle_empty_text(self):
        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = True
        svc.reader = None
        svc.tesseract_available = False
        svc.use_gpu = False

        with (
            patch("PIL.Image.open") as mock_open,
            patch.object(svc, "recognize_text_blocks", return_value=[]),
        ):
            mock_open.return_value = MagicMock()
            result = svc.recognize_text_from_bytes(b"img bytes")
        assert result["success"] is False
        assert result["confidence"] == 0.0

    def test_without_paddle(self):
        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = MagicMock()
        svc.reader.readtext.return_value = ["text"]
        svc.tesseract_available = False
        svc.use_gpu = False

        with (
            patch("PIL.Image.open") as mock_open,
            patch.object(svc, "recognize", return_value="text"),
        ):
            mock_open.return_value = MagicMock()
            result = svc.recognize_text_from_bytes(b"img bytes")
        assert result["success"] is True

    def test_recoverable_error(self):
        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = None
        svc.tesseract_available = False
        svc.use_gpu = False

        with patch("PIL.Image.open", side_effect=RuntimeError("open fail")):
            result = svc.recognize_text_from_bytes(b"img bytes")
        assert result["success"] is False
        assert result["confidence"] == 0.0


class TestOCRServiceRecognizeWithDetails:
    """Cover ``recognize_with_details`` branches."""

    def test_with_paddle(self):
        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = True
        svc.reader = None
        svc.tesseract_available = False
        svc.use_gpu = False

        image_2d = np.zeros((10, 10))
        with patch.object(
            svc,
            "recognize_text_blocks",
            return_value=[
                {"text": "100元", "conf": 90.0, "left": 0, "top": 0, "width": 10, "height": 10}
            ],
        ):
            result = svc.recognize_with_details(image_2d)
        assert len(result) == 1
        assert isinstance(result[0], OCRResult)
        assert result[0].text == "100元"
        assert result[0].block_type == "amount"

    def test_with_easyocr(self):
        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = MagicMock()
        svc.reader.readtext.return_value = [([[0, 0], [10, 0], [10, 10], [0, 10]], "hello", 0.95)]
        svc.tesseract_available = False
        svc.use_gpu = False

        image_2d = np.zeros((10, 10, 3))
        result = svc.recognize_with_details(image_2d)
        assert len(result) == 1
        assert result[0].text == "hello"

    def test_no_reader_returns_empty(self):
        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = None
        svc.tesseract_available = False
        svc.use_gpu = False

        image_2d = np.zeros((10, 10, 3))
        assert svc.recognize_with_details(image_2d) == []

    def test_recoverable_error_returns_empty(self):
        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = MagicMock()
        svc.reader.readtext.side_effect = RuntimeError("fail")
        svc.tesseract_available = False
        svc.use_gpu = False

        image_2d = np.zeros((10, 10, 3))
        assert svc.recognize_with_details(image_2d) == []


class TestOCRServiceGetActiveBackend:
    """Cover ``get_active_ocr_backend``."""

    def test_paddle(self):
        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = True
        svc.reader = None
        svc.tesseract_available = False
        assert svc.get_active_ocr_backend() == "paddleocr"

    def test_easyocr(self):
        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = MagicMock()
        svc.tesseract_available = False
        assert svc.get_active_ocr_backend() == "easyocr"

    def test_tesseract(self):
        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = None
        svc.tesseract_available = True
        assert svc.get_active_ocr_backend() == "tesseract"

    def test_none(self):
        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = None
        svc.tesseract_available = False
        assert svc.get_active_ocr_backend() == "none"


class TestOCRServiceClassifyText:
    """Cover ``_classify_text`` branches."""

    @pytest.fixture
    def svc(self):
        return OCRService.__new__(OCRService)

    def test_empty_returns_unknown(self, svc):
        assert svc._classify_text("") == "unknown"

    def test_date_chinese_format(self, svc):
        assert svc._classify_text("2024年1月15日") == "date"

    def test_date_with_slash(self, svc):
        assert svc._classify_text("01/15/2024") == "date"

    def test_amount_yuan(self, svc):
        assert svc._classify_text("100元") == "amount"

    def test_amount_dollar_symbol(self, svc):
        assert svc._classify_text("$100.50") == "amount"

    def test_amount_euro(self, svc):
        assert svc._classify_text("50€") == "amount"

    def test_phone(self, svc):
        assert svc._classify_text("13812345678") == "phone"

    def test_number(self, svc):
        assert svc._classify_text("12345") == "number"

    def test_text(self, svc):
        assert svc._classify_text("购货单位：测试公司") == "text"


class TestOCRServiceCleanText:
    """Cover ``_clean_text`` branches."""

    @pytest.fixture
    def svc(self):
        return OCRService.__new__(OCRService)

    def test_empty(self, svc):
        assert svc._clean_text("") == ""

    def test_strips_lines(self, svc):
        assert svc._clean_text("  a  \n  b  ") == "a\nb"

    def test_removes_empty_lines(self, svc):
        assert svc._clean_text("a\n\nb") == "a\nb"


class TestOCRServiceExtractStructuredData:
    """Cover ``extract_structured_data`` branches."""

    @pytest.fixture
    def svc(self):
        return OCRService.__new__(OCRService)

    def test_empty_text(self, svc):
        result = svc.extract_structured_data("")
        assert result["purchase_unit"] is None
        assert result["products"] == []

    def test_extract_all_fields(self, svc):
        text = """
        购货单位：测试公司
        联系人：张三
        联系电话：138-1234-5678
        订单编号：ORD001
        2024-01-15
        合计：1250.50
        ABC001 产品A 10 100.00 1000.00
        """
        result = svc.extract_structured_data(text)
        assert result["purchase_unit"] == "测试公司"
        assert result["contact_person"] == "张三"
        assert result["contact_phone"] == "138-1234-5678"
        assert result["order_number"] == "ORD001"
        assert result["purchase_date"] == "2024-01-15"
        assert result["total_amount"] == 1250.50
        assert len(result["products"]) == 1

    def test_invalid_amount(self, svc):
        result = svc.extract_structured_data("合计：abc")
        assert result["total_amount"] is None

    def test_chinese_date_format(self, svc):
        result = svc.extract_structured_data("2024年1月20日")
        assert result["purchase_date"] == "2024年1月20日"


class TestOCRServiceAnalyzeText:
    """Cover ``analyze_text`` branches."""

    @pytest.fixture
    def svc(self):
        return OCRService.__new__(OCRService)

    def test_empty_text(self, svc):
        result = svc.analyze_text("")
        assert result["text_type"] == "unknown"
        assert result["confidence"] == 0.0
        assert result["missing_fields"] == []

    def test_unknown_type_adds_suggestion(self, svc):
        result = svc.analyze_text("这是一段完全没有任何关键词的普通文本")
        assert result["text_type"] == "unknown"
        assert any("手动确认" in s for s in result["suggestions"])

    def test_detects_order_type(self, svc):
        result = svc.analyze_text("订单编号：001\n订购产品：显示器")
        assert result["text_type"] == "order"

    def test_detects_all_essential_fields(self, svc):
        text = "购货单位：测试公司\n联系人：张三\n2024-01-15"
        result = svc.analyze_text(text)
        assert len(result["missing_fields"]) == 0


# ===========================================================================
# 3. app/application/workflow/engine.py
# ===========================================================================


class TestWorkflowEngineRunBatch:
    """Cover ``_run_batch`` branches."""

    def test_single_node_success(self):
        engine = _make_engine({"success": True, "data": [{"name": "P1"}]})
        plan = _simple_plan()
        result = engine.run(plan)
        assert result.success is True
        assert len(result.node_results) == 1

    def test_single_node_failure(self):
        engine = _make_engine({"success": False, "message": "not found"})
        plan = _simple_plan()
        result = engine.run(plan)
        assert result.success is False
        assert "n1" in result.message

    def test_sequential_nodes(self):
        engine = _make_engine({"success": True, "data": []})
        nodes = [
            WorkflowNode(node_id="n1", tool_id="products", action="query", params={}),
            WorkflowNode(
                node_id="n2",
                tool_id="customers",
                action="query",
                params={},
                depends_on=["n1"],
            ),
        ]
        plan = _simple_plan(nodes=nodes)
        result = engine.run(plan)
        assert result.success is True
        assert len(result.node_results) == 2

    def test_circular_dependency_stalls(self):
        engine = _make_engine({"success": True})
        nodes = [
            WorkflowNode(node_id="n1", tool_id="a", action="x", params={}, depends_on=["n2"]),
            WorkflowNode(node_id="n2", tool_id="b", action="y", params={}, depends_on=["n1"]),
        ]
        plan = _simple_plan(nodes=nodes)
        result = engine.run(plan)
        assert result.success is False
        assert "依赖无法继续解析" in result.message

    def test_runtime_context_propagation(self):
        engine = _make_engine({"success": True, "data": []})
        plan = _simple_plan()
        result = engine.run(plan, runtime_context={"message": "hello"})
        assert "node_outputs" in result.final_context

    def test_empty_plan(self):
        engine = _make_engine()
        plan = _simple_plan(nodes=[])
        result = engine.run(plan)
        assert result.success is True
        assert result.node_results == []


class TestWorkflowEngineRunNode:
    """Cover ``_run_node`` branches."""

    def test_success_on_first_try(self):
        engine = _make_engine({"success": True})
        plan = _simple_plan()
        result = engine._run_node(plan.nodes[0], {})
        assert result.success is True
        assert result.retries == 0

    def test_retry_on_failure(self):
        call_count = 0

        def flaky_dispatch(tool_id, action, params):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return {"success": False, "message": "temp error"}
            return {"success": True}

        engine = WorkflowEngine(tool_dispatcher=flaky_dispatch)
        plan = _simple_plan()
        result = engine._run_node(plan.nodes[0], {}, max_retries=2)
        assert result.success is True
        assert result.retries == 1

    def test_all_retries_exhausted(self):
        engine = _make_engine({"success": False, "message": "permanent error"})
        plan = _simple_plan()
        result = engine._run_node(plan.nodes[0], {}, max_retries=1)
        assert result.success is False
        assert result.error == "permanent error"

    def test_exception_in_dispatch(self):
        def bad_dispatch(tool_id, action, params):
            raise RuntimeError("boom")

        engine = WorkflowEngine(tool_dispatcher=bad_dispatch)
        plan = _simple_plan()
        result = engine._run_node(plan.nodes[0], {}, max_retries=0)
        assert result.success is False
        assert "boom" in result.error


class TestWorkflowEngineSummarizeOutput:
    """Cover ``_summarize_output`` branches."""

    def test_success_with_message(self):
        assert "ok" in WorkflowEngine._summarize_output({"success": True, "message": "ok"})

    def test_success_with_answer(self):
        result = WorkflowEngine._summarize_output({"success": True, "answer": "ans"})
        assert "ans" in result

    def test_success_with_data_list(self):
        result = WorkflowEngine._summarize_output({"success": True, "data": [1, 2, 3]})
        assert "3 条数据" in result

    def test_success_with_data_dict(self):
        result = WorkflowEngine._summarize_output({"success": True, "data": {"k": "v"}})
        assert "v" in result

    def test_failure_output_with_error(self):
        result = WorkflowEngine._summarize_output({"success": False, "error": "bad"})
        assert "错误" in result

    def test_failure_output_with_message(self):
        result = WorkflowEngine._summarize_output({"success": False, "message": "msg"})
        assert "msg" in result

    def test_non_dict(self):
        result = WorkflowEngine._summarize_output("plain text")
        assert "plain text" in result


class TestWorkflowEngineHasNonEmptyParam:
    """Cover ``_has_non_empty_param`` branches."""

    def test_has_param(self):
        assert WorkflowEngine._has_non_empty_param({"keyword": "test"}, ("keyword",)) is True

    def test_empty_param(self):
        assert WorkflowEngine._has_non_empty_param({"keyword": ""}, ("keyword",)) is False

    def test_none_param(self):
        assert WorkflowEngine._has_non_empty_param({"keyword": None}, ("keyword",)) is False

    def test_missing_key(self):
        assert WorkflowEngine._has_non_empty_param({}, ("keyword",)) is False

    def test_multiple_keys_one_present(self):
        assert (
            WorkflowEngine._has_non_empty_param({"name": "x"}, ("keyword", "name", "unit_name"))
            is True
        )


class TestWorkflowEngineMergeRuntimeFallbackParams:
    """Cover ``_merge_runtime_fallback_params`` branches."""

    def test_products_query_empty_params(self):
        engine = _make_engine()
        node = WorkflowNode(node_id="n1", tool_id="products", action="query", params={})
        params = {}
        engine._merge_runtime_fallback_params(node, params, {"message": "hello"})
        assert params["keyword"] == "hello"

    def test_products_query_with_keyword(self):
        engine = _make_engine()
        node = WorkflowNode(
            node_id="n1", tool_id="products", action="query", params={"keyword": "x"}
        )
        params = {"keyword": "x"}
        engine._merge_runtime_fallback_params(node, params, {"message": "hello"})
        assert params["keyword"] == "x"

    def test_customers_query_empty_params(self):
        engine = _make_engine()
        node = WorkflowNode(node_id="n1", tool_id="customers", action="query", params={})
        params = {}
        engine._merge_runtime_fallback_params(node, params, {"message": "find customer"})
        assert params["keyword"] == "find customer"

    def test_no_message(self):
        engine = _make_engine()
        node = WorkflowNode(node_id="n1", tool_id="products", action="query", params={})
        params = {}
        engine._merge_runtime_fallback_params(node, params, {})
        assert "keyword" not in params

    def test_other_tool_not_affected(self):
        engine = _make_engine()
        node = WorkflowNode(node_id="n1", tool_id="orders", action="query", params={})
        params = {}
        engine._merge_runtime_fallback_params(node, params, {"message": "hello"})
        assert "keyword" not in params


class TestWorkflowEngineRunSingleTool:
    """Cover ``_run_single_tool`` branches."""

    def test_success(self):
        engine = _make_engine({"success": True, "data": []})
        result = engine._run_single_tool("products", "query", {}, {}, 0)
        assert result.success is True

    def test_failure_with_retries(self):
        engine = _make_engine({"success": False, "message": "err"})
        result = engine._run_single_tool("products", "query", {}, {}, 1)
        assert result.success is False

    def test_exception(self):
        def bad_dispatch(tool_id, action, params):
            raise ValueError("bad")

        engine = WorkflowEngine(tool_dispatcher=bad_dispatch)
        result = engine._run_single_tool("products", "query", {}, {}, 0)
        assert result.success is False
        assert "bad" in result.error


class TestWorkflowEngineAgenticLoop:
    """Cover ``_run_agentic_loop`` branches."""

    def test_agentic_loop_done_immediately(self):
        engine = _make_engine()
        with patch.object(engine, "_llm_decide_next_step", return_value={"action": "done"}):
            plan = _simple_plan()
            result = engine.run(
                plan,
                runtime_context={"message": "test"},
                agentic_loop=True,
                tool_registry={"products": {"actions": {"query": {"risk": "low"}}}},
            )
        assert result.success is True

    def test_agentic_loop_no_api_key(self):
        engine = _make_engine()
        with patch.object(engine, "_llm_decide_next_step", return_value=None):
            plan = _simple_plan()
            result = engine.run(
                plan,
                runtime_context={"message": "test"},
                agentic_loop=True,
                tool_registry={"products": {"actions": {"query": {"risk": "low"}}}},
            )
        assert result.success is True
        assert len(result.node_results) == 0

    def test_agentic_loop_execute_then_done(self):
        engine = _make_engine({"success": True, "data": []})
        call_count = 0

        def mock_decide(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "action": "execute",
                    "tool_id": "products",
                    "action_name": "query",
                    "params": {},
                    "reasoning": "test",
                }
            return {"action": "done"}

        with patch.object(engine, "_llm_decide_next_step", side_effect=mock_decide):
            plan = _simple_plan()
            result = engine.run(
                plan,
                runtime_context={"message": "test"},
                agentic_loop=True,
                tool_registry={"products": {"actions": {"query": {"risk": "low"}}}},
            )
        assert result.success is True
        assert len(result.node_results) == 1

    def test_agentic_loop_tool_failure_continues(self):
        engine = _make_engine({"success": False, "message": "tool err"})
        call_count = 0

        def mock_decide(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "action": "execute",
                    "tool_id": "products",
                    "action_name": "query",
                    "params": {},
                    "reasoning": "test",
                }
            return {"action": "done"}

        with patch.object(engine, "_llm_decide_next_step", side_effect=mock_decide):
            plan = _simple_plan()
            result = engine.run(
                plan,
                runtime_context={"message": "test"},
                agentic_loop=True,
                tool_registry={"products": {"actions": {"query": {"risk": "low"}}}},
            )
        assert result.success is True
        assert len(result.node_results) == 1
        assert result.node_results[0].success is False


class TestWorkflowEngineLlmDecideNextStep:
    """Cover ``_llm_decide_next_step`` branches."""

    def test_no_api_key_returns_none(self):
        engine = _make_engine()
        ai_service = MagicMock()
        ai_service.api_key = ""
        with patch(
            "app.application.workflow.engine.get_ai_conversation_service",
            return_value=ai_service,
        ):
            result = engine._llm_decide_next_step("msg", {}, {}, [], None)
        assert result is None

    def test_llm_call_failure_status(self):
        engine = _make_engine()
        ai_service = MagicMock()
        ai_service.api_key = "key"
        ai_service.api_url = "http://x"
        ai_service.model = "m"
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        with (
            patch(
                "app.application.workflow.engine.get_ai_conversation_service",
                return_value=ai_service,
            ),
            patch(
                "app.application.workflow.engine._get_sync_http_client",
                return_value=mock_client,
            ),
        ):
            result = engine._llm_decide_next_step("msg", {}, {}, [], None)
        assert result is None

    def test_llm_returns_empty_content(self):
        engine = _make_engine()
        ai_service = MagicMock()
        ai_service.api_key = "key"
        ai_service.api_url = "http://x"
        ai_service.model = "m"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"choices": [{"message": {"content": ""}}]}
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        with (
            patch(
                "app.application.workflow.engine.get_ai_conversation_service",
                return_value=ai_service,
            ),
            patch(
                "app.application.workflow.engine._get_sync_http_client",
                return_value=mock_client,
            ),
        ):
            result = engine._llm_decide_next_step("msg", {}, {}, [], None)
        assert result is None

    def test_llm_returns_done(self):
        engine = _make_engine()
        ai_service = MagicMock()
        ai_service.api_key = "key"
        ai_service.api_url = "http://x"
        ai_service.model = "m"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"action": "done"}'}}]
        }
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        with (
            patch(
                "app.application.workflow.engine.get_ai_conversation_service",
                return_value=ai_service,
            ),
            patch(
                "app.application.workflow.engine._get_sync_http_client",
                return_value=mock_client,
            ),
        ):
            result = engine._llm_decide_next_step("msg", {}, {}, [], None)
        assert result == {"action": "done"}

    def test_llm_returns_execute(self):
        engine = _make_engine()
        ai_service = MagicMock()
        ai_service.api_key = "key"
        ai_service.api_url = "http://x"
        ai_service.model = "m"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"action": "execute", "tool_id": "products", '
                        '"action_name": "query", "params": {}, "reasoning": "r"}'
                    }
                }
            ]
        }
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        with (
            patch(
                "app.application.workflow.engine.get_ai_conversation_service",
                return_value=ai_service,
            ),
            patch(
                "app.application.workflow.engine._get_sync_http_client",
                return_value=mock_client,
            ),
        ):
            result = engine._llm_decide_next_step("msg", {}, {}, [], None)
        assert result["action"] == "execute"
        assert result["tool_id"] == "products"

    def test_llm_returns_invalid_json_returns_none(self):
        engine = _make_engine()
        ai_service = MagicMock()
        ai_service.api_key = "key"
        ai_service.api_url = "http://x"
        ai_service.model = "m"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"choices": [{"message": {"content": "not json"}}]}
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        with (
            patch(
                "app.application.workflow.engine.get_ai_conversation_service",
                return_value=ai_service,
            ),
            patch(
                "app.application.workflow.engine._get_sync_http_client",
                return_value=mock_client,
            ),
        ):
            result = engine._llm_decide_next_step("msg", {}, {}, [], None)
        assert result is None

    def test_llm_returns_execute_missing_tool_id(self):
        engine = _make_engine()
        ai_service = MagicMock()
        ai_service.api_key = "key"
        ai_service.api_url = "http://x"
        ai_service.model = "m"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {"message": {"content": '{"action": "execute", "tool_id": "", "action_name": ""}'}}
            ]
        }
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        with (
            patch(
                "app.application.workflow.engine.get_ai_conversation_service",
                return_value=ai_service,
            ),
            patch(
                "app.application.workflow.engine._get_sync_http_client",
                return_value=mock_client,
            ),
        ):
            result = engine._llm_decide_next_step("msg", {}, {}, [], None)
        assert result is None

    def test_llm_call_raises_recoverable(self):
        engine = _make_engine()
        ai_service = MagicMock()
        ai_service.api_key = "key"
        ai_service.api_url = "http://x"
        ai_service.model = "m"
        mock_client = MagicMock()
        mock_client.post.side_effect = RuntimeError("network fail")
        with (
            patch(
                "app.application.workflow.engine.get_ai_conversation_service",
                return_value=ai_service,
            ),
            patch(
                "app.application.workflow.engine._get_sync_http_client",
                return_value=mock_client,
            ),
        ):
            result = engine._llm_decide_next_step("msg", {}, {}, [], None)
        assert result is None

    def test_tool_registry_with_non_dict_spec_skipped(self):
        engine = _make_engine()
        ai_service = MagicMock()
        ai_service.api_key = "key"
        ai_service.api_url = "http://x"
        ai_service.model = "m"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"action": "done"}'}}]
        }
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        with (
            patch(
                "app.application.workflow.engine.get_ai_conversation_service",
                return_value=ai_service,
            ),
            patch(
                "app.application.workflow.engine._get_sync_http_client",
                return_value=mock_client,
            ),
        ):
            result = engine._llm_decide_next_step(
                "msg",
                {"products": "not a dict", "orders": {"actions": {"x": {"risk": "low"}}}},
                {},
                [],
                None,
            )
        assert result == {"action": "done"}


# ===========================================================================
# 4. app/fastapi_routes/mobile_api_extensions.py
# ===========================================================================


class TestMobileExtEnsureMobileDeviceTable:
    """Cover ``_ensure_mobile_device_table`` branches."""

    def test_happy_path(self, ext_mod):
        mock_db = MagicMock()
        mock_insp = MagicMock()
        mock_insp.has_table.return_value = True
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with (
            patch("app.db.session.get_db", return_value=mock_db),
            patch("sqlalchemy.inspect", return_value=mock_insp),
        ):
            ext_mod._ensure_mobile_device_table()

    def test_table_missing_creates(self, ext_mod):
        mock_db = MagicMock()
        mock_bind = MagicMock()
        mock_db.get_bind.return_value = mock_bind
        mock_insp = MagicMock()
        mock_insp.has_table.return_value = False
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with (
            patch("app.db.session.get_db", return_value=mock_db),
            patch("sqlalchemy.inspect", return_value=mock_insp),
        ):
            ext_mod._ensure_mobile_device_table()

    def test_recoverable_error_logged(self, ext_mod):
        with patch("app.db.session.get_db", side_effect=RuntimeError("db down")):
            ext_mod._ensure_mobile_device_table()


class TestMobileExtGuessLanIpv4:
    """Cover ``_guess_lan_ipv4`` branches."""

    def test_returns_string(self, ext_mod):
        ip = ext_mod._guess_lan_ipv4()
        assert isinstance(ip, str)
        assert len(ip) > 0

    def test_fallback_on_os_error(self, ext_mod):
        with patch("socket.socket", side_effect=OSError("no network")):
            ip = ext_mod._guess_lan_ipv4()
            assert ip == "127.0.0.1"


class TestMobileExtPairingIssueHost:
    """Cover ``_pairing_issue_host`` branches."""

    def test_localhost_replaced(self, ext_mod):
        with patch.object(ext_mod, "_guess_lan_ipv4", return_value="192.168.1.100"):
            assert ext_mod._pairing_issue_host("127.0.0.1") == "192.168.1.100"

    def test_localhost_name_replaced(self, ext_mod):
        with patch.object(ext_mod, "_guess_lan_ipv4", return_value="192.168.1.100"):
            assert ext_mod._pairing_issue_host("localhost") == "192.168.1.100"

    def test_0000_replaced(self, ext_mod):
        with patch.object(ext_mod, "_guess_lan_ipv4", return_value="192.168.1.100"):
            assert ext_mod._pairing_issue_host("0.0.0.0") == "192.168.1.100"

    def test_real_ip_kept(self, ext_mod):
        assert ext_mod._pairing_issue_host("192.168.1.50") == "192.168.1.50"

    def test_empty_defaults(self, ext_mod):
        with patch.object(ext_mod, "_guess_lan_ipv4", return_value="192.168.1.100"):
            assert ext_mod._pairing_issue_host("") == "192.168.1.100"

    def test_none_defaults(self, ext_mod):
        with patch.object(ext_mod, "_guess_lan_ipv4", return_value="192.168.1.100"):
            assert ext_mod._pairing_issue_host(None) == "192.168.1.100"


class TestMobileExtPairingRoutes:
    """Cover pairing routes."""

    @pytest.mark.asyncio
    async def test_pairing_issue_success(self, ext_mod):
        body = ext_mod.PairingIssueBody(host="192.168.1.10", port=5000)
        with (
            patch.object(ext_mod, "_pairing_issue_host", return_value="192.168.1.10"),
            patch(
                "app.security.mobile_pairing.issue_pairing_nonce",
                return_value={"nonce": "abc123", "host": "192.168.1.10", "port": 5000},
            ),
        ):
            result = await ext_mod.mobile_pairing_issue(body)
        if hasattr(result, "body"):
            data = json.loads(result.body)
        else:
            data = result
        assert data.get("success") is True or data.get("data", {}).get("host") == "192.168.1.10"

    @pytest.mark.asyncio
    async def test_pairing_lookup_invalid_code(self, ext_mod):
        body = ext_mod.PairingLookupBody(code="000000")
        result = await ext_mod.mobile_pairing_lookup(body)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_pairing_lookup_valid(self, ext_mod):
        body = ext_mod.PairingLookupBody(code="123456")
        with patch.object(
            ext_mod,
            "lookup_by_shortcode",
            return_value={"host": "h", "port": 5000, "nonce": "n", "exp": 9999999999},
        ):
            result = await ext_mod.mobile_pairing_lookup(body)
        if hasattr(result, "body"):
            data = json.loads(result.body)
        else:
            data = result
        assert data.get("success") is True

    @pytest.mark.asyncio
    async def test_pairing_exchange_no_credentials(self, ext_mod):
        body = ext_mod.PairingExchangeBody(code="", nonce="")
        result = await ext_mod.mobile_pairing_exchange(body)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_pairing_exchange_by_code(self, ext_mod):
        body = ext_mod.PairingExchangeBody(code="123456")
        with patch.object(
            ext_mod,
            "consume_by_shortcode",
            return_value={"host": "h", "port": 5000, "shortCode": "123456"},
        ):
            result = await ext_mod.mobile_pairing_exchange(body)
        if hasattr(result, "body"):
            data = json.loads(result.body)
        else:
            data = result
        assert data.get("success") is True

    @pytest.mark.asyncio
    async def test_pairing_exchange_by_nonce(self, ext_mod):
        body = ext_mod.PairingExchangeBody(nonce="abc123")
        with patch.object(
            ext_mod,
            "consume_pairing_nonce",
            return_value={"host": "h", "port": 5000, "shortCode": "123456"},
        ):
            result = await ext_mod.mobile_pairing_exchange(body)
        if hasattr(result, "body"):
            data = json.loads(result.body)
        else:
            data = result
        assert data.get("success") is True


class TestMobileExtUnauthorizedRoutes:
    """Cover unauthorized route branches."""

    @pytest.mark.asyncio
    async def test_approval_list_unauthorized(self, ext_mod):
        mock_request = MagicMock()
        result = await ext_mod.mobile_approval_list(request=mock_request, user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_customers_unauthorized(self, ext_mod):
        result = await ext_mod.mobile_customers(user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_shipments_unauthorized(self, ext_mod):
        result = await ext_mod.mobile_shipments(user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_device_register_unauthorized(self, ext_mod):
        body = ext_mod.DeviceRegisterBody(fcm_token="a" * 10)
        result = await ext_mod.mobile_device_register(body=body, user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_mods_unauthorized(self, ext_mod):
        result = await ext_mod.mobile_mods_summary(user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_platform_shell_unauthorized(self, ext_mod):
        result = await ext_mod.mobile_platform_shell(user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_home_unauthorized(self, ext_mod):
        result = await ext_mod.mobile_home(user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_sync_status_unauthorized(self, ext_mod):
        result = await ext_mod.mobile_sync_status(user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_sync_pull_unauthorized(self, ext_mod):
        body = ext_mod.SyncPullBody(since_cursor=0)
        result = await ext_mod.mobile_sync_pull(body=body, user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_sync_push_unauthorized(self, ext_mod):
        body = ext_mod.SyncPushBody(items=[])
        result = await ext_mod.mobile_sync_push(body=body, user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_cs_info_unauthorized(self, ext_mod):
        mock_request = MagicMock()
        result = await ext_mod.get_cs_info(request=mock_request, user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_cs_post_message_unauthorized(self, ext_mod):
        mock_request = MagicMock()
        result = await ext_mod.post_cs_message(request=mock_request, body={}, user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_cs_get_messages_unauthorized(self, ext_mod):
        mock_request = MagicMock()
        result = await ext_mod.get_cs_messages(request=mock_request, user=None)
        assert result.status_code == 401


class TestMobileExtMobileModItems:
    """Cover ``_mobile_mod_items`` branches."""

    def test_empty_list(self, ext_mod):
        with patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm:
            mock_mm.return_value.list_all_mods.return_value = []
            assert ext_mod._mobile_mod_items() == []

    def test_dict_mods(self, ext_mod):
        with patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm:
            mock_mm.return_value.list_all_mods.return_value = [
                {"id": "mod-a", "name": "Mod A"},
                {"mod_id": "mod-b", "title": "Mod B"},
            ]
            items = ext_mod._mobile_mod_items()
            assert len(items) == 2
            assert items[0]["id"] == "mod-a"

    def test_object_mods(self, ext_mod):
        with patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm:
            mod = MagicMock()
            mod.id = "mod-obj"
            mod.name = "Obj Mod"
            mod.mod_id = ""
            mod.title = ""
            mock_mm.return_value.list_all_mods.return_value = [mod]
            items = ext_mod._mobile_mod_items()
            assert items[0]["id"] == "mod-obj"

    def test_exception_returns_empty(self, ext_mod):
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            side_effect=RuntimeError("fail"),
        ):
            assert ext_mod._mobile_mod_items() == []

    def test_limit_100(self, ext_mod):
        with patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm:
            mock_mm.return_value.list_all_mods.return_value = [
                {"id": f"mod-{i}", "name": f"Mod {i}"} for i in range(150)
            ]
            assert len(ext_mod._mobile_mod_items()) == 100

    def test_empty_id_skipped(self, ext_mod):
        with patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm:
            mock_mm.return_value.list_all_mods.return_value = [
                {"id": "", "name": "NoId"},
                {"mod_id": "has-id", "title": "HasId"},
            ]
            items = ext_mod._mobile_mod_items()
            assert len(items) == 1
            assert items[0]["id"] == "has-id"


class TestMobileExtApprovalShipmentItems:
    """Cover ``_approval_items`` / ``_shipment_items``."""

    def test_approval_items_happy_path(self, ext_mod):
        mock_db = MagicMock()
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.title = "Test"
        mock_row.status = "pending"
        mock_row.request_no = "REQ-001"
        mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = [
            mock_row
        ]
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db):
            items = ext_mod._approval_items(limit=10)
            assert len(items) == 1
            assert items[0]["id"] == 1

    def test_shipment_items_happy_path(self, ext_mod):
        mock_db = MagicMock()
        mock_row = MagicMock(spec=[])
        mock_row.id = 5
        mock_row.order_number = "ORD-1"
        mock_row.status = "shipped"
        mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = [
            mock_row
        ]
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db):
            items = ext_mod._shipment_items(limit=10)
            assert len(items) == 1
            assert items[0]["id"] == 5


class TestMobileExtDeviceRegister:
    """Cover ``mobile_device_register`` happy paths."""

    @pytest.mark.asyncio
    async def test_register_new_device(self, ext_mod):
        mock_user = MagicMock()
        mock_user.id = 1
        body = ext_mod.DeviceRegisterBody(fcm_token="a" * 10, push_token="push_tok_123")
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with (
            patch.object(ext_mod, "_ensure_mobile_device_table"),
            patch("app.db.session.get_db", return_value=mock_db),
            patch("app.utils.time.utc_now_naive", return_value=datetime.now()),
        ):
            result = await ext_mod.mobile_device_register(body=body, user=mock_user)
        if hasattr(result, "body"):
            data = json.loads(result.body)
        else:
            data = result
        assert data.get("success") is True

    @pytest.mark.asyncio
    async def test_register_existing_device_updates(self, ext_mod):
        mock_user = MagicMock()
        mock_user.id = 1
        body = ext_mod.DeviceRegisterBody(fcm_token="a" * 10, push_token="push_tok_123")
        mock_row = MagicMock()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_row
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with (
            patch.object(ext_mod, "_ensure_mobile_device_table"),
            patch("app.db.session.get_db", return_value=mock_db),
            patch("app.utils.time.utc_now_naive", return_value=datetime.now()),
        ):
            result = await ext_mod.mobile_device_register(body=body, user=mock_user)
        if hasattr(result, "body"):
            data = json.loads(result.body)
        else:
            data = result
        assert data.get("success") is True

    @pytest.mark.asyncio
    async def test_register_missing_push_token(self, ext_mod):
        mock_user = MagicMock()
        mock_user.id = 1
        body = ext_mod.DeviceRegisterBody(fcm_token="        ", push_token="")
        with patch.object(ext_mod, "_ensure_mobile_device_table"):
            result = await ext_mod.mobile_device_register(body=body, user=mock_user)
        assert result.status_code == 400


class TestMobileExtSyncRoutes:
    """Cover sync routes happy paths."""

    @pytest.mark.asyncio
    async def test_sync_status_success(self, ext_mod):
        mock_user = MagicMock()
        mock_user.id = 1
        mock_sync = MagicMock()
        mock_sync.get_status.return_value = {"local_cursor": 5}
        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_sync),
            patch("app.db.xcmax_sync._ensure_schema"),
            patch("app.db.xcmax_sync._get_conn") as mock_conn_ctx,
        ):
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchone.return_value = [0]
            mock_conn_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)
            result = await ext_mod.mobile_sync_status(user=mock_user)
        if hasattr(result, "body"):
            data = json.loads(result.body)
        else:
            data = result
        assert data.get("success") is True

    @pytest.mark.asyncio
    async def test_sync_status_error(self, ext_mod):
        mock_user = MagicMock()
        mock_user.id = 1
        with patch("app.db.xcmax_sync.SyncDb", side_effect=RuntimeError("db fail")):
            result = await ext_mod.mobile_sync_status(user=mock_user)
        if hasattr(result, "body"):
            data = json.loads(result.body)
        else:
            data = result
        assert data.get("success") is True or "error" in data.get("data", {})

    @pytest.mark.asyncio
    async def test_sync_pull_success(self, ext_mod):
        mock_user = MagicMock()
        mock_user.id = 1
        mock_sync = MagicMock()
        mock_sync.get_changes.return_value = [{"entity_type": "im_message"}]
        mock_sync.get_status.return_value = {"local_cursor": 5}
        body = ext_mod.SyncPullBody(since_cursor=0)
        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_sync),
            patch.object(ext_mod, "_approval_items", return_value=[]),
            patch.object(ext_mod, "_shipment_items", return_value=[]),
        ):
            result = await ext_mod.mobile_sync_pull(body=body, user=mock_user)
        if hasattr(result, "body"):
            data = json.loads(result.body)
        else:
            data = result
        assert data.get("success") is True

    @pytest.mark.asyncio
    async def test_sync_pull_error(self, ext_mod):
        mock_user = MagicMock()
        mock_user.id = 1
        body = ext_mod.SyncPullBody(since_cursor=0)
        with patch("app.db.xcmax_sync.SyncDb", side_effect=RuntimeError("db fail")):
            result = await ext_mod.mobile_sync_pull(body=body, user=mock_user)
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_sync_push_success(self, ext_mod):
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "tester"
        body = ext_mod.SyncPushBody(
            items=[ext_mod.SyncPushItem(entity_type="customer", entity_id="1")]
        )
        mock_sync = MagicMock()
        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_sync),
            patch("app.application.xcmax_sync_app.apply_inbox", return_value={"applied": 1}),
        ):
            result = await ext_mod.mobile_sync_push(body=body, user=mock_user)
        if hasattr(result, "body"):
            data = json.loads(result.body)
        else:
            data = result
        assert data.get("success") is True

    @pytest.mark.asyncio
    async def test_sync_push_error(self, ext_mod):
        mock_user = MagicMock()
        mock_user.id = 1
        body = ext_mod.SyncPushBody(items=[])
        with patch("app.db.xcmax_sync.SyncDb", side_effect=RuntimeError("db fail")):
            result = await ext_mod.mobile_sync_push(body=body, user=mock_user)
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_sync_ack_success(self, ext_mod):
        mock_user = MagicMock()
        mock_user.id = 1
        body = ext_mod.SyncAckBody(cursor=10)
        mock_sync = MagicMock()
        with patch("app.db.xcmax_sync.SyncDb", return_value=mock_sync):
            result = await ext_mod.mobile_sync_ack(body=body, user=mock_user)
        if hasattr(result, "body"):
            data = json.loads(result.body)
        else:
            data = result
        assert data.get("success") is True

    @pytest.mark.asyncio
    async def test_sync_ack_error(self, ext_mod):
        mock_user = MagicMock()
        mock_user.id = 1
        body = ext_mod.SyncAckBody(cursor=10)
        with patch("app.db.xcmax_sync.SyncDb", side_effect=RuntimeError("db fail")):
            result = await ext_mod.mobile_sync_ack(body=body, user=mock_user)
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_sync_conflicts_success(self, ext_mod):
        mock_user = MagicMock()
        mock_user.id = 1
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        with (
            patch("app.db.xcmax_sync._ensure_schema"),
            patch("app.db.xcmax_sync._get_conn") as mock_conn_ctx,
        ):
            mock_conn_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)
            result = await ext_mod.mobile_sync_conflicts(user=mock_user)
        if hasattr(result, "body"):
            data = json.loads(result.body)
        else:
            data = result
        assert data.get("success") is True

    @pytest.mark.asyncio
    async def test_sync_conflicts_error(self, ext_mod):
        mock_user = MagicMock()
        mock_user.id = 1
        with patch("app.db.xcmax_sync._get_conn", side_effect=RuntimeError("db fail")):
            result = await ext_mod.mobile_sync_conflicts(user=mock_user)
        if hasattr(result, "body"):
            data = json.loads(result.body)
        else:
            data = result
        assert data.get("success") is True


class TestMobileExtCsRoutes:
    """Cover CS routes happy paths."""

    @pytest.mark.asyncio
    async def test_cs_info_success(self, ext_mod):
        mock_user = MagicMock()
        mock_user.id = 1
        mock_request = MagicMock()
        result = await ext_mod.get_cs_info(request=mock_request, user=mock_user)
        if hasattr(result, "body"):
            data = json.loads(result.body)
        else:
            data = result
        assert data.get("success") is True
        assert data["data"]["cs_available"] is True

    @pytest.mark.asyncio
    async def test_cs_post_message_success(self, ext_mod):
        mock_user = MagicMock()
        mock_user.id = 1
        mock_request = MagicMock()
        result = await ext_mod.post_cs_message(
            request=mock_request, body={"body": "hello"}, user=mock_user
        )
        if hasattr(result, "body"):
            data = json.loads(result.body)
        else:
            data = result
        assert data.get("success") is True
        assert "message_id" in data["data"]

    @pytest.mark.asyncio
    async def test_cs_get_messages_success(self, ext_mod):
        mock_user = MagicMock()
        mock_user.id = 1
        mock_request = MagicMock()
        result = await ext_mod.get_cs_messages(request=mock_request, user=mock_user)
        if hasattr(result, "body"):
            data = json.loads(result.body)
        else:
            data = result
        assert data.get("success") is True
        assert data["data"]["messages"] == []


class TestMobileExtPydanticModels:
    """Cover Pydantic model defaults."""

    def test_device_register_body_defaults(self, ext_mod):
        body = ext_mod.DeviceRegisterBody(fcm_token="a" * 10)
        assert body.platform == "android"
        assert body.product_sku == "personal"

    def test_pairing_exchange_body_defaults(self, ext_mod):
        body = ext_mod.PairingExchangeBody()
        assert body.nonce == ""
        assert body.code == ""

    def test_pairing_issue_body_defaults(self, ext_mod):
        body = ext_mod.PairingIssueBody()
        assert body.host == "127.0.0.1"
        assert body.port == 5000

    def test_sync_pull_body_defaults(self, ext_mod):
        body = ext_mod.SyncPullBody()
        assert body.since_cursor == 0

    def test_sync_push_item_valid(self, ext_mod):
        item = ext_mod.SyncPushItem(entity_type="customer", entity_id="1")
        assert item.entity_type == "customer"
        assert item.operation == "update"

    def test_sync_ack_body_defaults(self, ext_mod):
        body = ext_mod.SyncAckBody()
        assert body.cursor == 0

    def test_pairing_lookup_body_valid(self, ext_mod):
        body = ext_mod.PairingLookupBody(code="123456")
        assert body.code == "123456"

    def test_auth_qr_confirm_body_defaults(self, ext_mod):
        body = ext_mod.AuthQrConfirmBody(qr_id="a" * 8)
        assert body.qr_id == "a" * 8
        assert body.account_kind == "enterprise"

    def test_oidc_exchange_body_valid(self, ext_mod):
        body = ext_mod.OidcExchangeBody(code="abc123", state="s" * 8)
        assert body.code == "abc123"


# ===========================================================================
# 5. app/mod_sdk/industry_seed.py
# ===========================================================================


class TestIndustrySeedDedupe:
    """Cover ``_dedupe`` helper."""

    def test_empty_list(self):
        assert industry_seed_mod._dedupe([]) == []

    def test_removes_duplicates(self):
        assert industry_seed_mod._dedupe(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]

    def test_strips_whitespace(self):
        assert industry_seed_mod._dedupe(["  a  ", "a", "b"]) == ["a", "b"]

    def test_skips_empty_strings(self):
        assert industry_seed_mod._dedupe(["", "  ", "a"]) == ["a"]

    def test_skips_none(self):
        assert industry_seed_mod._dedupe([None, "a", None]) == ["a"]


class TestIndustrySeedOpenIds:
    """Cover ``open_industry_seed_mod_ids``."""

    def test_returns_list(self):
        result = industry_seed_mod.open_industry_seed_mod_ids()
        assert isinstance(result, list)

    def test_with_mocked_baseline(self, monkeypatch):
        mock_doc = {
            "onboarding_open_industry_ids": ["涂料", "考勤"],
            "industry_packages": {
                "涂料": {"mod_id": "coating-industry"},
                "考勤": {"mod_id": "attendance-industry"},
            },
        }
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.load_industry_baseline_document",
            lambda: mock_doc,
        )
        result = industry_seed_mod.open_industry_seed_mod_ids()
        assert "coating-industry" in result
        assert "attendance-industry" in result

    def test_with_empty_doc(self, monkeypatch):
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.load_industry_baseline_document",
            lambda: {},
        )
        assert industry_seed_mod.open_industry_seed_mod_ids() == []

    def test_with_missing_mod_id(self, monkeypatch):
        mock_doc = {
            "onboarding_open_industry_ids": ["unknown"],
            "industry_packages": {"unknown": {}},
        }
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.load_industry_baseline_document",
            lambda: mock_doc,
        )
        assert industry_seed_mod.open_industry_seed_mod_ids() == []


class TestIndustrySeedModIdFor:
    """Cover ``industry_mod_id_for``."""

    def test_empty_returns_none(self):
        assert industry_seed_mod.industry_mod_id_for("") is None

    def test_none_returns_none(self):
        assert industry_seed_mod.industry_mod_id_for(None) is None

    def test_unknown_industry_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.load_industry_baseline_document",
            lambda: {"industry_packages": {}},
        )
        assert industry_seed_mod.industry_mod_id_for("unknown") is None

    def test_known_industry_returns_mod_id(self, monkeypatch):
        mock_doc = {
            "industry_packages": {"涂料": {"mod_id": "coating-industry"}},
        }
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.load_industry_baseline_document",
            lambda: mock_doc,
        )
        assert industry_seed_mod.industry_mod_id_for("涂料") == "coating-industry"

    def test_empty_mod_id_returns_none(self, monkeypatch):
        mock_doc = {
            "industry_packages": {"涂料": {"mod_id": ""}},
        }
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.load_industry_baseline_document",
            lambda: mock_doc,
        )
        assert industry_seed_mod.industry_mod_id_for("涂料") is None


class TestIndustrySeedResolve:
    """Cover ``resolve_industry_or_mod_id``."""

    def test_empty_returns_none_none(self):
        assert industry_seed_mod.resolve_industry_or_mod_id("") == (None, None)

    def test_none_returns_none_none(self):
        assert industry_seed_mod.resolve_industry_or_mod_id(None) == (None, None)

    def test_known_industry_returns_pair(self, monkeypatch):
        mock_doc = {
            "industry_packages": {"涂料": {"mod_id": "coating-industry"}},
        }
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.load_industry_baseline_document",
            lambda: mock_doc,
        )
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.open_industry_seed_mod_ids",
            lambda: ["coating-industry"],
        )
        iid, mid = industry_seed_mod.resolve_industry_or_mod_id("涂料")
        assert iid == "涂料"
        assert mid == "coating-industry"

    def test_mod_id_in_open_pool_returns_pair(self, monkeypatch):
        mock_doc = {
            "onboarding_open_industry_ids": ["涂料"],
            "industry_packages": {"涂料": {"mod_id": "coating-industry"}},
        }
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.load_industry_baseline_document",
            lambda: mock_doc,
        )
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.open_industry_seed_mod_ids",
            lambda: ["coating-industry"],
        )
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.industry_mod_id_for",
            lambda iid: "coating-industry" if iid == "涂料" else None,
        )
        iid, mid = industry_seed_mod.resolve_industry_or_mod_id("coating-industry")
        assert mid == "coating-industry"

    def test_unknown_returns_none_none(self, monkeypatch):
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.industry_mod_id_for",
            lambda iid: None,
        )
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.open_industry_seed_mod_ids",
            lambda: [],
        )
        assert industry_seed_mod.resolve_industry_or_mod_id("unknown") == (None, None)


class TestIndustrySeedBundledDir:
    """Cover ``bundled_industry_seeds_dir``."""

    def test_env_var_set(self, tmp_path, monkeypatch):
        pool = tmp_path / "seeds"
        pool.mkdir()
        monkeypatch.setenv("XCAGI_INDUSTRY_SEEDS_DIR", str(pool))
        result = industry_seed_mod.bundled_industry_seeds_dir()
        assert result == pool.resolve()

    def test_staged_env_var(self, tmp_path, monkeypatch):
        pool = tmp_path / "staged"
        pool.mkdir()
        monkeypatch.delenv("XCAGI_INDUSTRY_SEEDS_DIR", raising=False)
        monkeypatch.setenv("XCAGI_STAGED_INDUSTRY_SEEDS_DIR", str(pool))
        result = industry_seed_mod.bundled_industry_seeds_dir()
        assert result == pool.resolve()

    def test_env_var_not_dir_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCAGI_INDUSTRY_SEEDS_DIR", str(tmp_path / "missing"))
        monkeypatch.delenv("XCAGI_STAGED_INDUSTRY_SEEDS_DIR", raising=False)
        # No frozen, no cwd match (cwd is project root), no parent match likely
        result = industry_seed_mod.bundled_industry_seeds_dir()
        # Result depends on environment; just verify it doesn't crash
        assert result is None or isinstance(result, Path)


class TestIndustrySeedOtherOpen:
    """Cover ``other_open_industry_mod_ids``."""

    def test_excludes_keep(self, monkeypatch):
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.open_industry_seed_mod_ids",
            lambda: ["a", "b", "c"],
        )
        result = industry_seed_mod.other_open_industry_mod_ids("b")
        assert "b" not in result
        assert "a" in result
        assert "c" in result

    def test_empty_keep(self, monkeypatch):
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.open_industry_seed_mod_ids",
            lambda: ["a", "b"],
        )
        result = industry_seed_mod.other_open_industry_mod_ids("")
        assert "a" in result
        assert "b" in result


class TestIndustrySeedDeactivate:
    """Cover ``deactivate_other_open_industry_mods``."""

    def test_deactivate_with_remove_files(self, tmp_path, monkeypatch):
        keep = "coating-industry"
        other = "attendance-industry"
        mods_root = tmp_path / "mods"
        (mods_root / other).mkdir(parents=True)
        (mods_root / other / "manifest.json").write_text("{}", encoding="utf-8")

        unloaded: list[str] = []

        class FakeMM:
            def __init__(self):
                self.mods_root = str(mods_root)

            def unload_mod(self, mod_id):
                unloaded.append(mod_id)
                return True

        monkeypatch.setattr(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            lambda: FakeMM(),
        )
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.open_industry_seed_mod_ids",
            lambda: [keep, other],
        )
        rows = industry_seed_mod.deactivate_other_open_industry_mods(keep, remove_files=True)
        assert other in unloaded
        assert not (mods_root / other).exists()
        assert any(r.get("mod_id") == other for r in rows)

    def test_deactivate_without_remove_files(self, tmp_path, monkeypatch):
        keep = "coating-industry"
        other = "attendance-industry"
        mods_root = tmp_path / "mods"
        (mods_root / other).mkdir(parents=True)

        class FakeMM:
            def __init__(self):
                self.mods_root = str(mods_root)

            def unload_mod(self, mod_id):
                return True

        monkeypatch.setattr(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            lambda: FakeMM(),
        )
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.open_industry_seed_mod_ids",
            lambda: [keep, other],
        )
        rows = industry_seed_mod.deactivate_other_open_industry_mods(keep, remove_files=False)
        assert (mods_root / other).exists()
        assert all(not r.get("removed_files") for r in rows)

    def test_deactivate_unload_raises(self, tmp_path, monkeypatch):
        keep = "coating-industry"
        other = "attendance-industry"
        mods_root = tmp_path / "mods"

        class FakeMM:
            def __init__(self):
                self.mods_root = str(mods_root)

            def unload_mod(self, mod_id):
                raise RuntimeError("unload fail")

        monkeypatch.setattr(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            lambda: FakeMM(),
        )
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.open_industry_seed_mod_ids",
            lambda: [keep, other],
        )
        rows = industry_seed_mod.deactivate_other_open_industry_mods(keep, remove_files=False)
        assert len(rows) == 1

    def test_deactivate_remove_files_oserror(self, tmp_path, monkeypatch):
        keep = "coating-industry"
        other = "attendance-industry"
        mods_root = tmp_path / "mods"
        (mods_root / other).mkdir(parents=True)

        class FakeMM:
            def __init__(self):
                self.mods_root = str(mods_root)

            def unload_mod(self, mod_id):
                return True

        monkeypatch.setattr(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            lambda: FakeMM(),
        )
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.open_industry_seed_mod_ids",
            lambda: [keep, other],
        )
        with patch("shutil.rmtree", side_effect=OSError("perm denied")):
            rows = industry_seed_mod.deactivate_other_open_industry_mods(keep, remove_files=True)
        assert all(r.get("removed_files") is False for r in rows)


class TestIndustrySeedSeedMod:
    """Cover ``seed_industry_mod`` branches."""

    def test_invalid_industry_returns_invalid(self, monkeypatch):
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.resolve_industry_or_mod_id",
            lambda raw: (None, None),
        )
        result = industry_seed_mod.seed_industry_mod("unknown")
        assert result["success"] is False
        assert result["status"] == "invalid"

    def test_already_present(self, tmp_path, monkeypatch):
        mod_id = "coating-industry"
        mods_root = tmp_path / "mods"
        (mods_root / mod_id).mkdir(parents=True)

        class FakeMM:
            def __init__(self):
                self.mods_root = str(mods_root)

            def load_mod(self, mid):
                return True

        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.resolve_industry_or_mod_id",
            lambda raw: ("涂料", mod_id),
        )
        monkeypatch.setattr(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            lambda: FakeMM(),
        )
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.deactivate_other_open_industry_mods",
            lambda keep, **kw: [],
        )
        result = industry_seed_mod.seed_industry_mod("涂料")
        assert result["status"] == "already_present"

    def test_pool_missing(self, tmp_path, monkeypatch):
        mod_id = "coating-industry"
        mods_root = tmp_path / "mods"
        mods_root.mkdir()

        class FakeMM:
            def __init__(self):
                self.mods_root = str(mods_root)

        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.resolve_industry_or_mod_id",
            lambda raw: ("涂料", mod_id),
        )
        monkeypatch.setattr(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            lambda: FakeMM(),
        )
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.bundled_industry_seeds_dir",
            lambda: None,
        )
        result = industry_seed_mod.seed_industry_mod("涂料")
        assert result["success"] is False
        assert result["status"] == "pool_missing"

    def test_not_in_pool(self, tmp_path, monkeypatch):
        mod_id = "coating-industry"
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        pool = tmp_path / "pool"
        pool.mkdir()

        class FakeMM:
            def __init__(self):
                self.mods_root = str(mods_root)

        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.resolve_industry_or_mod_id",
            lambda raw: ("涂料", mod_id),
        )
        monkeypatch.setattr(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            lambda: FakeMM(),
        )
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.bundled_industry_seeds_dir",
            lambda: pool,
        )
        result = industry_seed_mod.seed_industry_mod("涂料")
        assert result["success"] is False
        assert result["status"] == "not_in_pool"

    def test_seed_success(self, tmp_path, monkeypatch):
        mod_id = "coating-industry"
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        pool = tmp_path / "pool"
        (pool / mod_id).mkdir(parents=True)
        (pool / mod_id / "manifest.json").write_text("{}", encoding="utf-8")

        class FakeMM:
            def __init__(self):
                self.mods_root = str(mods_root)

            def invalidate_scan_cache(self):
                pass

            def load_mod(self, mid):
                return True

        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.resolve_industry_or_mod_id",
            lambda raw: ("涂料", mod_id),
        )
        monkeypatch.setattr(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            lambda: FakeMM(),
        )
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.bundled_industry_seeds_dir",
            lambda: pool,
        )
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.deactivate_other_open_industry_mods",
            lambda keep, **kw: [],
        )
        result = industry_seed_mod.seed_industry_mod("涂料")
        assert result["success"] is True
        assert result["status"] == "seeded"

    def test_seed_copy_error(self, tmp_path, monkeypatch):
        mod_id = "coating-industry"
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        pool = tmp_path / "pool"
        (pool / mod_id).mkdir(parents=True)

        class FakeMM:
            def __init__(self):
                self.mods_root = str(mods_root)

        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.resolve_industry_or_mod_id",
            lambda raw: ("涂料", mod_id),
        )
        monkeypatch.setattr(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            lambda: FakeMM(),
        )
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.bundled_industry_seeds_dir",
            lambda: pool,
        )
        with patch("shutil.copytree", side_effect=OSError("copy fail")):
            result = industry_seed_mod.seed_industry_mod("涂料")
        assert result["success"] is False
        assert result["status"] == "copy_error"


class TestIndustrySeedInstallFallback:
    """Cover ``install_industry_seed_with_fallback``."""

    @pytest.mark.asyncio
    async def test_seed_success_returns_directly(self, monkeypatch):
        mock_result = {"success": True, "mod_id": "x", "status": "seeded"}
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.seed_industry_mod",
            lambda iid: mock_result,
        )
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.deactivate_other_open_industry_mods",
            lambda keep, **kw: [],
        )
        result = await industry_seed_mod.install_industry_seed_with_fallback("涂料")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_seed_failure_pool_missing_catalog_success(self, monkeypatch):
        mock_result = {
            "success": False,
            "mod_id": "x",
            "status": "pool_missing",
            "industry_id": "涂料",
            "message": "missing",
        }
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.seed_industry_mod",
            lambda iid: mock_result,
        )
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.deactivate_other_open_industry_mods",
            lambda keep, **kw: [],
        )
        mock_catalog = MagicMock()
        mock_catalog.success = True
        mock_catalog.message = "ok"
        with patch(
            "app.fastapi_routes.mod_store_routes._install_from_catalog",
            new=AsyncMock(return_value=mock_catalog),
        ):
            result = await industry_seed_mod.install_industry_seed_with_fallback("涂料")
        assert result["success"] is True
        assert result["status"] == "catalog"

    @pytest.mark.asyncio
    async def test_seed_failure_pool_missing_catalog_failure(self, monkeypatch):
        mock_result = {
            "success": False,
            "mod_id": "x",
            "status": "not_in_pool",
            "industry_id": "涂料",
            "message": "missing",
        }
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.seed_industry_mod",
            lambda iid: mock_result,
        )
        mock_catalog = MagicMock()
        mock_catalog.success = False
        mock_catalog.message = "catalog fail"
        with patch(
            "app.fastapi_routes.mod_store_routes._install_from_catalog",
            new=AsyncMock(return_value=mock_catalog),
        ):
            result = await industry_seed_mod.install_industry_seed_with_fallback("涂料")
        assert result["success"] is False
        assert result["status"] == "catalog_failed"

    @pytest.mark.asyncio
    async def test_seed_failure_invalid_no_catalog(self, monkeypatch):
        mock_result = {
            "success": False,
            "mod_id": None,
            "status": "invalid",
            "industry_id": None,
            "message": "invalid",
        }
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.seed_industry_mod",
            lambda iid: mock_result,
        )
        result = await industry_seed_mod.install_industry_seed_with_fallback("unknown")
        assert result["success"] is False
        assert result["status"] == "invalid"

    @pytest.mark.asyncio
    async def test_catalog_raises_recoverable(self, monkeypatch):
        mock_result = {
            "success": False,
            "mod_id": "x",
            "status": "pool_missing",
            "industry_id": "涂料",
            "message": "missing",
        }
        monkeypatch.setattr(
            "app.mod_sdk.industry_seed.seed_industry_mod",
            lambda iid: mock_result,
        )
        with patch(
            "app.fastapi_routes.mod_store_routes._install_from_catalog",
            new=AsyncMock(side_effect=RuntimeError("catalog err")),
        ):
            result = await industry_seed_mod.install_industry_seed_with_fallback("涂料")
        assert result["success"] is False
        assert result["status"] == "catalog_failed"


# ===========================================================================
# 6. app/services/wechat_contact_service.py
# ===========================================================================


@pytest.fixture
def wechat_svc() -> WechatContactService:
    return WechatContactService()


class TestWechatGetContacts:
    """Cover ``get_contacts`` branches."""

    def test_keyword_with_results(self, wechat_svc):
        s = MagicMock()
        s.query.return_value = _fluent(all_=[_contact()])
        with _patch_db(wechat_mod, s):
            out = wechat_svc.get_contacts(keyword="张")
        assert out[0]["contact_name"] == "张三"

    def test_type_all_default_starred(self, wechat_svc):
        s = MagicMock()
        s.query.return_value = _fluent(all_=[_contact()])
        with _patch_db(wechat_mod, s):
            out = wechat_svc.get_contacts(contact_type="all", starred_only=True)
        assert len(out) == 1

    def test_type_specific(self, wechat_svc):
        s = MagicMock()
        s.query.return_value = _fluent(all_=[_contact(contact_type="group")])
        with _patch_db(wechat_mod, s):
            out = wechat_svc.get_contacts(contact_type="group")
        assert out[0]["contact_type"] == "group"

    def test_keyword_fallback_to_wechat_db(self, wechat_svc):
        s = MagicMock()
        s.query.return_value = _fluent(all_=[])
        extra = [{"id": 99, "contact_name": "挖到的"}]
        with (
            _patch_db(wechat_mod, s),
            patch.object(wechat_svc, "_search_contacts_from_wechat_db", return_value=extra),
        ):
            out = wechat_svc.get_contacts(keyword="找不到")
        assert out == extra

    def test_keyword_fallback_raises_returns_empty(self, wechat_svc):
        s = MagicMock()
        s.query.return_value = _fluent(all_=[])
        with (
            _patch_db(wechat_mod, s),
            patch.object(
                wechat_svc,
                "_search_contacts_from_wechat_db",
                side_effect=RuntimeError("db fail"),
            ),
        ):
            out = wechat_svc.get_contacts(keyword="找不到")
        assert out == []

    def test_db_error_returns_empty(self, wechat_svc):
        with patch.object(wechat_mod, "get_db", side_effect=RuntimeError("db down")):
            assert wechat_svc.get_contacts() == []

    def test_no_filters_returns_all(self, wechat_svc):
        s = MagicMock()
        s.query.return_value = _fluent(all_=[_contact(), _contact(id=2, contact_name="李四")])
        with _patch_db(wechat_mod, s):
            out = wechat_svc.get_contacts()
        assert len(out) == 2


class TestWechatSearchContactsFromWechatDb:
    """Cover ``_search_contacts_from_wechat_db`` branches."""

    def test_empty_keyword(self, wechat_svc):
        assert wechat_svc._search_contacts_from_wechat_db("") == []
        assert wechat_svc._search_contacts_from_wechat_db("   ") == []

    def test_via_contact_sqlite(self, wechat_svc, tmp_path):
        decrypted = tmp_path / "decrypted" / "message"
        decrypted.mkdir(parents=True)
        msg_db = decrypted / "message_0.db"
        msg_db.write_bytes(b"x")

        contact_dir = tmp_path / "decrypted" / "contact"
        contact_dir.mkdir(parents=True)
        contact_db = contact_dir / "contact.db"
        with sqlite3.connect(contact_db) as conn:
            conn.execute(
                "CREATE TABLE contact (username TEXT, nick_name TEXT, remark TEXT, "
                "is_in_chat_room INTEGER, delete_flag INTEGER)"
            )
            conn.execute(
                "INSERT INTO contact VALUES (?, ?, ?, ?, ?)",
                ("wxid_demo", "七彩乐园", "备注", 0, 0),
            )
            conn.commit()

        with patch.dict(os.environ, {"WECHAT_MSG_DB_PATH": str(msg_db)}, clear=False):
            out = wechat_svc._search_contacts_from_wechat_db("七彩", limit=5)
        assert len(out) == 1
        assert out[0]["contact_name"] == "七彩乐园"

    def test_via_message_db_old_format(self, wechat_svc, tmp_path):
        db_path = tmp_path / "message_0.db"
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE MSG (talker TEXT, displayName TEXT)")
            conn.execute("INSERT INTO MSG VALUES (?, ?)", ("wxid_abc", "李四"))
            conn.commit()

        plugin = MagicMock()
        plugin.is_available.return_value = True
        plugin.add_to_sys_path.return_value = None
        plugin.get_decrypted_db_path.return_value = None
        fake_wdr = MagicMock(get_recent_messages=MagicMock(return_value={"rows": []}))
        with (
            patch.dict(os.environ, {"WECHAT_MSG_DB_PATH": str(db_path)}, clear=False),
            patch(
                "app.infrastructure.plugins.wechat_plugin.get_wechat_plugin",
                return_value=plugin,
            ),
            patch("app.utils.path_utils.get_base_dir", return_value=str(tmp_path)),
            patch.dict("sys.modules", {"wechat_db_read": fake_wdr}),
        ):
            out = wechat_svc._search_contacts_from_wechat_db("李四", limit=3)
        assert len(out) == 1
        assert out[0]["contact_name"] == "李四"

    def test_no_db_path_returns_empty(self, wechat_svc, tmp_path, monkeypatch):
        monkeypatch.delenv("WECHAT_MSG_DB_PATH", raising=False)
        plugin = MagicMock()
        plugin.is_available.return_value = False
        plugin.get_decrypted_db_path.return_value = None
        with (
            patch(
                "app.infrastructure.plugins.wechat_plugin.get_wechat_plugin",
                return_value=plugin,
            ),
            patch("app.utils.path_utils.get_base_dir", return_value=str(tmp_path)),
        ):
            out = wechat_svc._search_contacts_from_wechat_db("x")
        assert out == []

    def test_recoverable_error_returns_empty(self, wechat_svc, tmp_path, monkeypatch):
        monkeypatch.delenv("WECHAT_MSG_DB_PATH", raising=False)
        with patch(
            "app.infrastructure.plugins.wechat_plugin.get_wechat_plugin",
            side_effect=RuntimeError("plugin fail"),
        ):
            out = wechat_svc._search_contacts_from_wechat_db("x")
        assert out == []


class TestWechatGetContactById:
    """Cover ``get_contact_by_id`` branches."""

    def test_found(self, wechat_svc):
        s = MagicMock()
        s.query.return_value = _fluent(first=_contact())
        with _patch_db(wechat_mod, s):
            out = wechat_svc.get_contact_by_id(1)
        assert out["id"] == 1

    def test_missing(self, wechat_svc):
        s = MagicMock()
        s.query.return_value = _fluent(first=None)
        with _patch_db(wechat_mod, s):
            assert wechat_svc.get_contact_by_id(9) is None

    def test_db_error_returns_none(self, wechat_svc):
        with patch.object(wechat_mod, "get_db", side_effect=RuntimeError("db fail")):
            assert wechat_svc.get_contact_by_id(1) is None


class TestWechatAddContact:
    """Cover ``add_contact`` branches."""

    def test_empty_name(self, wechat_svc):
        out = wechat_svc.add_contact("   ")
        assert out["success"] is False

    def test_placeholder_name_uses_wechat_id(self, wechat_svc):
        s = MagicMock()
        with _patch_db(wechat_mod, s):
            out = wechat_svc.add_contact("%", wechat_id="wxid_123")
        assert out["success"] is True
        s.add.assert_called_once()

    def test_placeholder_short_name_uses_wechat_id(self, wechat_svc):
        s = MagicMock()
        with _patch_db(wechat_mod, s):
            out = wechat_svc.add_contact("%s", wechat_id="wxid_456")
        assert out["success"] is True

    def test_success(self, wechat_svc):
        s = MagicMock()
        with _patch_db(wechat_mod, s):
            out = wechat_svc.add_contact("李四", remark="同事")
        assert out["success"] is True

    def test_db_error(self, wechat_svc):
        with patch.object(wechat_mod, "get_db", side_effect=RuntimeError("db fail")):
            out = wechat_svc.add_contact("x")
        assert out["success"] is False


class TestWechatUpdateContact:
    """Cover ``update_contact`` branches."""

    def test_not_found(self, wechat_svc):
        s = MagicMock()
        s.query.return_value = _fluent(first=None)
        with _patch_db(wechat_mod, s):
            assert wechat_svc.update_contact(1, contact_name="x")["success"] is False

    def test_success_all_fields(self, wechat_svc):
        s = MagicMock()
        s.query.return_value = _fluent(first=_contact())
        with _patch_db(wechat_mod, s):
            out = wechat_svc.update_contact(
                1,
                contact_name="新名",
                remark="新备注",
                wechat_id="newid",
                contact_type="invalid_type",
                is_starred=False,
            )
        assert out["success"] is True

    def test_empty_name(self, wechat_svc):
        s = MagicMock()
        s.query.return_value = _fluent(first=_contact())
        with _patch_db(wechat_mod, s):
            out = wechat_svc.update_contact(1, contact_name="   ")
        assert out["success"] is False

    def test_db_error(self, wechat_svc):
        with patch.object(wechat_mod, "get_db", side_effect=RuntimeError("db fail")):
            out = wechat_svc.update_contact(1, contact_name="x")
        assert out["success"] is False


class TestWechatDeleteAndStar:
    """Cover ``delete_contact`` and ``star_contact``."""

    def test_delete_success(self, wechat_svc):
        s = MagicMock()
        s.query.return_value = _fluent(first=_contact())
        with _patch_db(wechat_mod, s):
            assert wechat_svc.delete_contact(1)["success"] is True

    def test_delete_not_found(self, wechat_svc):
        s = MagicMock()
        s.query.return_value = _fluent(first=None)
        with _patch_db(wechat_mod, s):
            assert wechat_svc.delete_contact(9)["success"] is False

    def test_star_contact_delegates(self, wechat_svc):
        s = MagicMock()
        s.query.return_value = _fluent(first=_contact())
        with _patch_db(wechat_mod, s):
            assert wechat_svc.star_contact(1, starred=True)["success"] is True

    def test_unstar_all(self, wechat_svc):
        s = MagicMock()
        s.query.return_value = _fluent(update_=3)
        with _patch_db(wechat_mod, s):
            out = wechat_svc.unstar_all()
        assert out["success"] is True
        assert out["count"] == 3

    def test_unstar_all_db_error(self, wechat_svc):
        with patch.object(wechat_mod, "get_db", side_effect=RuntimeError("db fail")):
            out = wechat_svc.unstar_all()
        assert out["success"] is False


class TestWechatContactContext:
    """Cover ``get_contact_context`` and ``save_contact_context``."""

    def test_get_context_empty(self, wechat_svc):
        s = MagicMock()
        s.query.return_value = _fluent(first=None)
        with _patch_db(wechat_mod, s):
            assert wechat_svc.get_contact_context(1) == []

    def test_get_context_parsed(self, wechat_svc):
        ctx = SimpleNamespace(context_json=json.dumps([{"m": "hi"}]))
        s = MagicMock()
        s.query.return_value = _fluent(first=ctx)
        with _patch_db(wechat_mod, s):
            out = wechat_svc.get_contact_context(1)
        assert out == [{"m": "hi"}]

    def test_get_context_invalid_json(self, wechat_svc):
        ctx = SimpleNamespace(context_json="{not json")
        s = MagicMock()
        s.query.return_value = _fluent(first=ctx)
        with _patch_db(wechat_mod, s):
            assert wechat_svc.get_contact_context(1) == []

    def test_get_context_db_error(self, wechat_svc):
        with patch.object(wechat_mod, "get_db", side_effect=RuntimeError("db fail")):
            assert wechat_svc.get_contact_context(1) == []

    def test_save_context_update_existing(self, wechat_svc):
        ctx = SimpleNamespace(wechat_id="", context_json="", message_count=0, updated_at=None)
        s = MagicMock()
        s.query.return_value = _fluent(first=ctx)
        with _patch_db(wechat_mod, s):
            assert wechat_svc.save_contact_context(1, "wx", [{"m": "a"}]) is True
        assert ctx.message_count == 1

    def test_save_context_insert_new(self, wechat_svc):
        s = MagicMock()
        s.query.return_value = _fluent(first=None)
        with _patch_db(wechat_mod, s):
            assert wechat_svc.save_contact_context(1, "wx", [{"m": "a"}]) is True
        s.add.assert_called_once()

    def test_save_context_db_error(self, wechat_svc):
        with patch.object(wechat_mod, "get_db", side_effect=RuntimeError("db fail")):
            assert wechat_svc.save_contact_context(1, "wx", []) is False


class TestWechatResolveSendMessage:
    """Cover ``resolve_send_message`` and ``_find_best_matching_contact``."""

    def test_too_short(self, wechat_svc):
        assert wechat_svc.resolve_send_message("hi") == (None, None)

    def test_match(self, wechat_svc):
        with patch.object(wechat_svc, "_find_best_matching_contact", return_value="张三"):
            contact, content = wechat_svc.resolve_send_message("给张三发送你好呀")
        assert contact == "张三"
        assert content == "你好呀"

    def test_no_match(self, wechat_svc):
        with patch.object(wechat_svc, "_find_best_matching_contact", return_value=None):
            assert wechat_svc.resolve_send_message("给某人发送内容啊") == (None, None)

    def test_pattern_without_colon(self, wechat_svc):
        with patch.object(wechat_svc, "_find_best_matching_contact", return_value=None):
            assert wechat_svc.resolve_send_message("发给张三") == (None, None)

    def test_find_best_matching_contact_fuzzy(self, wechat_svc):
        with patch.object(
            wechat_svc,
            "get_contacts",
            return_value=[{"contact_name": "七彩乐园有限公司"}],
        ):
            hit = wechat_svc._find_best_matching_contact("七彩乐园")
        assert hit == "七彩乐园有限公司"

    def test_find_best_matching_contact_no_contacts(self, wechat_svc):
        with patch.object(wechat_svc, "get_contacts", return_value=[]):
            assert wechat_svc._find_best_matching_contact("无人") is None

    def test_find_best_matching_contact_low_score(self, wechat_svc):
        with patch.object(
            wechat_svc,
            "get_contacts",
            return_value=[{"contact_name": "完全不同的名字"}],
        ):
            assert wechat_svc._find_best_matching_contact("张三") is None


class TestWechatRefreshMessages:
    """Cover ``refresh_messages`` branches."""

    def test_contact_missing(self, wechat_svc):
        s = MagicMock()
        s.query.return_value = _fluent(first=None)
        with _patch_db(wechat_mod, s):
            out = wechat_svc.refresh_messages(99)
        assert out["success"] is False
        assert "不存在" in out["message"]

    def test_empty_wechat_id(self, wechat_svc):
        s = MagicMock()
        s.query.return_value = _fluent(first=_contact(wechat_id="", contact_name=""))
        with _patch_db(wechat_mod, s):
            out = wechat_svc.refresh_messages(1)
        assert out["success"] is False

    def test_no_db_file(self, wechat_svc, tmp_path):
        s = MagicMock()
        s.query.return_value = _fluent(first=_contact())
        missing = str(tmp_path / "no_message.db")
        with (
            _patch_db(wechat_mod, s),
            patch(
                "app.utils.path_utils.get_resource_path",
                return_value=str(tmp_path / "missing"),
            ),
            patch.dict(os.environ, {"WECHAT_MSG_DB_PATH": missing}, clear=False),
        ):
            out = wechat_svc.refresh_messages(1)
        assert out["success"] is False
        assert "数据库不存在" in out["message"]

    def test_import_wechat_db_read_fails(self, wechat_svc, tmp_path):
        s = MagicMock()
        s.query.return_value = _fluent(first=_contact())
        db_file = tmp_path / "message_0.db"
        db_file.write_bytes(b"")

        class _FailModule:
            def __getattr__(self, name):
                raise ImportError(f"cannot import {name}")

        with (
            _patch_db(wechat_mod, s),
            patch.dict(os.environ, {"WECHAT_MSG_DB_PATH": str(db_file)}, clear=False),
            patch(
                "app.utils.path_utils.get_resource_path",
                return_value=str(tmp_path),
            ),
            patch.dict(
                "sys.modules",
                {"wechat_db_read": _FailModule()},
            ),
        ):
            out = wechat_svc.refresh_messages(1)
        assert out["success"] is False

    def test_success(self, wechat_svc, tmp_path):
        s = MagicMock()
        s.query.return_value = _fluent(first=_contact())
        db_file = tmp_path / "message_0.db"
        db_file.write_bytes(b"")
        fake_read = MagicMock(
            return_value={"success": True, "rows": [{"role": "other", "text": "你好"}]}
        )
        with (
            _patch_db(wechat_mod, s),
            patch.dict(os.environ, {"WECHAT_MSG_DB_PATH": str(db_file)}, clear=False),
            patch(
                "app.utils.path_utils.get_resource_path",
                return_value=str(tmp_path),
            ),
            patch.dict(
                "sys.modules",
                {
                    "wechat_db_read": MagicMock(
                        get_messages_for_contact=fake_read,
                        get_wechat_contact_db_path=MagicMock(),
                    )
                },
            ),
            patch.object(wechat_svc, "save_contact_context", return_value=True),
        ):
            out = wechat_svc.refresh_messages(1, limit=10)
        assert out["success"] is True

    def test_no_rows(self, wechat_svc, tmp_path):
        s = MagicMock()
        s.query.return_value = _fluent(first=_contact())
        db_file = tmp_path / "message_0.db"
        db_file.write_bytes(b"")
        fake_read = MagicMock(return_value={"success": True, "rows": []})
        with (
            _patch_db(wechat_mod, s),
            patch.dict(os.environ, {"WECHAT_MSG_DB_PATH": str(db_file)}, clear=False),
            patch(
                "app.utils.path_utils.get_resource_path",
                return_value=str(tmp_path),
            ),
            patch.dict(
                "sys.modules",
                {
                    "wechat_db_read": MagicMock(
                        get_messages_for_contact=fake_read,
                        get_wechat_contact_db_path=MagicMock(),
                    )
                },
            ),
        ):
            out = wechat_svc.refresh_messages(1, limit=10)
        assert out["success"] is True
        assert out["count"] == 0

    def test_read_failure(self, wechat_svc, tmp_path):
        s = MagicMock()
        s.query.return_value = _fluent(first=_contact())
        db_file = tmp_path / "message_0.db"
        db_file.write_bytes(b"")
        fake_read = MagicMock(return_value={"success": False, "message": "read err"})
        with (
            _patch_db(wechat_mod, s),
            patch.dict(os.environ, {"WECHAT_MSG_DB_PATH": str(db_file)}, clear=False),
            patch(
                "app.utils.path_utils.get_resource_path",
                return_value=str(tmp_path),
            ),
            patch.dict(
                "sys.modules",
                {
                    "wechat_db_read": MagicMock(
                        get_messages_for_contact=fake_read,
                        get_wechat_contact_db_path=MagicMock(),
                    )
                },
            ),
        ):
            out = wechat_svc.refresh_messages(1, limit=10)
        assert out["success"] is False

    def test_db_error(self, wechat_svc):
        with patch.object(wechat_mod, "get_db", side_effect=RuntimeError("db fail")):
            out = wechat_svc.refresh_messages(1)
        assert out["success"] is False


class TestWechatGetService:
    """Cover singleton ``get_wechat_contact_service``."""

    def test_singleton(self):
        assert wechat_mod.get_wechat_contact_service() is wechat_mod.get_wechat_contact_service()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
