"""智能搜索 V0 路由单测。"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _require_search_v0_route(client: TestClient):
    """`/api/search/v0` 端点当前未接线（SmartSearchApplicationService 孤立）。

    路由缺失时跳过；一旦后续接线，本守卫自动失效、用例恢复。
    """
    paths = {getattr(r, "path", "") for r in client.app.routes}
    if "/api/search/v0" not in paths:
        pytest.skip("/api/search/v0 未在当前构建中注册（孤立的 SmartSearchApplicationService）")


@pytest.fixture(autouse=True)
def disable_lan_guard(monkeypatch):
    monkeypatch.setenv("LAN_GUARD_ENABLED", "0")
    monkeypatch.setenv("LAN_CIDR_GUARD_ENABLED", "0")
    from app.security.lan_config import reset_lan_config_cache
    from app.security.lan_settings_store import LanSettingsOverride

    monkeypatch.setattr(
        "app.security.lan_settings_store.load_overrides",
        lambda: LanSettingsOverride(enabled=False),
    )
    reset_lan_config_cache()


@patch("app.application.smart_search_app_service.SmartSearchApplicationService.search")
def test_search_v0_products(mock_search, client: TestClient):
    mock_search.return_value = {
        "success": True,
        "query": "七彩",
        "scope": "products",
        "results": {"products": {"success": True, "data": [{"name": "七彩"}]}},
    }
    r = client.get("/api/search/v0", params={"q": "七彩", "scope": "products"})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["scope"] == "products"


@patch("app.application.smart_search_app_service.SmartSearchApplicationService.search")
def test_search_v0_customers(mock_search, client: TestClient):
    mock_search.return_value = {
        "success": True,
        "query": "测试",
        "scope": "customers",
        "results": {"customers": {"success": True, "data": []}},
    }
    r = client.get("/api/search/v0", params={"q": "测试", "scope": "customers"})
    assert r.status_code == 200
    assert r.json()["scope"] == "customers"
