"""Tests for app.infrastructure.repositories.product_repository_impl — domain-style SQLAlchemy product repo."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.repositories.product_repository_impl import (
    SQLAlchemyProductRepository,
)

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def repo():
    return SQLAlchemyProductRepository()


def _mock_db_ctx(mock_db):
    """Return a context manager that yields mock_db."""

    @contextmanager
    def _ctx():
        yield mock_db

    return _ctx()


def _make_mock_product_model(**overrides):
    """Create a mock Product ORM model with realistic attributes."""
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


# ---------------------------------------------------------------------------
# _to_domain / _to_db_model
# ---------------------------------------------------------------------------


class TestToDomainAndToDb:
    """_to_domain / _to_db_model — 转换方法"""

    @patch("app.infrastructure.repositories.product_repository_impl.product_to_domain")
    def test_to_domain_delegates(self, mock_to_domain, repo):
        """_to_domain 委托给 product_to_domain"""
        mock_model = _make_mock_product_model()
        mock_domain = MagicMock()
        mock_to_domain.return_value = mock_domain

        result = repo._to_domain(mock_model)
        mock_to_domain.assert_called_once_with(mock_model)
        assert result is mock_domain

    @patch("app.infrastructure.repositories.product_repository_impl.product_to_db")
    def test_to_db_model_delegates(self, mock_to_db, repo):
        """_to_db_model 委托给 product_to_db"""
        mock_product = MagicMock()
        mock_to_db.return_value = {"name": "测试"}

        result = repo._to_db_model(mock_product)
        mock_to_db.assert_called_once_with(mock_product)
        assert result == {"name": "测试"}


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------


class TestSave:
    """save() — 保存产品（创建或更新）"""

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    @patch("app.infrastructure.repositories.product_repository_impl.product_to_domain")
    @patch("app.infrastructure.repositories.product_repository_impl.product_to_db")
    def test_save_new_product(self, mock_to_db, mock_to_domain, mock_get_db, repo):
        """无 id 的产品走创建路径"""
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

        # Patch ProductModel constructor
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
        """有 id 且数据库中存在的产品走更新路径"""
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

        # Should update existing model attributes
        mock_db.commit.assert_called_once()

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    @patch("app.infrastructure.repositories.product_repository_impl.product_to_domain")
    @patch("app.infrastructure.repositories.product_repository_impl.product_to_db")
    def test_save_product_with_id_not_found_creates_new(
        self, mock_to_db, mock_to_domain, mock_get_db, repo
    ):
        """有 id 但数据库中不存在的产品走创建路径"""
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


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


class TestCreate:
    """create() — 委托给 save"""

    @patch.object(SQLAlchemyProductRepository, "save")
    def test_create_delegates_to_save(self, mock_save, repo):
        """create 委托给 save"""
        mock_product = MagicMock()
        mock_save.return_value = mock_product

        result = repo.create(mock_product)
        mock_save.assert_called_once_with(mock_product)
        assert result is mock_product


# ---------------------------------------------------------------------------
# find_by_id
# ---------------------------------------------------------------------------


class TestFindById:
    """find_by_id() — 按 ID 查找产品"""

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    @patch("app.infrastructure.repositories.product_repository_impl.product_to_domain")
    def test_found(self, mock_to_domain, mock_get_db, repo):
        """找到产品时返回 domain 对象"""
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
        """未找到产品时返回 None"""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.find_by_id(999)
        assert result is None


# ---------------------------------------------------------------------------
# find_all
# ---------------------------------------------------------------------------


class TestFindAllRepo:
    """find_all() — 分页查询产品（domain 版）"""

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    @patch("app.infrastructure.repositories.product_repository_impl.product_to_domain")
    def test_basic_query(self, mock_to_domain, mock_get_db, repo):
        """基本查询返回产品和总数"""
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
        """unit_name 过滤"""
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
        """model_number 过滤"""
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
        """model_number 为空字符串时不添加过滤"""
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
        """keyword 单段过滤"""
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
        """keyword 多段过滤（中文+数字）"""
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
        """keyword 去除空白后为空时不添加过滤"""
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


# ---------------------------------------------------------------------------
# find_all_dict
# ---------------------------------------------------------------------------


class TestFindAllDict:
    """find_all_dict() — 快速查询返回字典列表"""

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    def test_basic_dict_query(self, mock_get_db, repo):
        """基本查询返回字典列表和总数"""
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
        """字段为 None 时使用默认值"""
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
        """unit_name 过滤"""
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
        """keyword 过滤"""
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


# ---------------------------------------------------------------------------
# find_by_model_number
# ---------------------------------------------------------------------------


class TestFindByModelNumber:
    """find_by_model_number() — 按型号查找产品"""

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    @patch("app.infrastructure.repositories.product_repository_impl.product_to_domain")
    def test_found(self, mock_to_domain, mock_get_db, repo):
        """找到产品时返回 domain 对象"""
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
        """未找到产品时返回 None"""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.find_by_model_number("NONEXISTENT")
        assert result is None


# ---------------------------------------------------------------------------
# find_by_name
# ---------------------------------------------------------------------------


class TestFindByName:
    """find_by_name() — 按名称模糊查找产品"""

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    @patch("app.infrastructure.repositories.product_repository_impl.product_to_domain")
    def test_found(self, mock_to_domain, mock_get_db, repo):
        """找到产品时返回 domain 列表"""
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
        """未找到产品时返回空列表"""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.find_by_name("不存在")
        assert result == []


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


class TestDelete:
    """delete() — 删除产品"""

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    def test_delete_success(self, mock_get_db, repo):
        """删除存在的产品返回 True"""
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
        """删除不存在的产品返回 False"""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.delete(999)
        assert result is False


# ---------------------------------------------------------------------------
# count
# ---------------------------------------------------------------------------


class TestCount:
    """count() — 统计产品总数"""

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    def test_count_returns_number(self, mock_get_db, repo):
        """返回产品数量"""
        mock_db = MagicMock()
        mock_db.query.return_value.count.return_value = 42
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.count()
        assert result == 42

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    def test_count_zero(self, mock_get_db, repo):
        """无产品时返回 0"""
        mock_db = MagicMock()
        mock_db.query.return_value.count.return_value = 0
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = repo.count()
        assert result == 0


# ---------------------------------------------------------------------------
# find_product_units
# ---------------------------------------------------------------------------


class TestFindProductUnits:
    """find_product_units() — 查询产品单位列表"""

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    def test_fallback_to_products_unit(self, mock_get_db, repo):
        """无 purchase_units 表时从 products 表获取"""
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
        # TRIVIAL_MEASURE_UNITS should be filtered out
        assert "件" not in result
        assert "箱" not in result

    @patch("app.infrastructure.repositories.product_repository_impl.get_db")
    def test_purchase_units_authoritative(self, mock_get_db, repo):
        """purchase_units 表存在时使用权威数据"""
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
        """无单位数据时返回空列表"""
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
        """重复单位去重"""
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
        """None 值被跳过"""
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
        """purchase_units 查询出错时回退到 products 表"""
        mock_db = MagicMock()
        mock_db.bind = MagicMock()
        mock_db.query.return_value.distinct.return_value.all.return_value = [
            ("产品A",),
        ]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        with patch("app.infrastructure.repositories.product_repository_impl.inspect") as mock_insp:
            # First call for purchase_units fails, second for products succeeds
            mock_insp_obj = MagicMock()
            mock_insp_obj.get_table_names.return_value = ["products"]
            mock_insp.return_value = mock_insp_obj

            with patch(
                "app.application.customer_app_service.get_customers_session",
                side_effect=RuntimeError("session error"),
            ):
                result = repo.find_product_units()

        assert isinstance(result, list)
