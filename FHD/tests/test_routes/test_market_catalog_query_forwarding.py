"""Catalog operations retain pagination/filter semantics through the host gateway."""

import asyncio
from unittest.mock import AsyncMock

from starlette.requests import Request

from app.fastapi_routes.admin_control.market_gateway import MarketGateway


def test_catalog_query_reaches_upstream_without_changing_authorized_path():
    proxy = AsyncMock(return_value={"items": [], "total": 0})
    gateway = MarketGateway(errors=(), gate=None, proxy=proxy, maintenance=None, transport=None)
    query = b"limit=50&offset=100&status=pending&search=%E5%90%88%E5%90%8C"
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/market/admin/catalog",
            "query_string": query,
            "headers": [],
        }
    )
    asyncio.run(gateway._xcmax_market_proxy_impl(request, "admin/catalog"))
    proxy.assert_awaited_once_with(
        request, "GET", "/api/admin/catalog?" + query.decode(), json_body=None
    )


def test_market_item_download_uses_authorized_market_route_not_public_record():
    from app.infrastructure.mods.catalog_client import market_item_to_package_row

    item = {"id": 42, "pkg_id": "market-only", "version": "1.0.0"}
    assert market_item_to_package_row(item)["download_url"] == "/api/market/catalog/42/download"
    item.pop("id")
    assert (
        market_item_to_package_row(item)["download_url"]
        == "/v1/packages/market-only/1.0.0/download"
    )
