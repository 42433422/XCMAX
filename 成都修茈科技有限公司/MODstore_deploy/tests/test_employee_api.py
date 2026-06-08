"""employee_api 模块冒烟（路径解析、路由元数据）。"""

from __future__ import annotations

import os
from unittest.mock import patch

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
