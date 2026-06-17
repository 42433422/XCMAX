"""production_line_event_api — 时间轨/事件轨 HTTP 路由烟测。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.production_line_event_api import admin_router, xcmax_router


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(xcmax_router)
    return TestClient(app)


def test_event_rail_status(client: TestClient) -> None:
    with patch(
        "app.fastapi_routes.production_line_event_api.get_six_line_event_app_service",
        return_value=MagicMock(status_snapshot=lambda: {"operations_routes": 12}),
    ):
        r = client.get("/api/admin/production-line/event-rail/status")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["operations_routes"] == 12


def test_event_rail_backlog(client: TestClient) -> None:
    with patch(
        "app.fastapi_routes.production_line_event_api.get_six_line_event_app_service",
        return_value=MagicMock(list_backlog_for_digest=lambda limit: [{"id": "x"}]),
    ):
        r = client.get("/api/xcmax/production-line/event-rail/backlog?limit=1")
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["count"] == 1


def test_time_rail_graph(client: TestClient) -> None:
    fake = MagicMock(graph_payload=lambda: {"ok": True, "nodes": []})
    with patch(
        "app.application.time_rail_app_service.get_time_rail_app_service",
        return_value=fake,
    ):
        r = client.get("/api/admin/production-line/time-rail/graph")
    assert r.status_code == 200
    assert r.json()["data"]["ok"] is True


@pytest.mark.asyncio
async def test_time_rail_maintenance_sync_route_reads_body_limit(client: TestClient) -> None:
    fake = MagicMock()
    fake.maintenance_sync = AsyncMock(return_value={"ok": True, "added": 2})
    with patch(
        "app.application.time_rail_app_service.get_time_rail_app_service",
        return_value=fake,
    ):
        r = client.post(
            "/api/admin/production-line/time-rail/maintenance/sync",
            json={"limit": 7},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    fake.maintenance_sync.assert_awaited_once_with(limit=7)


@pytest.mark.asyncio
async def test_time_rail_status_route(client: TestClient) -> None:
    fake = MagicMock()
    fake.runtime_status = AsyncMock(return_value={"nodes": {}, "degraded": False})
    with patch(
        "app.application.time_rail_app_service.get_time_rail_app_service",
        return_value=fake,
    ):
        r = client.get("/api/xcmax/production-line/time-rail/status?node_id=P1")
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_post_event_dispatch(client: TestClient) -> None:
    with patch(
        "app.fastapi_routes.production_line_event_api.get_six_line_event_app_service",
        return_value=MagicMock(dispatch=lambda body: {"matched": True, "action": "noop"}),
    ):
        r = client.post(
            "/api/admin/production-line/event",
            json={"step_id": "O1", "status": "completed"},
        )
    assert r.status_code == 200
    assert r.json()["data"]["matched"] is True
