"""Host compat API for the admin console personnel bridge.

The admin console historically addresses personnel data through
``/api/mod/xcmax-personnel``.  Desktop builds may not install that Mod, while
the same personnel mirror already lives in the bundled ``taiyangniao-pro``
SQLite side database.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Query

logger = logging.getLogger(__name__)

MOD_ID = "xcmax-personnel"
TAIYANGNIAO_DB = "taiyangniao_pro.db"

_ALLOWED_COUNT_TABLES = frozenset({"attendance_employees", "attendance_departments"})


def _db_path() -> Path:
    from app.mod_sdk.private_sqlite import resolve_mod_private_sqlite_path

    return resolve_mod_private_sqlite_path(TAIYANGNIAO_DB)


def _connect_existing() -> sqlite3.Connection | None:
    path = _db_path()
    if not path.is_file():
        return None
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _safe_page(page: int, page_size: int) -> tuple[int, int]:
    p = max(1, int(page or 1))
    size = min(500, max(1, int(page_size or 50)))
    return p, size


def _empty_page(page: int, page_size: int) -> dict[str, Any]:
    return {
        "success": True,
        "data": {"items": [], "total": 0, "page": page, "page_size": page_size},
    }


def _table_count(conn: sqlite3.Connection, table: str) -> int:
    if table not in _ALLOWED_COUNT_TABLES:
        return 0
    try:
        cur = conn.execute("SELECT COUNT(*) FROM " + table)
        return int(cur.fetchone()[0] or 0)
    except sqlite3.Error:
        return 0


def build_xcmax_personnel_router() -> APIRouter:
    router = APIRouter(prefix=f"/api/mod/{MOD_ID}", tags=[f"mod-{MOD_ID}"])

    @router.get("/employees", response_model=None)
    def list_employees(
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=500),
        search: str = Query(""),
    ):
        page, page_size = _safe_page(page, page_size)
        conn = _connect_existing()
        if conn is None:
            return _empty_page(page, page_size)
        like = f"%{(search or '').strip()}%"
        try:
            cur = conn.execute(
                """
                SELECT COUNT(*)
                FROM attendance_employees
                WHERE employee_name LIKE ?
                   OR department LIKE ?
                   OR employee_no LIKE ?
                   OR position LIKE ?
                   OR user_id LIKE ?
                """,
                (like, like, like, like, like),
            )
            total = int(cur.fetchone()[0] or 0)
            offset = (page - 1) * page_size
            cur = conn.execute(
                """
                SELECT id, employee_name, department, main_department, attendance_group,
                       employee_no, position, user_id
                FROM attendance_employees
                WHERE employee_name LIKE ?
                   OR department LIKE ?
                   OR employee_no LIKE ?
                   OR position LIKE ?
                   OR user_id LIKE ?
                ORDER BY id
                LIMIT ? OFFSET ?
                """,
                (like, like, like, like, like, page_size, offset),
            )
            items = [dict(row) for row in cur.fetchall()]
            return {
                "success": True,
                "data": {"items": items, "total": total, "page": page, "page_size": page_size},
            }
        except sqlite3.Error as exc:
            logger.warning("xcmax-personnel employees fallback failed: %s", exc)
            return _empty_page(page, page_size)
        finally:
            conn.close()

    @router.get("/departments", response_model=None)
    def list_departments(
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=500),
        search: str = Query(""),
    ):
        page, page_size = _safe_page(page, page_size)
        conn = _connect_existing()
        if conn is None:
            return _empty_page(page, page_size)
        like = f"%{(search or '').strip()}%"
        try:
            cur = conn.execute(
                """
                SELECT COUNT(*)
                FROM attendance_departments
                WHERE department LIKE ?
                   OR main_department LIKE ?
                   OR attendance_group LIKE ?
                """,
                (like, like, like),
            )
            total = int(cur.fetchone()[0] or 0)
            offset = (page - 1) * page_size
            cur = conn.execute(
                """
                SELECT id, department, main_department, attendance_group
                FROM attendance_departments
                WHERE department LIKE ?
                   OR main_department LIKE ?
                   OR attendance_group LIKE ?
                ORDER BY id
                LIMIT ? OFFSET ?
                """,
                (like, like, like, page_size, offset),
            )
            items = [dict(row) for row in cur.fetchall()]
            return {
                "success": True,
                "data": {"items": items, "total": total, "page": page, "page_size": page_size},
            }
        except sqlite3.Error as exc:
            logger.warning("xcmax-personnel departments fallback failed: %s", exc)
            return _empty_page(page, page_size)
        finally:
            conn.close()

    @router.post("/employees/sync-remote-yuangon", response_model=None)
    def sync_remote_yuangon(_body: dict = Body(default_factory=dict)):
        """Desktop fallback for the admin console sync button.

        In local desktop mode the bundled personnel mirror is already materialized
        in ``taiyangniao_pro.db``.  Return the current mirror counts so the
        operator action completes instead of falling through to a 404.
        """
        conn = _connect_existing()
        if conn is None:
            return {
                "success": True,
                "data": {
                    "employees": 0,
                    "departments": 0,
                    "source": "taiyangniao-pro",
                    "synced": False,
                },
            }
        try:
            employees = _table_count(conn, "attendance_employees")
            departments = _table_count(conn, "attendance_departments")
            return {
                "success": True,
                "data": {
                    "employees": employees,
                    "departments": departments,
                    "source": "taiyangniao-pro",
                    "synced": False,
                },
            }
        finally:
            conn.close()

    return router


def register_xcmax_personnel_routes(app) -> None:
    app.include_router(build_xcmax_personnel_router())
    logger.info("Registered xcmax_personnel_compat (/api/mod/%s/*)", MOD_ID)


__all__ = ["MOD_ID", "build_xcmax_personnel_router", "register_xcmax_personnel_routes"]
