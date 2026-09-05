from __future__ import annotations

import importlib.util
import logging
import sqlite3
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "XCAGI"
    / "mods"
    / "attendance-industry"
    / "backend"
    / "management_routes.py"
)
SPEC = importlib.util.spec_from_file_location("attendance_industry_management_routes", MODULE_PATH)
assert SPEC and SPEC.loader
ROUTES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ROUTES)


def _seed_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE attendance_employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file TEXT NOT NULL,
            employee_name TEXT NOT NULL,
            department TEXT NOT NULL,
            main_department TEXT NOT NULL,
            attendance_group TEXT NOT NULL,
            employee_no TEXT NOT NULL,
            position TEXT NOT NULL,
            user_id TEXT NOT NULL,
            UNIQUE(source_file, employee_name, department)
        );
        CREATE TABLE attendance_departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file TEXT NOT NULL,
            department TEXT NOT NULL,
            main_department TEXT NOT NULL,
            attendance_group TEXT NOT NULL,
            UNIQUE(source_file, department, attendance_group)
        );
        CREATE TABLE attendance_daily_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file TEXT NOT NULL,
            month_label TEXT NOT NULL,
            source_row INTEGER NOT NULL,
            employee_name TEXT NOT NULL,
            attendance_group TEXT NOT NULL,
            department TEXT NOT NULL,
            employee_no TEXT NOT NULL,
            position TEXT NOT NULL,
            user_id TEXT NOT NULL,
            work_date TEXT NOT NULL,
            shift_name TEXT NOT NULL,
            daily_times_json TEXT NOT NULL,
            raw_times_json TEXT NOT NULL,
            all_times_json TEXT NOT NULL,
            leave_hours REAL NOT NULL,
            absent_days REAL NOT NULL,
            late_count_hint REAL NOT NULL,
            early_count_hint REAL NOT NULL,
            missing_card_count REAL NOT NULL,
            notes_json TEXT NOT NULL,
            imported_at TEXT NOT NULL
        );
        INSERT INTO attendance_departments
            (source_file, department, main_department, attendance_group)
        VALUES ('seed.xlsx', '生产部', '制造中心', '计时');
        INSERT INTO attendance_employees
            (source_file, employee_name, department, main_department, attendance_group, employee_no, position, user_id)
        VALUES ('seed.xlsx', '张三', '生产部', '制造中心', '计时', 'E001', '木工', 'u1');
        INSERT INTO attendance_daily_records
            (source_file, month_label, source_row, employee_name, attendance_group, department,
             employee_no, position, user_id, work_date, shift_name, daily_times_json,
             raw_times_json, all_times_json, leave_hours, absent_days, late_count_hint,
             early_count_hint, missing_card_count, notes_json, imported_at)
        VALUES ('seed.xlsx', '2026-08', 1, '张三', '计时', '生产部', 'E001', '木工', 'u1',
                '2026-08-01', '正班', '[]', '[]', '[]', 0, 0, 1, 0, 0, '[]', '2026-08-02 10:00:00');
        """
    )
    conn.commit()
    conn.close()


def test_shared_schedule_resources_do_not_expose_customer_template(tmp_path):
    path = tmp_path / "attendance.db"
    _seed_db(path)
    with _client(path) as client:
        response = client.get("/api/mod/attendance-industry/schedules")
        assert response.status_code == 200
        data = response.json()
        assert data["schedule_groups"] == [
            {"name": "计时", "headcount": "1 人", "shift_type": "人员考勤组", "lines": []}
        ]
        assert data["lines"] == []
        assert "424/" not in response.text


def _client(db_path: Path) -> TestClient:
    router = APIRouter(prefix="/api/mod/attendance-industry")
    ROUTES.register(
        router,
        logger=logging.getLogger(__name__),
        get_database_path=lambda: db_path,
    )
    app = FastAPI()
    app.include_router(router)
    # These CRUD tests inject an isolated database. Real session/owner rejection
    # and cross-account storage are exercised in test_deep_mods/test_owner_workspace.
    from app.mod_sdk.owner_workspace import owner_context, require_owner_workspace

    async def authenticated_test_owner():
        with owner_context("tenant:fixture"):
            yield "tenant:fixture"

    app.dependency_overrides[require_owner_workspace] = authenticated_test_owner
    return TestClient(app)


def test_personnel_and_department_management_crud(tmp_path: Path) -> None:
    db_path = tmp_path / "attendance.db"
    _seed_db(db_path)
    client = _client(db_path)

    employees = client.get("/api/mod/attendance-industry/employees")
    assert employees.status_code == 200
    assert employees.json()["data"]["items"][0]["employee_name"] == "张三"

    departments = client.get("/api/mod/attendance-industry/departments")
    assert departments.status_code == 200
    assert departments.json()["data"]["items"][0]["employee_count"] == 1

    created_department = client.post(
        "/api/mod/attendance-industry/departments",
        json={"department": "质检部", "main_department": "制造中心", "attendance_group": "计时"},
    )
    assert created_department.status_code == 200
    department_id = created_department.json()["data"]["id"]

    created_employee = client.post(
        "/api/mod/attendance-industry/employees",
        json={"employee_name": "李四", "employee_no": "E002", "department": "质检部"},
    )
    assert created_employee.status_code == 200
    employee_id = created_employee.json()["data"]["id"]

    updated_employee = client.put(
        f"/api/mod/attendance-industry/employees/{employee_id}",
        json={
            "employee_name": "李四",
            "employee_no": "E002",
            "department": "质检部",
            "position": "质检",
        },
    )
    assert updated_employee.status_code == 200
    assert updated_employee.json()["data"]["position"] == "质检"

    blocked_department_delete = client.delete(
        f"/api/mod/attendance-industry/departments/{department_id}"
    )
    assert blocked_department_delete.status_code == 409

    assert client.delete(f"/api/mod/attendance-industry/employees/{employee_id}").status_code == 200
    assert (
        client.delete(f"/api/mod/attendance-industry/departments/{department_id}").status_code
        == 200
    )


def test_attendance_records_support_search_and_month_filter(tmp_path: Path) -> None:
    db_path = tmp_path / "attendance.db"
    _seed_db(db_path)
    client = _client(db_path)

    response = client.get(
        "/api/mod/attendance-industry/records",
        params={"search": "张三", "month": "2026-08"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["shift_name"] == "正班"
    assert data["months"] == ["2026-08"]


def test_management_and_conversion_share_roster_even_after_last_person_deleted(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "attendance.db"
    _seed_db(db_path)
    from app.mod_sdk import attendance_roster

    monkeypatch.setattr(attendance_roster, "attendance_database_path", lambda: db_path)
    client = _client(db_path)
    assert attendance_roster.read_attendance_roster() == [("生产部", "木工", "张三")]

    assert (
        client.put(
            "/api/mod/attendance-industry/departments/1", json={"department": "新生产部"}
        ).status_code
        == 200
    )
    assert attendance_roster.read_attendance_roster() == [("新生产部", "木工", "张三")]
    assert (
        client.put(
            "/api/mod/attendance-industry/employees/1",
            json={"employee_name": "张三改名", "department": "新生产部", "position": "计时"},
        ).status_code
        == 200
    )
    assert attendance_roster.read_attendance_roster() == [("新生产部", "计时", "张三改名")]
    assert client.delete("/api/mod/attendance-industry/employees/1").status_code == 200
    assert attendance_roster.read_attendance_roster() == []


def test_new_install_can_create_first_department_and_person(tmp_path):
    db_path = tmp_path / "new" / "attendance.db"
    client = _client(db_path)
    assert client.get("/api/mod/attendance-industry/employees").json()["data"]["total"] == 0
    assert not db_path.exists()
    assert (
        client.post(
            "/api/mod/attendance-industry/departments", json={"department": "研发部"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/mod/attendance-industry/employees",
            json={"employee_name": "新员工", "department": "研发部"},
        ).status_code
        == 200
    )
    assert (
        client.get("/api/mod/attendance-industry/departments").json()["data"]["items"][0][
            "employee_count"
        ]
        == 1
    )


def test_manual_entry_cannot_duplicate_imported_person_or_department(tmp_path):
    db_path = tmp_path / "attendance.db"
    _seed_db(db_path)
    client = _client(db_path)
    assert (
        client.post(
            "/api/mod/attendance-industry/employees",
            json={"employee_name": "张三", "department": "生产部"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/mod/attendance-industry/departments", json={"department": "生产部"}
        ).status_code
        == 409
    )
    assert client.get("/api/mod/attendance-industry/employees").json()["data"]["total"] == 1
