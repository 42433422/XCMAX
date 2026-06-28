"""/contacts/fixed 端点集成守卫:完整路径 + 端 gating 真生效。"""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock

import pytest


def _ext():
    if "app.fastapi_routes.mobile_api_extensions" not in sys.modules:
        from app.fastapi_routes import mobile_api  # noqa: F401  触发子路由加载
    return sys.modules["app.fastapi_routes.mobile_api_extensions"]


def _user():
    u = MagicMock()
    u.id = 1
    u.username = "tester"
    return u


def _payload(result):
    if hasattr(result, "body"):
        return json.loads(result.body)
    return result


@pytest.mark.asyncio
async def test_fixed_unauthorized_401():
    ext = _ext()
    result = await ext.get_mobile_fixed_contacts(request=MagicMock(), user=None)
    assert result.status_code == 401


@pytest.mark.asyncio
async def test_fixed_enterprise_has_cs(monkeypatch):
    ext = _ext()
    monkeypatch.setattr(ext, "_mobile_group_mode", lambda request: "enterprise")
    data = _payload(await ext.get_mobile_fixed_contacts(request=MagicMock(), user=_user()))["data"]
    assert data["side"] == "enterprise"
    assert [e["kind"] for e in data["top"]] == ["assistant", "dedicated_cs"]
    # 超级员工仅管理端开放：企业端固定区 bottom 不含 super
    assert all(e["kind"] != "super" for e in data["bottom"])


@pytest.mark.asyncio
async def test_fixed_admin_no_cs(monkeypatch):
    ext = _ext()
    monkeypatch.setattr(ext, "_mobile_group_mode", lambda request: "admin")
    data = _payload(await ext.get_mobile_fixed_contacts(request=MagicMock(), user=_user()))["data"]
    assert data["side"] == "admin"
    kinds = [e["kind"] for e in data["top"]] + [e["kind"] for e in data["bottom"]]
    assert "dedicated_cs" not in kinds
    assert "assistant" in kinds
