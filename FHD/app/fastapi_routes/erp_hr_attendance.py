"""ERP personnel and attendance read APIs.

These routes are host-owned core ERP capability.  They remain available
without an attendance Mod; Mods only add parsers, templates, and terminology.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.application.erp_attendance_app_service import attendance_record_page
from app.db import HostSessionLocal
from app.db.models.hr_attendance import (
    AttendanceImportBatch,
    ErpDepartment,
    ErpEmployee,
)
from app.infrastructure.auth.dependencies import get_logged_in_user

router = APIRouter(prefix="/api/erp/hr", tags=["erp-hr-attendance"])


def _host_db():
    db = HostSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _page(page: int, page_size: int) -> tuple[int, int, int]:
    current = max(1, int(page or 1))
    size = min(500, max(1, int(page_size or 50)))
    return current, size, (current - 1) * size


@router.get("/employees", response_model=None)
def list_employees(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: str = Query(""),
    db: Session = Depends(_host_db),
) -> dict[str, Any]:
    page, page_size, offset = _page(page, page_size)
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
    rows = query.order_by(ErpEmployee.id).offset(offset).limit(page_size).all()
    return {
        "success": True,
        "data": {
            "items": [
                {
                    "id": row.id,
                    "employee_name": row.employee_name,
                    "department_id": row.department_id,
                    "department": row.department,
                    "main_department": row.main_department,
                    "attendance_group": row.attendance_group,
                    "employee_no": row.employee_no,
                    "position": row.position,
                    "user_id": row.external_user_id,
                    "account_user_id": row.account_user_id,
                    "source_system": row.source_system,
                    "is_active": row.is_active,
                }
                for row in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
            "source": "erp:erp_employees",
        },
    }


@router.get("/departments", response_model=None)
def list_departments(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: str = Query(""),
    db: Session = Depends(_host_db),
) -> dict[str, Any]:
    page, page_size, offset = _page(page, page_size)
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
    rows = query.order_by(ErpDepartment.id).offset(offset).limit(page_size).all()
    return {
        "success": True,
        "data": {
            "items": [
                {
                    "id": row.id,
                    "department": row.name,
                    "main_department": row.parent_name,
                    "attendance_group": row.attendance_group,
                    "source_system": row.source_system,
                    "is_active": row.is_active,
                }
                for row in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
            "source": "erp:erp_departments",
        },
    }


@router.get("/attendance-records", response_model=None)
def list_attendance_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    date_start: str = Query(""),
    date_end: str = Query(""),
    employee_name: str = Query(""),
    employee_no: str = Query(""),
    department: str = Query(""),
    db: Session = Depends(_host_db),
) -> dict[str, Any]:
    for raw in (date_start, date_end):
        if raw:
            date.fromisoformat(raw)
    page, page_size, offset = _page(page, page_size)
    total, rows = attendance_record_page(
        db,
        date_start=date_start,
        date_end=date_end,
        employee_name=employee_name,
        employee_no=employee_no,
        department=department,
        offset=offset,
        limit=page_size,
    )
    return {
        "success": True,
        "data": {
            "items": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "source": "erp:erp_attendance_daily_records",
        },
    }


@router.get("/attendance-imports", response_model=None)
def list_attendance_imports(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(_host_db),
) -> dict[str, Any]:
    page, page_size, offset = _page(page, page_size)
    query = db.query(AttendanceImportBatch)
    total = query.count()
    rows = (
        query.order_by(AttendanceImportBatch.imported_at.desc(), AttendanceImportBatch.id.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )
    return {
        "success": True,
        "data": {
            "items": [
                {
                    "id": row.id,
                    "source_name": row.source_name,
                    "month_label": row.month_label,
                    "workbook_kind": row.workbook_kind,
                    "rows_in": row.rows_in,
                    "rows_written": row.rows_written,
                    "department_rows": row.department_rows,
                    "employee_rows": row.employee_rows,
                    "imported_at": row.imported_at.isoformat(),
                }
                for row in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
            "source": "erp:erp_attendance_import_batches",
        },
    }


@router.get("/legacy-migration-preview", response_model=None)
def legacy_migration_preview(db: Session = Depends(_host_db)) -> dict[str, Any]:
    from app.application.erp_attendance_app_service import legacy_attendance_preview
    from app.mod_sdk.private_sqlite import resolve_mod_private_sqlite_path

    data = legacy_attendance_preview(resolve_mod_private_sqlite_path("taiyangniao_pro.db"))
    data["already_migrated"] = (
        db.query(AttendanceImportBatch.id)
        .filter(AttendanceImportBatch.source_file == "legacy-migration:taiyangniao-pro")
        .first()
        is not None
    )
    return {
        "success": True,
        "data": data,
    }


@router.post("/legacy-migrate", response_model=None)
def migrate_legacy_attendance(
    user: Any = Depends(get_logged_in_user),
    db: Session = Depends(_host_db),
) -> dict[str, Any]:
    from app.application.erp_attendance_app_service import migrate_legacy_attendance_to_erp
    from app.mod_sdk.private_sqlite import resolve_mod_private_sqlite_path

    result = migrate_legacy_attendance_to_erp(
        db,
        legacy_db_path=resolve_mod_private_sqlite_path("taiyangniao_pro.db"),
        owner_user_id=int(getattr(user, "id", 0) or 0) or None,
    )
    db.commit()
    return {"success": True, "data": result}


__all__ = ["router"]
