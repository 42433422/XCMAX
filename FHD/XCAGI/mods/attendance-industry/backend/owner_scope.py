"""考勤数据账号级归属隔离。

同一台桌面机器可能先后登录多个客户账号（开发/演示机、多租户试点），考勤人员、
部门与逐日记录必须按登录账号隔离，避免「A 公司看到 B 公司名单」。

归属键 = 当前登录用户名（users.username）。未登录/无法解析时返回空串，
调用方按「空结果 + 拒绝写入」处理（fail-closed），绝不回退到全量。

存量兼容：首次访问执行幂等迁移，为三张表补 ``owner_user_id`` 列，并把历史行
归属到太阳鸟账号（考勤侧库数据全部来自太阳鸟交付 seed）。
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from app.mod_sdk.errors import RECOVERABLE_ERRORS

try:
    from .owner_schema import upgrade_unique_constraints
except ImportError:  # The Mod loader also supports top-level backend imports.
    from owner_schema import upgrade_unique_constraints

# 历史存量数据的归属账号：考勤侧库的数据全部来自太阳鸟交付 seed。
LEGACY_OWNER_USERNAME = "SUNBIRD"

_TABLES = (
    "attendance_employees",
    "attendance_departments",
    "attendance_daily_records",
)

_MIGRATE_LOCK = threading.Lock()


def owner_from_request(request) -> str:
    """当前登录账号用户名；未登录或解析失败返回空串（调用方 fail-closed）。"""
    try:
        from app.mod_sdk.host_services import resolve_session_user
    except RECOVERABLE_ERRORS:
        return ""
    try:
        user = resolve_session_user(request)
    except RECOVERABLE_ERRORS:
        return ""
    if user is None:
        return ""
    return str(getattr(user, "username", "") or "").strip()


def migrate_owner_column(db_path: Path) -> None:
    """原子升级归属列和唯一约束；每次重查，支持同路径恢复旧数据库。"""
    with _MIGRATE_LOCK:
        if not db_path.is_file():
            return
        conn = sqlite3.connect(str(db_path), timeout=30)
        try:
            # SQLite's documented table-rebuild sequence: disable FK actions before
            # BEGIN, then verify references before committing the complete upgrade.
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("PRAGMA legacy_alter_table=ON")
            conn.execute("BEGIN IMMEDIATE")
            for table in _TABLES:
                has_table = (
                    conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                    ).fetchone()
                    is not None
                )
                if not has_table:
                    continue
                cols = {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                if "owner_user_id" not in cols:
                    conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN owner_user_id TEXT NOT NULL DEFAULT ''"
                    )
                    # 列刚建时表内全是历史行：归属太阳鸟交付账号。
                    conn.execute(
                        f"UPDATE {table} SET owner_user_id = ? WHERE owner_user_id = ''",
                        (LEGACY_OWNER_USERNAME,),
                    )
                upgrade_unique_constraints(conn, table)
            if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise sqlite3.IntegrityError("attendance owner upgrade: invalid foreign key")
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            raise
        finally:
            conn.close()
