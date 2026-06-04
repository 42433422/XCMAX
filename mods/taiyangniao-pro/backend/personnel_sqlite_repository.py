"""太阳鸟 mod 本地 sqlite 人员表访问（从 blueprints 迁出）。"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Iterator


def connect_products_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def load_attendance_employees_roster(db_path: Path) -> list[tuple[str, str, str]]:
    """侧栏「人员管理」主数据：attendance_employees（部门, 职位/性质, 姓名）。"""
    if not db_path.exists():
        return []
    with closing(connect_products_db(db_path)) as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT department, main_department, position, employee_name "
                "FROM attendance_employees "
                "WHERE employee_name IS NOT NULL AND TRIM(employee_name) != '' "
                "ORDER BY id"
            )
        except sqlite3.Error:
            return []
        seen: set[str] = set()
        out: list[tuple[str, str, str]] = []
        for row in cur.fetchall():
            name = str(row["employee_name"]).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            dept = str(row["department"] or row["main_department"] or "").strip()
            nature = str(row["position"] or "").strip()
            out.append((dept, nature, name))
        return out


def load_products_personnel_roster(db_path: Path) -> list[tuple[str, str, str]]:
    if not db_path.exists():
        return []
    with closing(connect_products_db(db_path)) as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT unit, specification, name FROM products "
                "WHERE name IS NOT NULL AND TRIM(name) != '' ORDER BY id"
            )
        except sqlite3.Error:
            return []
        seen: set[str] = set()
        out: list[tuple[str, str, str]] = []
        for row in cur.fetchall():
            name = str(row["name"]).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            dept = str(row["unit"] or "").strip()
            nature = str(row["specification"] or "").strip()
            out.append((dept, nature, name))
        return out
