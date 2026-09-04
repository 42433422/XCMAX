from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "XCAGI"
    / "mods"
    / "attendance-industry"
    / "backend"
    / "attendance_routes.py"
)
SPEC = importlib.util.spec_from_file_location("attendance_industry_dashboard_routes", MODULE_PATH)
assert SPEC and SPEC.loader
ROUTES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ROUTES)


def test_dashboard_snapshot_is_empty_when_database_is_missing(tmp_path: Path) -> None:
    db_path = tmp_path / "missing.db"

    result = ROUTES.build_attendance_dashboard_snapshot(db_path)

    assert result["readiness"] == "empty"
    assert result["employees_total"] == 0
    assert result["latest_import"] is None
    assert not db_path.exists()


def test_dashboard_snapshot_aggregates_roster_records_and_latest_import(tmp_path: Path) -> None:
    db_path = tmp_path / "attendance.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE attendance_employees (
            id INTEGER PRIMARY KEY,
            employee_name TEXT NOT NULL,
            department TEXT NOT NULL
        );
        CREATE TABLE attendance_departments (
            id INTEGER PRIMARY KEY,
            department TEXT NOT NULL
        );
        CREATE TABLE attendance_daily_records (
            id INTEGER PRIMARY KEY,
            month_label TEXT NOT NULL,
            work_date TEXT NOT NULL,
            leave_hours REAL NOT NULL,
            absent_days REAL NOT NULL,
            late_count_hint REAL NOT NULL,
            early_count_hint REAL NOT NULL,
            missing_card_count REAL NOT NULL
        );
        CREATE TABLE attendance_import_batches (
            id INTEGER PRIMARY KEY,
            source_file TEXT NOT NULL,
            month_label TEXT NOT NULL,
            rows_in INTEGER NOT NULL,
            rows_written INTEGER NOT NULL,
            imported_at TEXT NOT NULL
        );

        INSERT INTO attendance_employees VALUES
            (1, '张三', '生产部'),
            (2, '李四', '生产部'),
            (3, '王五', '行政部');
        INSERT INTO attendance_departments VALUES
            (1, '生产部'),
            (2, '行政部');
        INSERT INTO attendance_daily_records VALUES
            (1, '2026-08', '2026-08-01', 0, 0, 0, 0, 0),
            (2, '2026-08', '2026-08-02', 1, 0, 0, 0, 0),
            (3, '2026-09', '2026-09-01', 0, 0, 1, 0, 1);
        INSERT INTO attendance_import_batches VALUES
            (1, '/tmp/august.xlsx', '2026-08', 100, 98, '2026-08-31 10:00:00'),
            (2, '/tmp/september.xlsx', '2026-09', 20, 20, '2026-09-02 12:00:00');
        """
    )
    conn.commit()
    conn.close()

    result = ROUTES.build_attendance_dashboard_snapshot(db_path)

    assert result["readiness"] == "ready"
    assert result["employees_total"] == 3
    assert result["departments_total"] == 2
    assert result["daily_records_total"] == 3
    assert result["anomaly_records_total"] == 2
    assert result["months_total"] == 2
    assert result["latest_month"] == "2026-09"
    assert result["date_from"] == "2026-08-01"
    assert result["date_to"] == "2026-09-01"
    assert result["latest_import"]["source_file"] == "/tmp/september.xlsx"
    assert result["department_breakdown"] == [
        {"department": "生产部", "employees": 2},
        {"department": "行政部", "employees": 1},
    ]


def test_dashboard_snapshot_reports_roster_ready_without_daily_records(tmp_path: Path) -> None:
    db_path = tmp_path / "roster-only.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE attendance_employees (id INTEGER PRIMARY KEY, employee_name TEXT, department TEXT)"
    )
    conn.execute("INSERT INTO attendance_employees VALUES (1, '张三', '')")
    conn.commit()
    conn.close()

    result = ROUTES.build_attendance_dashboard_snapshot(db_path)

    assert result["readiness"] == "needs_records"
    assert result["department_breakdown"] == [{"department": "未分配部门", "employees": 1}]
    assert result["daily_records_total"] == 0
