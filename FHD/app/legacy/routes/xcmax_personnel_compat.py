"""Compatibility API exposing ERP personnel under historical route names.

The admin console still addresses ``/api/mod/xcmax-personnel``. Canonical
records now live in the host ERP database; the old Mod-private SQLite is a
read-only fallback until an administrator confirms its one-time migration.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Query
from sqlalchemy import or_

from app.utils.operational_errors import RECOVERABLE_ERRORS

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


def _erp_employees_page(page: int, page_size: int, search: str) -> dict[str, Any] | None:
    from app.db import HostSessionLocal
    from app.db.models.hr_attendance import ErpEmployee

    db = HostSessionLocal()
    try:
        query = db.query(ErpEmployee).filter(ErpEmployee.is_active.is_(True))
        value = str(search or "").strip()
        if value:
            like = f"%{value}%"
            query = query.filter(
                or_(
                    ErpEmployee.employee_name.ilike(like),
                    ErpEmployee.department.ilike(like),
                    ErpEmployee.employee_no.ilike(like),
                    ErpEmployee.position.ilike(like),
                    ErpEmployee.external_user_id.ilike(like),
                )
            )
        total = query.count()
        if total == 0:
            return None
        rows = query.order_by(ErpEmployee.id).offset((page - 1) * page_size).limit(page_size).all()
        return {
            "success": True,
            "data": {
                "items": [
                    {
                        "id": row.id,
                        "employee_name": row.employee_name,
                        "department": row.department,
                        "main_department": row.main_department,
                        "attendance_group": row.attendance_group,
                        "employee_no": row.employee_no,
                        "position": row.position,
                        "user_id": row.external_user_id,
                    }
                    for row in rows
                ],
                "total": total,
                "page": page,
                "page_size": page_size,
                "source": "erp:erp_employees",
            },
        }
    except RECOVERABLE_ERRORS:
        return None
    finally:
        db.close()


def _erp_departments_page(page: int, page_size: int, search: str) -> dict[str, Any] | None:
    from app.db import HostSessionLocal
    from app.db.models.hr_attendance import ErpDepartment

    db = HostSessionLocal()
    try:
        query = db.query(ErpDepartment).filter(ErpDepartment.is_active.is_(True))
        value = str(search or "").strip()
        if value:
            like = f"%{value}%"
            query = query.filter(
                or_(
                    ErpDepartment.name.ilike(like),
                    ErpDepartment.parent_name.ilike(like),
                    ErpDepartment.attendance_group.ilike(like),
                )
            )
        total = query.count()
        if total == 0:
            return None
        rows = (
            query.order_by(ErpDepartment.id).offset((page - 1) * page_size).limit(page_size).all()
        )
        return {
            "success": True,
            "data": {
                "items": [
                    {
                        "id": row.id,
                        "department": row.name,
                        "main_department": row.parent_name,
                        "attendance_group": row.attendance_group,
                    }
                    for row in rows
                ],
                "total": total,
                "page": page,
                "page_size": page_size,
                "source": "erp:erp_departments",
            },
        }
    except RECOVERABLE_ERRORS:
        return None
    finally:
        db.close()


def _erp_counts() -> tuple[int, int] | None:
    from app.db import HostSessionLocal
    from app.db.models.hr_attendance import ErpDepartment, ErpEmployee

    db = HostSessionLocal()
    try:
        employees = db.query(ErpEmployee).filter(ErpEmployee.is_active.is_(True)).count()
        departments = db.query(ErpDepartment).filter(ErpDepartment.is_active.is_(True)).count()
        return employees, departments
    except RECOVERABLE_ERRORS:
        return None
    finally:
        db.close()


def build_xcmax_personnel_router() -> APIRouter:
    router = APIRouter(prefix=f"/api/mod/{MOD_ID}", tags=[f"mod-{MOD_ID}"])

    @router.get("/employees", response_model=None)
    def list_employees(
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=500),
        search: str = Query(""),
    ):
        page, page_size = _safe_page(page, page_size)
        erp_page = _erp_employees_page(page, page_size, search)
        if erp_page is not None:
            return erp_page
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
        erp_page = _erp_departments_page(page, page_size, search)
        if erp_page is not None:
            return erp_page
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

        This action reports ERP master-data counts. If only a legacy side database
        exists, report it as pending migration instead of pretending it was synced.
        """
        erp_counts = _erp_counts()
        if erp_counts is not None and any(erp_counts):
            return {
                "success": True,
                "data": {
                    "employees": erp_counts[0],
                    "departments": erp_counts[1],
                    "source": "erp",
                    "synced": False,
                    "migration_required": False,
                },
            }
        conn = _connect_existing()
        if conn is None:
            return {
                "success": True,
                "data": {
                    "employees": 0,
                    "departments": 0,
                    "source": "erp",
                    "synced": False,
                    "migration_required": False,
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
                    "source": "legacy:taiyangniao-pro",
                    "synced": False,
                    "migration_required": bool(employees or departments),
                },
            }
        finally:
            conn.close()

    return router


def register_xcmax_personnel_routes(app) -> None:
    app.include_router(build_xcmax_personnel_router())
    logger.info("Registered xcmax_personnel_compat (/api/mod/%s/*)", MOD_ID)


__all__ = ["MOD_ID", "build_xcmax_personnel_router", "register_xcmax_personnel_routes"]
