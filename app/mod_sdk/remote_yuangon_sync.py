"""从远端 yuangon 目录拉取 employee.yaml 并写入本地人员 SQLite（products / attendance_* / customers）。"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

_DEFAULT_SSH_HOST = os.environ.get("XCMAX_REMOTE_HOST", "")
DEFAULT_SSH_TARGET = os.environ.get(
    "XCMAX_SSH_TARGET", f"root@{_DEFAULT_SSH_HOST}" if _DEFAULT_SSH_HOST else ""
)
DEFAULT_REMOTE_ROOT = "/root/modstore-git/yuangon"
DEFAULT_SOURCE_FILE = f"ssh://{DEFAULT_SSH_TARGET}{DEFAULT_REMOTE_ROOT}"


@dataclass(frozen=True)
class RemoteYuangonEmployee:
    employee_id: str
    name: str
    version: str
    domain: str
    area: str
    owner: str
    path: str


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance_departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file TEXT NOT NULL,
            department TEXT NOT NULL,
            main_department TEXT NOT NULL,
            attendance_group TEXT NOT NULL,
            UNIQUE(source_file, department, attendance_group)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance_employees (
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
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file TEXT NOT NULL DEFAULT '',
            model_number TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL DEFAULT '',
            specification TEXT NOT NULL DEFAULT '',
            price REAL NOT NULL DEFAULT 0,
            unit TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file TEXT NOT NULL DEFAULT '',
            customer_name TEXT NOT NULL DEFAULT '',
            contact_person TEXT NOT NULL DEFAULT '',
            contact_phone TEXT NOT NULL DEFAULT '',
            address TEXT NOT NULL DEFAULT '',
            purchase_unit TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_employees_name ON attendance_employees (employee_name)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_departments_dept ON attendance_departments (department)"
    )


def _remote_probe_script(remote_root: str) -> str:
    root_json = json.dumps(remote_root)
    return f"""
import json
from pathlib import Path

root = Path({root_json})
rows = []
if not root.exists():
    raise SystemExit(f"remote yuangon root not found: {{root}}")

def clean_value(raw):
    value = str(raw or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1]
    return value.strip()

for p in sorted(root.rglob("employee.yaml")):
    if any(part.startswith(".") for part in p.parts):
        continue
    data = {{}}
    for line in p.read_text("utf-8", errors="ignore").splitlines():
        if not line.strip() or line.startswith(" ") or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key in {{"id", "name", "version", "domain", "area", "owner"}}:
            data[key] = clean_value(value)
    employee_id = data.get("id", "").strip()
    if not employee_id:
        continue
    rows.append({{
        "employee_id": employee_id,
        "name": data.get("name") or employee_id,
        "version": data.get("version") or "",
        "domain": data.get("domain") or "",
        "area": data.get("area") or "yuangon",
        "owner": data.get("owner") or "",
        "path": str(p.relative_to(root)),
    }})

print(json.dumps(rows, ensure_ascii=False))
""".strip()


def fetch_remote_yuangon_employees(
    *,
    ssh_target: str = DEFAULT_SSH_TARGET,
    remote_root: str = DEFAULT_REMOTE_ROOT,
    connect_timeout: int = 15,
) -> list[RemoteYuangonEmployee]:
    """Fetch top-level fields from remote ``yuangon/**/employee.yaml`` via SSH."""

    target = (ssh_target or DEFAULT_SSH_TARGET).strip()
    root = (remote_root or DEFAULT_REMOTE_ROOT).strip()
    if not target:
        raise ValueError("ssh_target is empty")
    if not root.startswith("/"):
        raise ValueError("remote_root must be an absolute path")

    cmd = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={int(connect_timeout)}",
        target,
        f"python3 - <<'PY'\n{_remote_probe_script(root)}\nPY",
    ]
    completed = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        text=True,
        timeout=max(20, int(connect_timeout) + 15),
    )
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"ssh fetch employees failed exit={completed.returncode}: {err}")

    payload = json.loads(completed.stdout or "[]")
    employees: list[RemoteYuangonEmployee] = []
    seen: set[str] = set()
    for item in payload if isinstance(payload, list) else []:
        employee_id = str(item.get("employee_id") or "").strip()
        if not employee_id or employee_id in seen:
            continue
        seen.add(employee_id)
        employees.append(
            RemoteYuangonEmployee(
                employee_id=employee_id,
                name=str(item.get("name") or employee_id).strip(),
                version=str(item.get("version") or "").strip(),
                domain=str(item.get("domain") or "").strip(),
                area=str(item.get("area") or "yuangon").strip(),
                owner=str(item.get("owner") or "").strip(),
                path=str(item.get("path") or "").strip(),
            )
        )
    return employees


def sync_remote_yuangon_employees(
    db_path: Path,
    *,
    ssh_target: str = DEFAULT_SSH_TARGET,
    remote_root: str = DEFAULT_REMOTE_ROOT,
    source_file: str | None = None,
    connect_timeout: int = 15,
) -> dict[str, Any]:
    """Fetch remote yuangon employees and replace this sync source in local tables."""

    employees = fetch_remote_yuangon_employees(
        ssh_target=ssh_target,
        remote_root=remote_root,
        connect_timeout=connect_timeout,
    )
    source = source_file or f"ssh://{ssh_target}{remote_root}"
    now = datetime.now().isoformat(timespec="seconds")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_schema(conn)
        conn.execute("BEGIN")
        for table in ("attendance_employees", "attendance_departments", "products", "customers"):
            conn.execute(f"DELETE FROM {table} WHERE source_file = ?", (source,))

        areas: dict[str, str] = {}
        for emp in employees:
            area = emp.area or "yuangon"
            areas.setdefault(area, area)
            conn.execute(
                """
                INSERT OR IGNORE INTO attendance_employees
                    (source_file, employee_name, department, main_department,
                     attendance_group, employee_no, position, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source,
                    emp.name,
                    area,
                    area,
                    "MODstore 在岗",
                    emp.employee_id,
                    emp.domain,
                    emp.employee_id,
                ),
            )
            specification = emp.domain or (f"version {emp.version}" if emp.version else "")
            conn.execute(
                """
                INSERT INTO products
                    (source_file, model_number, name, specification, price, unit, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (source, emp.employee_id, emp.name, specification, 0.0, area, now, now),
            )

        for area in sorted(areas):
            conn.execute(
                """
                INSERT OR IGNORE INTO attendance_departments
                    (source_file, department, main_department, attendance_group)
                VALUES (?, ?, ?, ?)
                """,
                (source, area, area, "MODstore 在岗"),
            )
            conn.execute(
                """
                INSERT INTO customers
                    (source_file, customer_name, contact_person, contact_phone, address, purchase_unit, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (source, area, "", "", "远端 yuangon 员工分组", "", now, now),
            )

        conn.commit()
        return {
            "employees": len(employees),
            "departments": len(areas),
            "source_file": source,
            "ssh_target": ssh_target,
            "remote_root": remote_root,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


__all__ = [
    "DEFAULT_REMOTE_ROOT",
    "DEFAULT_SSH_TARGET",
    "DEFAULT_SOURCE_FILE",
    "RemoteYuangonEmployee",
    "fetch_remote_yuangon_employees",
    "sync_remote_yuangon_employees",
]
