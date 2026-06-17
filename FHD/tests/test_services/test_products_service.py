"""Tests for app.services.products_service — extended coverage."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.products_service import ProductsService


@pytest.fixture
def mock_repo():
    return MagicMock()


@pytest.fixture
def service(mock_repo):
    svc = ProductsService(repository=mock_repo)
    svc._cache = None
    svc._monitor = None
    svc._query_optimizer = None
    return svc


# ---------------------------------------------------------------------------
# _normalize_find_all_result
# ---------------------------------------------------------------------------


class TestNormalizeFindAllResult:
    def test_tuple_result(self):
        row = MagicMock()
        result = ProductsService._normalize_find_all_result(([row], 5))
        assert result == ([row], 5)

    def test_tuple_with_none(self):
        result = ProductsService._normalize_find_all_result((None, 0))
        assert result == ([], 0)

    def test_dict_result_with_total(self):
        result = ProductsService._normalize_find_all_result({"data": [{"id": 1}], "total": 1})
        assert result == ([{"id": 1}], 1)

    def test_dict_result_with_count(self):
        result = ProductsService._normalize_find_all_result({"data": [{"id": 1}], "count": 1})
        assert result == ([{"id": 1}], 1)

    def test_dict_result_no_total_no_count(self):
        result = ProductsService._normalize_find_all_result({"data": [{"id": 1}, {"id": 2}]})
        assert result == ([{"id": 1}, {"id": 2}], 2)

    def test_list_result(self):
        result = ProductsService._normalize_find_all_result([1, 2, 3])
        assert result == ([1, 2, 3], 3)

    def test_unknown_type(self):
        result = ProductsService._normalize_find_all_result(42)
        assert result == ([], 0)

    def test_empty_dict(self):
        result = ProductsService._normalize_find_all_result({})
        assert result == ([], 0)


# ---------------------------------------------------------------------------
# get_products
# ---------------------------------------------------------------------------


class TestGetProducts:
    def test_no_repository(self, mock_repo):
        svc = ProductsService(repository=mock_repo)
        svc._repository = None
        result = svc.get_products()
        assert result["success"] is False

    def test_with_cache_hit(self, service, mock_repo):
        mock_cache = MagicMock()
        cached_result = {"success": True, "data": [], "total": 0, "_cached": True}
        mock_cache.get.return_value = cached_result
        service._cache = mock_cache
        result = service.get_products(page=1)
        assert result["_cached"] is True
        mock_repo.find_all.assert_not_called()

    def test_with_cache_miss(self, service, mock_repo):
        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        service._cache = mock_cache
        row = MagicMock()
        row.to_dict.return_value = {"id": 1, "name": "A"}
        mock_repo.find_all.return_value = ([row], 1)
        result = service.get_products(page=1)
        assert result["success"] is True
        assert result["total"] == 1

    def test_with_monitor(self, service, mock_repo):
        mock_monitor = MagicMock()
        service._monitor = mock_monitor
        mock_repo.find_all.return_value = ([], 0)
        result = svc_get_products(service)
        mock_monitor.record_metric.assert_called_once()

    def test_dict_result_without_to_dict(self, service, mock_repo):
        # When find_all returns a tuple (list_of_products, total), products without
        # to_dict are kept as-is. A dict in the list is preserved as a dict.
        mock_repo.find_all.return_value = ([{"id": 1}], 1)
        result = service.get_products()
        assert result["data"] == [{"id": 1}]


def svc_get_products(service, **kwargs):
    return service.get_products(**kwargs)


# ---------------------------------------------------------------------------
# get_product_units
# ---------------------------------------------------------------------------


class TestGetProductUnits:
    def test_no_repository(self, mock_repo):
        svc = ProductsService(repository=mock_repo)
        svc._repository = None
        result = svc.get_product_units()
        assert result["success"] is False

    def test_returns_units(self, service, mock_repo):
        mock_repo.find_product_units.return_value = ["unit_a", "unit_b"]
        result = service.get_product_units()
        assert result["success"] is True
        assert result["count"] == 2

    def test_with_cache(self, service, mock_repo):
        mock_cache = MagicMock()
        mock_cache.get.return_value = {"success": True, "data": ["cached"], "count": 1}
        service._cache = mock_cache
        result = service.get_product_units()
        assert result["data"] == ["cached"]


# ---------------------------------------------------------------------------
# get_product
# ---------------------------------------------------------------------------


class TestGetProduct:
    def test_no_repository(self, mock_repo):
        svc = ProductsService(repository=mock_repo)
        svc._repository = None
        result = svc.get_product(1)
        assert result["success"] is False

    def test_product_not_found(self, service, mock_repo):
        mock_repo.find_by_id.return_value = None
        result = service.get_product(999)
        assert result["success"] is False
        assert result["message"] == "产品不存在"

    def test_product_found(self, service, mock_repo):
        mock_repo.find_by_id.return_value = {"id": 1, "name": "A"}
        result = service.get_product(1)
        assert result["success"] is True


# ---------------------------------------------------------------------------
# create_product
# ---------------------------------------------------------------------------


class TestCreateProduct:
    def test_no_repository(self, mock_repo):
        svc = ProductsService(repository=mock_repo)
        svc._repository = None
        result = svc.create_product({})
        assert result["success"] is False

    def test_create_success(self, service, mock_repo):
        mock_product = MagicMock()
        mock_product.to_dict.return_value = {"id": 1, "name": "A"}
        mock_repo.create.return_value = mock_product
        # Product, Money, ModelNumber are imported inside create_product from
        # app.domain.product.entities and app.domain.value_objects
        with patch("app.domain.product.entities.Product", return_value=mock_product), \
             patch("app.domain.value_objects.Money", return_value=MagicMock()), \
             patch("app.domain.value_objects.ModelNumber", return_value=MagicMock()):
            result = service.create_product({"name": "A", "product_code": "X1"})
        assert result["success"] is True

    def test_create_error(self, service, mock_repo):
        mock_repo.create.side_effect = RuntimeError("db error")
        with patch("app.domain.product.entities.Product", side_effect=RuntimeError("fail")), \
             patch("app.domain.value_objects.Money", return_value=MagicMock()):
            result = service.create_product({"name": "A"})
        assert result["success"] is False


# ---------------------------------------------------------------------------
# update_product
# ---------------------------------------------------------------------------


class TestUpdateProduct:
    def test_no_repository(self, mock_repo):
        svc = ProductsService(repository=mock_repo)
        svc._repository = None
        result = svc.update_product(1, {})
        assert result["success"] is False

    def test_update_success(self, service, mock_repo):
        mock_repo.update.return_value = {"success": True}
        result = service.update_product(1, {"name": "B"})
        assert result == {"success": True}


# ---------------------------------------------------------------------------
# delete_product
# ---------------------------------------------------------------------------


class TestDeleteProduct:
    def test_no_repository(self, mock_repo):
        svc = ProductsService(repository=mock_repo)
        svc._repository = None
        result = svc.delete_product(1)
        assert result["success"] is False

    def test_delete_success(self, service, mock_repo):
        mock_repo.delete.return_value = True
        result = service.delete_product(1)
        assert result["success"] is True

    def test_delete_failure(self, service, mock_repo):
        mock_repo.delete.return_value = False
        result = service.delete_product(1)
        assert result["success"] is False


# ---------------------------------------------------------------------------
# batch_add_products
# ---------------------------------------------------------------------------


class TestBatchAddProducts:
    def test_no_repository(self, mock_repo):
        svc = ProductsService(repository=mock_repo)
        svc._repository = None
        result = svc.batch_add_products([])
        assert result["success"] is False

    def test_batch_with_optimizer(self, service, mock_repo):
        mock_optimizer = MagicMock()
        mock_result = MagicMock()
        mock_result.success_count = 5
        mock_result.failed_count = 0
        mock_result.errors = []
        mock_optimizer.batch_execute.return_value = mock_result
        service._query_optimizer = mock_optimizer
        mock_repo.create_from_dict = MagicMock()
        result = service.batch_add_products([{"name": f"P{i}"} for i in range(15)])
        assert result["success"] is True

    def test_batch_without_optimizer(self, service, mock_repo):
        mock_repo.batch_create.return_value = {"success": True}
        result = service.batch_add_products([{"name": "P1"}])
        assert result["success"] is True

    def test_batch_error(self, service, mock_repo):
        mock_repo.batch_create.side_effect = RuntimeError("fail")
        result = service.batch_add_products([{"name": "P1"}])
        assert result["success"] is False


def svc_batch_add(service, data):
    return service.batch_add_products(data)


# ---------------------------------------------------------------------------
# batch_delete_products
# ---------------------------------------------------------------------------


class TestBatchDeleteProducts:
    def test_no_repository(self, mock_repo):
        svc = ProductsService(repository=mock_repo)
        svc._repository = None
        result = svc.batch_delete_products([1, 2])
        assert result["success"] is False

    def test_batch_delete_with_monitor(self, service, mock_repo):
        mock_monitor = MagicMock()
        service._monitor = mock_monitor
        mock_repo.batch_delete.return_value = {"success": True}
        result = service.batch_delete_products([1, 2])
        mock_monitor.record_metric.assert_called_once()


# ---------------------------------------------------------------------------
# get_product_names
# ---------------------------------------------------------------------------


class TestGetProductNames:
    def test_no_repository(self, mock_repo):
        svc = ProductsService(repository=mock_repo)
        svc._repository = None
        result = svc.get_product_names()
        assert result["success"] is False

    def test_returns_names(self, service, mock_repo):
        mock_repo.find_names.return_value = ["A", "B"]
        result = service.get_product_names(keyword="A")
        assert result["success"] is True
        assert result["count"] == 2


# ---------------------------------------------------------------------------
# export_to_excel
# ---------------------------------------------------------------------------


class TestExportToExcel:
    def test_no_repository(self, mock_repo):
        svc = ProductsService(repository=mock_repo)
        svc._repository = None
        result = svc.export_to_excel()
        assert result["success"] is False

    def test_export_with_monitor(self, service, mock_repo):
        mock_monitor = MagicMock()
        service._monitor = mock_monitor
        mock_repo.export_to_excel.return_value = {"success": True}
        result = service.export_to_excel()
        mock_monitor.record_metric.assert_called_once()


# ---------------------------------------------------------------------------
# _product_exists
# ---------------------------------------------------------------------------


class TestProductExists:
    def test_no_repository(self, mock_repo):
        svc = ProductsService(repository=mock_repo)
        svc._repository = None
        assert svc._product_exists(1) is False

    def test_exists(self, service, mock_repo):
        mock_repo.exists.return_value = True
        assert service._product_exists(1) is True


# ---------------------------------------------------------------------------
# set_repository
# ---------------------------------------------------------------------------


class TestSetRepository:
    def test_set_repository_clears_cache(self, mock_repo):
        svc = ProductsService(repository=mock_repo)
        mock_cache = MagicMock()
        svc._cache = mock_cache
        new_repo = MagicMock()
        svc.set_repository(new_repo)
        assert svc._repository is new_repo
        mock_cache.clear_pattern.assert_called()


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------


class TestCacheInvalidation:
    def test_invalidate_product_cache_no_cache(self, service):
        service._cache = None
        service._invalidate_product_cache()  # Should not raise

    def test_invalidate_product_cache_error(self, service):
        mock_cache = MagicMock()
        mock_cache.clear_pattern.side_effect = RuntimeError("cache error")
        service._cache = mock_cache
        service._invalidate_product_cache()  # Should not raise

    def test_invalidate_single_product_cache(self, service):
        mock_cache = MagicMock()
        service._cache = mock_cache
        service._invalidate_single_product_cache(1)
        mock_cache.delete.assert_called_once_with("product:1")

    def test_invalidate_single_product_cache_error(self, service):
        mock_cache = MagicMock()
        mock_cache.delete.side_effect = RuntimeError("err")
        service._cache = mock_cache
        service._invalidate_single_product_cache(1)  # Should not raise
