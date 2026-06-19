from __future__ import annotations

import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.xcmax_personnel_compat import (
    MOD_ID,
    register_xcmax_personnel_routes,
)


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path))
    app = FastAPI()
    register_xcmax_personnel_routes(app)
    return TestClient(app)


def _seed_db(tmp_path) -> None:
    db_dir = tmp_path / "mod_dbs"
    db_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_dir / "taiyangniao_pro.db"))
    conn.executescript(
        """
        CREATE TABLE attendance_employees (
            id INTEGER PRIMARY KEY,
            employee_name TEXT,
            department TEXT,
            main_department TEXT,
            attendance_group TEXT,
            employee_no TEXT,
            position TEXT,
            user_id TEXT
        );
        CREATE TABLE attendance_departments (
            id INTEGER PRIMARY KEY,
            department TEXT,
            main_department TEXT,
            attendance_group TEXT
        );
        """
    )
    conn.executemany(
        """
        INSERT INTO attendance_employees
            (id, employee_name, department, main_department, attendance_group, employee_no, position, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (1, "胡超", "计划生产部", "计划生产部", "计时", "E001", "计时", "u1"),
            (2, "樊琪麒", "质检部", "质检部", "计时", "E002", "质检", "u2"),
        ],
    )
    conn.executemany(
        """
        INSERT INTO attendance_departments (id, department, main_department, attendance_group)
        VALUES (?, ?, ?, ?)
        """,
        [
            (1, "计划生产部", "计划生产部", "计时"),
            (2, "质检部", "质检部", "计时"),
        ],
    )
    conn.commit()
    conn.close()


def test_xcmax_personnel_employees_returns_empty_without_tables(tmp_path, monkeypatch) -> None:
    db_dir = tmp_path / "mod_dbs"
    db_dir.mkdir(parents=True, exist_ok=True)
    (db_dir / "taiyangniao_pro.db").touch()
    client = _client(tmp_path, monkeypatch)

    resp = client.get(f"/api/mod/{MOD_ID}/employees")

    assert resp.status_code == 200
    assert resp.json()["data"] == {"items": [], "total": 0, "page": 1, "page_size": 50}


def test_xcmax_personnel_employees_reads_taiyangniao_mirror(tmp_path, monkeypatch) -> None:
    _seed_db(tmp_path)
    client = _client(tmp_path, monkeypatch)

    resp = client.get(f"/api/mod/{MOD_ID}/employees", params={"page_size": 1, "search": "计划"})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    assert payload["data"]["total"] == 1
    assert payload["data"]["items"][0]["employee_name"] == "胡超"


def test_xcmax_personnel_departments_reads_taiyangniao_mirror(tmp_path, monkeypatch) -> None:
    _seed_db(tmp_path)
    client = _client(tmp_path, monkeypatch)

    resp = client.get(f"/api/mod/{MOD_ID}/departments", params={"search": "质检"})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["data"]["total"] == 1
    assert payload["data"]["items"][0]["department"] == "质检部"


def test_xcmax_personnel_sync_remote_yuangon_returns_current_counts(tmp_path, monkeypatch) -> None:
    _seed_db(tmp_path)
    client = _client(tmp_path, monkeypatch)

    resp = client.post(f"/api/mod/{MOD_ID}/employees/sync-remote-yuangon", json={})

    assert resp.status_code == 200
    assert resp.json()["data"] == {
        "employees": 2,
        "departments": 2,
        "source": "taiyangniao-pro",
        "synced": False,
    }
