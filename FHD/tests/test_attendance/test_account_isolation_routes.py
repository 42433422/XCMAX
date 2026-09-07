"""考勤 mod 路由层账号隔离端到端测试（TestClient + 假会话）。

通过 DATABASE_PATH 让 mod 私有库落在 tmp（resolve_mod_private_sqlite_path
优先级 1），以 mod_manager 同款方式加载 blueprints，monkeypatch 会话解析。
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import types
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

MOD_BACKEND = (
    Path(__file__).resolve().parents[2] / "XCAGI" / "mods" / "attendance-industry" / "backend"
)


class _FakeUser:
    def __init__(self, username: str) -> None:
        self.username = username


@pytest.fixture()
def client(tmp_path, monkeypatch):
    state: dict[str, object] = {"user": None}

    import app.infrastructure.auth.dependencies as auth_deps

    monkeypatch.setattr(auth_deps, "resolve_session_user", lambda request: state["user"])

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path))

    backend_text = str(MOD_BACKEND)
    if backend_text not in sys.path:
        sys.path.insert(0, backend_text)

    spec = importlib.util.spec_from_file_location(
        "xcagi_attendance_industry_blueprints", MOD_BACKEND / "blueprints.py"
    )
    assert spec and spec.loader
    bp = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = bp
    spec.loader.exec_module(bp)

    app = FastAPI()
    bp.register_fastapi_routes(app, "attendance-industry")
    test_client = TestClient(app)
    test_client.att_state = state  # type: ignore[attr-defined]
    return test_client


def _login(client, username: str | None) -> None:
    client.att_state["user"] = _FakeUser(username) if username else None  # type: ignore[attr-defined]


def _employees(client):
    return {
        i["employee_name"]
        for i in client.get("/api/mods/attendance-industry/employees").json()["data"]["items"]
    }


def test_unauthenticated_reads_are_empty_and_writes_rejected(client):
    _login(client, None)
    r = client.get("/api/mods/attendance-industry/employees")
    assert r.status_code == 200
    assert r.json()["data"]["items"] == []
    r = client.post("/api/mods/attendance-industry/employees", json={"employee_name": "张三"})
    assert r.status_code == 401


def test_two_accounts_cannot_see_each_other(client):
    _login(client, "SUNBIRD")
    assert (
        client.post(
            "/api/mods/attendance-industry/employees",
            json={"employee_name": "胡超", "department": "计划生产部"},
        ).status_code
        == 200
    )
    _login(client, "wuxinghua1")
    assert (
        client.post(
            "/api/mods/attendance-industry/employees",
            json={"employee_name": "王涂料", "department": "生产部"},
        ).status_code
        == 200
    )

    _login(client, "SUNBIRD")
    assert _employees(client) == {"胡超"}
    _login(client, "wuxinghua1")
    assert _employees(client) == {"王涂料"}


def test_cross_account_update_and_delete_are_404(client):
    _login(client, "SUNBIRD")
    created = client.post(
        "/api/mods/attendance-industry/employees",
        json={"employee_name": "太阳鸟员工", "department": "木工部"},
    ).json()["data"]
    emp_id = created["id"]

    _login(client, "wuxinghua1")
    assert (
        client.put(
            f"/api/mods/attendance-industry/employees/{emp_id}",
            json={"employee_name": "改名", "department": "木工部"},
        ).status_code
        == 404
    )
    assert client.delete(f"/api/mods/attendance-industry/employees/{emp_id}").status_code == 404

    _login(client, "SUNBIRD")
    assert _employees(client) == {"太阳鸟员工"}


def test_departments_isolated_per_account(client):
    _login(client, "SUNBIRD")
    assert (
        client.post(
            "/api/mods/attendance-industry/departments", json={"department": "计划生产部"}
        ).status_code
        == 200
    )
    _login(client, "wuxinghua1")
    # 不同账号可建同名部门（唯一性按账号内判定）
    assert (
        client.post(
            "/api/mods/attendance-industry/departments", json={"department": "计划生产部"}
        ).status_code
        == 200
    )
    assert client.get("/api/mods/attendance-industry/departments").json()["data"]["total"] == 1
    _login(client, "SUNBIRD")
    assert client.get("/api/mods/attendance-industry/departments").json()["data"]["total"] == 1


def test_legacy_rows_belong_to_sunbird_after_migration(client):
    """旧库（无 owner 列）经迁移后存量归属太阳鸟；其它账号看不到。"""
    import os

    db_path = Path(os.environ["DATABASE_PATH"]) / "mod_dbs" / "taiyangniao_pro.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # 手工建「旧 schema」：完全没有 owner_user_id 列，模拟已交付太阳鸟库
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE attendance_employees ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, source_file TEXT NOT NULL DEFAULT 'manual', "
        "employee_name TEXT NOT NULL, department TEXT NOT NULL DEFAULT '', "
        "main_department TEXT NOT NULL DEFAULT '', attendance_group TEXT NOT NULL DEFAULT '', "
        "employee_no TEXT NOT NULL DEFAULT '', position TEXT NOT NULL DEFAULT '', "
        "user_id TEXT NOT NULL DEFAULT '', UNIQUE(source_file, employee_name, department))"
    )
    conn.execute(
        "INSERT INTO attendance_employees (source_file, employee_name, department) "
        "VALUES ('seed', '老数据', '综合部')"
    )
    conn.commit()
    conn.close()

    _login(client, "SUNBIRD")
    assert _employees(client) == {"老数据"}  # 迁移触发 + 归属太阳鸟
    _login(client, "wuxinghua1")
    assert _employees(client) == set()


def test_module_surface_sanity():
    """blueprints 以包外路径加载时，owner_scope 顶层回退 import 必须可用。"""
    backend_text = str(MOD_BACKEND)
    if backend_text not in sys.path:
        sys.path.insert(0, backend_text)
    spec = importlib.util.spec_from_file_location(
        "att_owner_scope_smoke", MOD_BACKEND / "owner_scope.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.LEGACY_OWNER_USERNAME == "SUNBIRD"
    assert callable(mod.owner_from_request)
    assert callable(mod.migrate_owner_column)
    _ = types  # keep import used marker
