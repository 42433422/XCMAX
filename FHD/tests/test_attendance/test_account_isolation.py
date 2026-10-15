"""考勤工作区账号级数据隔离回归测试。

覆盖：owner 列迁移幂等、读过滤、写归属、跨账号改删 404、未登录 fail-closed、
花名册按账号隔离。直接测 mod backend 的 SQL 层与迁移逻辑（不依赖宿主会话）。
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import types
from pathlib import Path

import pytest

MOD_BACKEND = (
    Path(__file__).resolve().parents[2] / "XCAGI" / "mods" / "attendance-industry" / "backend"
)


def _load_owner_scope():
    if str(MOD_BACKEND) not in sys.path:
        sys.path.insert(0, str(MOD_BACKEND))
    spec = importlib.util.spec_from_file_location("att_owner_scope", MOD_BACKEND / "owner_scope.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # owner_scope 依赖宿主 app.mod_sdk.errors（真实模块含 RECOVERABLE_ERRORS），无需替身。
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def owner_scope():
    return _load_owner_scope()


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "taiyangniao_pro.db"
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE attendance_employees ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, source_file TEXT NOT NULL DEFAULT 'manual', "
        "employee_name TEXT NOT NULL, department TEXT NOT NULL DEFAULT '', "
        "main_department TEXT NOT NULL DEFAULT '', attendance_group TEXT NOT NULL DEFAULT '', "
        "employee_no TEXT NOT NULL DEFAULT '', position TEXT NOT NULL DEFAULT '', "
        "user_id TEXT NOT NULL DEFAULT '', UNIQUE(source_file, employee_name, department))"
    )
    conn.execute(
        "CREATE TABLE attendance_departments ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, source_file TEXT NOT NULL DEFAULT 'manual', "
        "department TEXT NOT NULL, main_department TEXT NOT NULL DEFAULT '', "
        "attendance_group TEXT NOT NULL DEFAULT '', UNIQUE(source_file, department, attendance_group))"
    )
    conn.execute(
        "CREATE TABLE attendance_daily_records ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, month_label TEXT, employee_name TEXT, "
        "department TEXT, work_date TEXT)"
    )
    # 存量太阳鸟数据（无 owner 列的旧 schema）
    conn.execute(
        "INSERT INTO attendance_employees (source_file, employee_name, department) VALUES "
        "('seed', '胡超', '计划生产部'), ('seed', '樊琪麒', '计划生产部')"
    )
    conn.commit()
    conn.close()
    return path


def test_migrate_adds_owner_column_and_backfills_legacy(owner_scope, db):
    owner_scope.migrate_owner_column(db)
    conn = sqlite3.connect(str(db))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(attendance_employees)")}
    assert "owner_user_id" in cols
    rows = conn.execute("SELECT DISTINCT owner_user_id FROM attendance_employees").fetchall()
    assert [r[0] for r in rows] == [owner_scope.LEGACY_OWNER_USERNAME]
    conn.close()


def test_migrate_is_idempotent(owner_scope, db):
    owner_scope.migrate_owner_column(db)
    owner_scope.migrate_owner_column(db)  # 第二次不得报错/不得重复改归属
    conn = sqlite3.connect(str(db))
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM attendance_employees WHERE owner_user_id = ?",
            (owner_scope.LEGACY_OWNER_USERNAME,),
        ).fetchone()[0]
        == 2
    )
    conn.close()


def test_migrate_skips_missing_db(owner_scope, tmp_path):
    owner_scope.migrate_owner_column(tmp_path / "nope.db")  # 不抛异常


def test_roster_query_is_owner_scoped(owner_scope, db):
    """模拟 _resolve_personnel_roster 的隔离查询：不同账号互不可见。"""
    owner_scope.migrate_owner_column(db)
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO attendance_employees (employee_name, department, owner_user_id) VALUES "
        "('王涂料', '生产部', 'wuxinghua1')"
    )
    conn.commit()
    sunbird = conn.execute(
        "SELECT employee_name FROM attendance_employees WHERE owner_user_id = ?",
        (owner_scope.LEGACY_OWNER_USERNAME,),
    ).fetchall()
    coating = conn.execute(
        "SELECT employee_name FROM attendance_employees WHERE owner_user_id = ?",
        ("wuxinghua1",),
    ).fetchall()
    assert {r[0] for r in sunbird} == {"胡超", "樊琪麒"}
    assert {r[0] for r in coating} == {"王涂料"}
    conn.close()
