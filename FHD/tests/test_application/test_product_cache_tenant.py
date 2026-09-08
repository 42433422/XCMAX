from unittest.mock import Mock, patch

import pytest

from app.infrastructure.tenant_scope import tenant_scope
from app.services.products_service import ProductsService


def test_product_cache_does_not_serve_another_tenants_product():
    repository = Mock()
    repository.find_by_id.side_effect = [{"name": "租户一产品"}, None]
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
    values = {}
    cache = Mock()
    cache.get.side_effect = values.get
    cache.set.side_effect = lambda key, value, **kwargs: values.update({key: value})
    service._cache = cache
    with tenant_scope(1):
        assert service.get_product(1)["success"]
        assert service.get_product(1)["success"]
    with tenant_scope(2):
        assert not service.get_product(1)["success"]
    assert repository.find_by_id.call_count == 2
    with tenant_scope(1):
        service._invalidate_single_product_cache(1)
    cache.delete.assert_called_once_with(next(iter(values)))


def test_product_update_refreshes_lists_only_for_current_tenant():
    import fnmatch

    repository = Mock()
    repository.find_all.side_effect = [([{"name": "旧名称"}], 1), ([{"name": "新名称"}], 1)]
    repository.update.return_value = {"success": True}
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
    values = {}
    cache = Mock()
    cache.get.side_effect = values.get
    cache.set.side_effect = lambda key, value, **kwargs: values.update({key: value})
    cache.delete.side_effect = lambda key: values.pop(key, None)

    def clear(pattern):
        for key in list(values):
            if fnmatch.fnmatchcase(key, pattern):
                del values[key]

    cache.clear_pattern.side_effect = clear
    service._cache = cache
    with tenant_scope(2):
        foreign_key = service._tenant_cache_key("products:list:foreign")
        values[foreign_key] = "其他租户缓存"
    with tenant_scope(1):
        assert service.get_products()["data"][0]["name"] == "旧名称"
        assert service.update_product(1, {"name": "新名称"})["success"]
        assert service.get_products()["data"][0]["name"] == "新名称"
    assert values[foreign_key] == "其他租户缓存"
    assert repository.find_all.call_count == 2


@pytest.mark.parametrize(
    "method, repository_method, first, second",
    [
        ("get_products", "find_all", ([{"name": "A"}], 1), ([{"name": "B"}], 1)),
        ("get_product_units", "find_product_units", ["A"], ["B"]),
        ("get_product_names", "find_names", ["A"], ["B"]),
    ],
)
def test_collection_caches_are_separate_between_tenants(method, repository_method, first, second):
    repository = Mock()
    getattr(repository, repository_method).side_effect = [first, second]
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
    values = {}
    cache = Mock()
    cache.get.side_effect = values.get
    cache.set.side_effect = lambda key, value, **kwargs: values.update({key: value})
    service._cache = cache
    with tenant_scope(1):
        first_result = getattr(service, method)()
        assert getattr(service, method)() == first_result
    with tenant_scope(2):
        second_result = getattr(service, method)()
    assert first_result["data"] != second_result["data"]
    assert getattr(repository, repository_method).call_count == 2
