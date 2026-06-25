"""employee_api 模块冒烟（路径解析、路由元数据）。"""

from __future__ import annotations

import os
import types
from unittest.mock import patch

import pytest

import modstore_server.employee_api as employee_api


def test_router_prefix_and_tags() -> None:
    assert employee_api.router.prefix == "/api/employees"
    assert "employees" in employee_api.router.tags


def test_runtime_dir_uses_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path))
    assert employee_api._runtime_dir() == tmp_path


def test_employee_download_jobs_root_creates_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path))
    root = employee_api._employee_download_jobs_root()
    assert root.is_dir()
    assert root.name == "employee_output_downloads"


def test_resolve_taiyangniao_backend_from_env(monkeypatch) -> None:
    with patch.dict(os.environ, {"TAIYANGNIAO_BACKEND_PATH": "/opt/taiyangniao/backend"}):
        data: dict = {}
        employee_api._resolve_taiyangniao_backend(data)
    assert data["taiyangniao_backend_path"] == "/opt/taiyangniao/backend"


@pytest.mark.asyncio
async def test_execute_endpoint_offloads_blocking_employee_runtime(monkeypatch) -> None:
    calls: list[dict] = []

    class Runtime:
        def execute_task(self, **kwargs):
            calls.append(kwargs)
            return {"ok": True}

    offloaded: list[object] = []

    async def fake_run_in_threadpool(func, **kwargs):
        offloaded.append(func)
        return func(**kwargs)

    monkeypatch.setattr(employee_api, "_user_may_execute_employee_pack", lambda *_a: True)
    monkeypatch.setattr(employee_api, "get_default_employee_client", lambda: Runtime())
    monkeypatch.setattr(employee_api, "run_in_threadpool", fake_run_in_threadpool)
    result = await employee_api.execute_employee_task_endpoint(
        "employee-a",
        "只读任务",
        {"dry_run": True},
        db=object(),
        user=types.SimpleNamespace(id=7),
    )
    assert result == {"ok": True}
    assert len(offloaded) == 1
    assert calls == [
        {
            "employee_id": "employee-a",
            "task": "只读任务",
            "input_data": {"dry_run": True},
            "user_id": 7,
        }
    ]
