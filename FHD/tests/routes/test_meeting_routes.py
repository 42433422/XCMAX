"""会议纪要 API 路由：Web + 移动镜像端点（薄层，应用服务被打桩）。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.mod_sdk  # noqa: F401  # 预热 app.services 包，规避隔离运行时已知的循环导入
from app.fastapi_routes.meeting_routes import mobile_router, router

_RECORD = {
    "id": 1,
    "title": "周会",
    "status": "completed",
    "source_hash": "h",
    "level1_script": "【张三】：下周上线。",
    "level2_architecture": "```mermaid\nflowchart TD\nA-->B\n```",
    "level3_plain": "说白了：下周上线。",
}


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.include_router(mobile_router)
    return TestClient(app, raise_server_exceptions=False)


def _fake_svc() -> SimpleNamespace:
    return SimpleNamespace(
        create_and_generate=AsyncMock(return_value=_RECORD),
        get_minute=MagicMock(return_value=_RECORD),
        list_minutes=MagicMock(return_value={"items": [_RECORD], "page": 1, "per_page": 20}),
    )


class TestWebRoutes:
    def test_levels(self, client):
        r = client.get("/api/meetings/levels")
        assert r.status_code == 200
        ids = [lvl["id"] for lvl in r.json()["data"]["levels"]]
        assert ids == ["level1_script", "level2_architecture", "level3_plain"]

    def test_generate_all(self, client):
        with patch("app.fastapi_routes.meeting_routes._svc", return_value=_fake_svc()):
            r = client.post("/api/meetings/generate-all", json={"raw_transcript": "张三：上线。"})
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["level1_script"] and body["data"]["level2_architecture"]
        assert body["data"]["level3_plain"]

    def test_generate_all_rejects_empty(self, client):
        r = client.post("/api/meetings/generate-all", json={"raw_transcript": "   "})
        assert r.status_code == 400

    def test_get_one(self, client):
        with patch("app.fastapi_routes.meeting_routes._svc", return_value=_fake_svc()):
            r = client.get("/api/meetings/1")
        assert r.status_code == 200
        assert r.json()["data"]["id"] == 1

    def test_get_one_404(self, client):
        svc = _fake_svc()
        svc.get_minute = MagicMock(return_value=None)
        with patch("app.fastapi_routes.meeting_routes._svc", return_value=svc):
            r = client.get("/api/meetings/999")
        assert r.status_code == 404

    def test_list(self, client):
        with patch("app.fastapi_routes.meeting_routes._svc", return_value=_fake_svc()):
            r = client.get("/api/meetings")
        assert r.status_code == 200
        assert r.json()["data"]["items"][0]["id"] == 1


class TestMobileRoutes:
    def test_mobile_generate_unauthorized(self, client):
        with patch("app.fastapi_routes.meeting_routes._mobile_uid", return_value=None):
            r = client.post("/api/mobile/v1/meetings/generate-all", json={"raw_transcript": "x"})
        assert r.status_code == 200  # 统一壳，错误在 body
        assert r.json()["success"] is False
        assert r.json()["code"] == 401

    def test_mobile_generate_ok(self, client):
        with (
            patch("app.fastapi_routes.meeting_routes._mobile_uid", return_value=7),
            patch("app.fastapi_routes.meeting_routes._svc", return_value=_fake_svc()),
        ):
            r = client.post(
                "/api/mobile/v1/meetings/generate-all",
                json={"raw_transcript": "张三：上线。"},
                headers={"Authorization": "Bearer faketoken"},
            )
        body = r.json()
        assert body["success"] is True
        assert body["data"]["level2_architecture"]

    def test_mobile_levels(self, client):
        r = client.get("/api/mobile/v1/meetings/levels")
        assert r.json()["success"] is True
        assert len(r.json()["data"]["levels"]) == 3


def test_routers_registered_in_business_mount():
    """锁定挂载接线：register_business_routes 注册 web + mobile 两个会议路由。"""
    from fastapi import FastAPI

    from app.fastapi_routes.mounts.business import register_business_routes
    from app.fastapi_routes.registry import RouteRegistry

    registry = RouteRegistry()
    register_business_routes(FastAPI(), registry)
    names = registry.names()
    assert "meetings" in names
    assert "meetings_mobile" in names
