"""移动端统一任务只读接口（P0 合流）单测。"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.mobile_extensions.routes_tasks import (
    TaskRoutes,
    TaskRoutesPorts,
    task_summary,
)


class _FakeTask:
    def __init__(self, **overrides: Any) -> None:
        self._payload = {
            "task_id": "task-1",
            "title": "整理本周考勤",
            "status": "running",
            "attention_state": "",
            "approval_required": False,
            "workspace_id": "desktop:mac-1",
            "workspace_isolation": "business_workspace",
            "conversation_id": "employee:attendance",
            "metadata": {"execution_target": "desktop:mac-1"},
            "progress": {"percent": 42},
            "updated_at": "2026-11-13T10:00:00",
        }
        self._payload.update(overrides)

    def to_dict(self) -> dict[str, Any]:
        return dict(self._payload)


class _FakeUser:
    id = 39
    tenant_id = "tenant-a"


def _client(ports: TaskRoutesPorts) -> TestClient:
    app = FastAPI()
    routes = TaskRoutes(ports, lambda: _FakeUser())
    app.include_router(routes.router, prefix="/api/mobile/v1")
    return TestClient(app)


def test_task_summary_exposes_display_fields_only() -> None:
    summary = task_summary(_FakeTask())
    assert summary["task_id"] == "task-1"
    assert summary["execution_target"] == "desktop:mac-1"
    assert summary["progress_percent"] == 42
    assert "user_id" not in summary
    assert "tenant_id" not in summary


def test_task_list_scopes_to_current_user_and_tenant() -> None:
    captured: dict[str, Any] = {}

    def _list_tasks(**kwargs: Any) -> list[Any]:
        captured.update(kwargs)
        return [_FakeTask()]

    client = _client(
        TaskRoutesPorts(
            list_tasks=_list_tasks,
            get_task=lambda **_: None,
        )
    )
    response = client.get("/api/mobile/v1/tasks?limit=20")
    body = response.json()

    assert response.status_code == 200
    assert body["success"] is True
    assert body["data"]["count"] == 1
    assert body["data"]["items"][0]["title"] == "整理本周考勤"
    assert captured == {
        "user_id": "39",
        "tenant_id": "tenant-a",
        "limit": 20,
        "include_archived": False,
    }


def test_task_detail_returns_not_found_for_other_tenant() -> None:
    client = _client(
        TaskRoutesPorts(
            list_tasks=lambda **_: [],
            get_task=lambda **_: None,
        )
    )
    response = client.get("/api/mobile/v1/tasks/task-missing")
    assert response.status_code == 404
    assert response.json()["message"] == "任务不存在或无权查看"
