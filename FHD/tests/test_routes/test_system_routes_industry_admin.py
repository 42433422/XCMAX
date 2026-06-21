"""POST /api/system/industry admin-only 测试（Task 7）。

验证：
- 普通用户（tier != "admin"）调用 POST /api/system/industry 返回 403
- admin 用户（tier == "admin"）调用返回 200
- 未登录用户返回 401
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes import system_routes


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(system_routes.router)
    return TestClient(app, raise_server_exceptions=False)


def _make_user(tier: str = "personal", industry_id: str = "通用"):
    return SimpleNamespace(
        id=1,
        username="tester",
        tier=tier,
        industry_id=industry_id,
        is_active=True,
        role="user",
    )


class TestSetIndustryAdminOnly:
    """POST /api/system/industry 仅限 admin。"""

    def test_personal_user_gets_403(self, client: TestClient):
        """普通用户（tier=personal）应返回 403。"""
        fake_user = _make_user(tier="personal")
        with patch(
            "app.infrastructure.auth.dependencies.resolve_session_user",
            return_value=fake_user,
        ):
            resp = client.post("/api/system/industry", json={"industry_id": "涂料"})
        assert resp.status_code == 403
        body = resp.json()
        assert body["detail"]["message"]["code"] == "ADMIN_ONLY"

    def test_enterprise_user_gets_403(self, client: TestClient):
        """企业用户（tier=enterprise）应返回 403。"""
        fake_user = _make_user(tier="enterprise")
        with patch(
            "app.infrastructure.auth.dependencies.resolve_session_user",
            return_value=fake_user,
        ):
            resp = client.post("/api/system/industry", json={"industry_id": "涂料"})
        assert resp.status_code == 403

    def test_admin_user_gets_200(self, client: TestClient):
        """admin 用户（tier=admin）应返回 200。"""
        fake_admin = _make_user(tier="admin")
        with patch(
            "app.infrastructure.auth.dependencies.resolve_session_user",
            return_value=fake_admin,
        ), patch(
            "resources.config.industry_config.set_current_industry",
            return_value=True,
        ), patch(
            "resources.config.industry_config.get_industry_profile",
            return_value=SimpleNamespace(
                name="涂料",
                units={},
                quantity_fields={},
                product_fields={},
                order_types={},
                intent_keywords={},
                print_config={},
            ),
        ):
            resp = client.post("/api/system/industry", json={"industry_id": "涂料"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True

    def test_unauthenticated_user_gets_401(self, client: TestClient):
        """未登录用户应返回 401。"""
        with patch(
            "app.infrastructure.auth.dependencies.resolve_session_user",
            return_value=None,
        ):
            resp = client.post("/api/system/industry", json={"industry_id": "涂料"})
        assert resp.status_code == 401
