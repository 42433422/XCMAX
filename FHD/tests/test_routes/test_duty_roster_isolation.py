"""宿主编制只对平台管理员可见，企业账号拿到的必须是空编制。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.fastapi_routes.system_routes import (
    get_duty_roster,
    get_workflow_employee_catalog,
)


def _call(endpoint, **kwargs):
    return asyncio.run(endpoint(user=SimpleNamespace(**kwargs)))


def test_tenant_gets_an_empty_duty_roster():
    body = _call(get_duty_roster, tier="enterprise", role="operator")
    data = body["data"]
    assert body["success"] is True
    assert data["scope"] == "tenant"
    assert data["departments"] == {}
    assert data["all_planned_ids"] == []
    assert data["employee_labels"] == {}


def test_platform_admin_gets_the_real_roster():
    body = _call(get_duty_roster, tier="admin", role="admin")
    data = body["data"]
    assert data["scope"] == "platform"
    assert data["departments"]
    assert data["all_planned_ids"]


def test_tenant_gets_an_empty_employee_catalog():
    body = _call(get_workflow_employee_catalog, tier="enterprise", role="operator")
    assert body["data"]["scope"] == "tenant"
    assert body["data"]["catalog"] == []
