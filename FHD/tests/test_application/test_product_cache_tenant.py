from unittest.mock import Mock, patch

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
