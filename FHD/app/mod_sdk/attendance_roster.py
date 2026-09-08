"""Read the shared attendance roster inside the authenticated owner workspace."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.mod_sdk.owner_workspace import attendance_database_path


def ensure_roster_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS attendance_employees ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, source_file TEXT NOT NULL DEFAULT 'manual', "
        "employee_name TEXT NOT NULL, department TEXT NOT NULL DEFAULT '', "
        "main_department TEXT NOT NULL DEFAULT '', attendance_group TEXT NOT NULL DEFAULT '', "
        "employee_no TEXT NOT NULL DEFAULT '', position TEXT NOT NULL DEFAULT '', "
        "user_id TEXT NOT NULL DEFAULT '', UNIQUE(source_file, employee_name, department))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS attendance_departments ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, source_file TEXT NOT NULL DEFAULT 'manual', "
        "department TEXT NOT NULL, main_department TEXT NOT NULL DEFAULT '', "
        "attendance_group TEXT NOT NULL DEFAULT '', UNIQUE(source_file, department, attendance_group))"
    )


def initialize_roster_once(employees: list[dict]) -> bool:
    """Create a fresh owner database; an existing database is never changed."""
    target = attendance_database_path()
    if target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=target.parent, suffix=".db", delete=False) as temporary:
        staging = Path(temporary.name)
    try:
        with closing(sqlite3.connect(staging)) as connection:
            ensure_roster_schema(connection)
            for row in employees:
                name = str(row.get("name") or "").strip()
                department = str(row.get("dept") or "").strip()
                group = str(row.get("group") or "").strip()
                if not name:
                    continue
                connection.execute(
                    "INSERT OR IGNORE INTO attendance_employees "
                    "(source_file,employee_name,department,attendance_group,position) VALUES (?,?,?,?,?)",
                    ("delivery-seed", name, department, group, group),
                )
                if department:
                    connection.execute(
                        "INSERT OR IGNORE INTO attendance_departments "
                        "(source_file,department,attendance_group) VALUES (?,?,?)",
                        ("delivery-seed", department, group),
                    )
            connection.commit()
        try:
            os.link(staging, target)
        except FileExistsError:
            return False
        return True
    finally:
        staging.unlink(missing_ok=True)


def attendance_roster_state(request=None) -> tuple[bool, list[tuple[str, str, str]]]:
    """Use the current main roster with explicit ownership, then an isolated private seed."""
    if request is not None:
        from app.infrastructure.auth.dependencies import get_logged_in_user
        from app.mod_sdk.private_sqlite import resolve_mod_private_sqlite_path

        username = str(get_logged_in_user(request).username or "").strip()
        shared = resolve_mod_private_sqlite_path("taiyangniao_pro.db")
        if username and shared.is_file():
            with closing(sqlite3.connect(f"{shared.as_uri()}?mode=ro", uri=True)) as conn:
                columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(attendance_employees)")
                }
                if {"id", "employee_name", "department", "position", "owner_user_id"} <= columns:
                    rows = conn.execute(
                        "SELECT department, position, employee_name FROM attendance_employees "
                        "WHERE owner_user_id = ? AND TRIM(employee_name) <> '' ORDER BY id",
                        (username,),
                    ).fetchall()
                    return True, _unique_roster(rows)
    path = attendance_database_path()
    if not path.is_file():
        return False, []
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(attendance_employees)")}
        if not {"id", "employee_name", "department", "position"} <= columns:
            return False, []
        rows = conn.execute(
            "SELECT department, position, employee_name FROM attendance_employees "
            "WHERE TRIM(employee_name) <> '' ORDER BY id"
        ).fetchall()
    return True, _unique_roster(rows)


def read_attendance_roster(request=None) -> list[tuple[str, str, str]]:
    return attendance_roster_state(request)[1]


def _unique_roster(rows) -> list[tuple[str, str, str]]:
    seen: set[str] = set()
    result: list[tuple[str, str, str]] = []
    for department, position, name in rows:
        name = str(name or "").strip()
        if name and name not in seen:
            seen.add(name)
            result.append((str(department or ""), str(position or ""), name))
    return result
