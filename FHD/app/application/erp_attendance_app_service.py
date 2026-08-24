"""ERP-owned personnel and attendance application service.

Customer/industry Mods supply parsers and terminology.  This service owns the
canonical tenant-scoped records, deterministic import receipt, and rollback.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models.hr_attendance import (
    AttendanceDailyRecord,
    AttendanceImportBatch,
    AttendanceLeaveRecord,
    ErpDepartment,
    ErpEmployee,
)
from app.infrastructure.tenant_scope import tenant_id_for_write

ERP_ATTENDANCE_SOURCE = "erp:attendance"


def erp_attendance_schema_available(db: Session) -> bool:
    bind = db.get_bind()
    inspector = sa_inspect(bind)
    required = {
        "erp_departments",
        "erp_employees",
        "erp_attendance_import_batches",
        "erp_attendance_daily_records",
        "erp_attendance_leave_records",
    }
    return required.issubset(set(inspector.get_table_names()))


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def employee_identity_key(
    *, employee_name: str, department: str = "", employee_no: str = "", external_user_id: str = ""
) -> str:
    """Build a tenant-local stable employee identity without using source-file position."""

    user_id = _clean(external_user_id).casefold()
    if user_id:
        return f"user:{user_id}"
    number = _clean(employee_no).casefold()
    if number:
        return f"number:{number}"
    name = _clean(employee_name).casefold()
    dept = _clean(department).casefold()
    return f"name:{name}|department:{dept}"


def _department(
    db: Session,
    *,
    name: str,
    parent_name: str,
    attendance_group: str,
    source_key: str,
    receipt: dict[str, Any],
) -> ErpDepartment | None:
    name = _clean(name)
    if not name:
        return None
    parent_name = _clean(parent_name)
    obj = (
        db.query(ErpDepartment)
        .filter(ErpDepartment.name == name, ErpDepartment.parent_name == parent_name)
        .first()
    )
    if obj is None:
        obj = ErpDepartment(
            tenant_id=tenant_id_for_write(),
            name=name,
            parent_name=parent_name,
            attendance_group=_clean(attendance_group),
            source_system="attendance_import",
            source_key=source_key,
            is_active=True,
        )
        db.add(obj)
        db.flush()
        receipt["created_department_ids"].append(obj.id)
        return obj

    before: dict[str, Any] = {}
    group = _clean(attendance_group)
    if group and not obj.attendance_group:
        before["attendance_group"] = obj.attendance_group
        obj.attendance_group = group
    if before:
        receipt["updated_departments"].append({"id": obj.id, "before": before})
    return obj


def _employee(
    db: Session,
    *,
    row: dict[str, Any],
    department_id: int | None,
    source_key: str,
    receipt: dict[str, Any],
) -> ErpEmployee:
    name = _clean(row.get("name") or row.get("employee_name"))
    department = _clean(row.get("dept") or row.get("department"))
    employee_no = _clean(row.get("emp_no") or row.get("employee_no"))
    external_user_id = _clean(row.get("uid") or row.get("external_user_id") or row.get("user_id"))
    identity_key = employee_identity_key(
        employee_name=name,
        department=department,
        employee_no=employee_no,
        external_user_id=external_user_id,
    )
    obj = db.query(ErpEmployee).filter(ErpEmployee.identity_key == identity_key).first()
    values = {
        "employee_name": name,
        "department_id": department_id,
        "department": department,
        "main_department": _clean(row.get("main_dept") or row.get("main_department")),
        "attendance_group": _clean(row.get("group") or row.get("attendance_group")),
        "employee_no": employee_no,
        "position": _clean(row.get("position")),
        "external_user_id": external_user_id,
    }
    if obj is None:
        obj = ErpEmployee(
            tenant_id=tenant_id_for_write(),
            identity_key=identity_key,
            **values,
            source_system="attendance_import",
            source_key=source_key,
            is_active=True,
        )
        db.add(obj)
        db.flush()
        receipt["created_employee_ids"].append(obj.id)
        return obj

    # A later import may complete blank canonical fields, but must not silently
    # overwrite already-confirmed ERP master data.
    before: dict[str, Any] = {}
    for field, value in values.items():
        current = getattr(obj, field)
        if value not in (None, "") and current in (None, ""):
            before[field] = current
            setattr(obj, field, value)
    if before:
        receipt["updated_employees"].append({"id": obj.id, "before": before})
    return obj


def _daily_records(
    excel_path: Path,
    *,
    month_label: str,
) -> tuple[int, list[Any], str]:
    try:
        from app.shell.taiyangniao_attendance.parser import parse_attendance_workbook
    except ModuleNotFoundError:
        return 0, [], month_label
    parsed = parse_attendance_workbook(excel_path, month=month_label or None)
    return int(parsed.rows_in), list(parsed.records), str(parsed.month or month_label)


def _datetime_list(values: list[Any]) -> list[str]:
    return [
        value.strftime("%Y-%m-%d %H:%M:%S") if hasattr(value, "strftime") else str(value)
        for value in values
    ]


def import_attendance_workbook_to_erp(
    excel_path: Path,
    db: Session,
    *,
    owner_user_id: int | None,
    source_file_key: str,
    source_hash: str = "",
) -> dict[str, Any]:
    """Parse an attendance workbook and persist it atomically in ERP tables."""

    if not excel_path.is_file():
        raise FileNotFoundError(f"Excel 文件不存在: {excel_path}")
    existing = (
        db.query(AttendanceImportBatch)
        .filter(AttendanceImportBatch.source_file == source_file_key)
        .first()
    )
    if existing is not None:
        raise ValueError("attendance_source_already_imported")

    from app.application.attendance_import_app_service import (
        _infer_month_from_filename,
        _parse_workbook,
    )

    departments, employees, workbook_kind = _parse_workbook(excel_path)
    month_label = _infer_month_from_filename(excel_path)
    imported_at = datetime.now(UTC)
    receipt: dict[str, Any] = {
        "storage": "erp",
        "source": ERP_ATTENDANCE_SOURCE,
        "source_file": source_file_key,
        "source_name": excel_path.name,
        "created_department_ids": [],
        "created_employee_ids": [],
        "updated_departments": [],
        "updated_employees": [],
    }
    batch = AttendanceImportBatch(
        tenant_id=tenant_id_for_write(),
        owner_user_id=owner_user_id,
        source_file=source_file_key,
        source_name=excel_path.name,
        source_hash=_clean(source_hash),
        month_label=month_label,
        workbook_kind=workbook_kind,
        rows_in=0,
        rows_written=0,
        department_rows=0,
        employee_rows=0,
        receipt_json="{}",
        imported_at=imported_at,
    )
    db.add(batch)
    db.flush()

    department_by_name: dict[tuple[str, str], ErpDepartment] = {}
    for row in departments:
        obj = _department(
            db,
            name=_clean(row.get("department")),
            parent_name=_clean(row.get("main_department")),
            attendance_group=_clean(row.get("attendance_group")),
            source_key=source_file_key,
            receipt=receipt,
        )
        if obj is not None:
            department_by_name[(obj.name, obj.parent_name)] = obj

    employee_by_identity: dict[str, ErpEmployee] = {}
    for row in employees:
        dept_name = _clean(row.get("dept"))
        main_name = _clean(row.get("main_dept"))
        dept = department_by_name.get((dept_name, main_name))
        if dept is None:
            dept = _department(
                db,
                name=dept_name,
                parent_name=main_name,
                attendance_group=_clean(row.get("group")),
                source_key=source_file_key,
                receipt=receipt,
            )
        obj = _employee(
            db,
            row=row,
            department_id=dept.id if dept else None,
            source_key=source_file_key,
            receipt=receipt,
        )
        employee_by_identity[obj.identity_key] = obj

    rows_in = 0
    daily_records: list[Any] = []
    if workbook_kind == "dingtalk":
        rows_in, daily_records, month_label = _daily_records(excel_path, month_label=month_label)
    for record in daily_records:
        identity = employee_identity_key(
            employee_name=record.employee_name,
            department=record.department,
            employee_no=record.employee_no,
            external_user_id=record.user_id,
        )
        employee = employee_by_identity.get(identity)
        if employee is None:
            dept = _department(
                db,
                name=record.department,
                parent_name="",
                attendance_group=record.attendance_group,
                source_key=source_file_key,
                receipt=receipt,
            )
            employee = _employee(
                db,
                row={
                    "name": record.employee_name,
                    "dept": record.department,
                    "group": record.attendance_group,
                    "emp_no": record.employee_no,
                    "position": record.position,
                    "uid": record.user_id,
                },
                department_id=dept.id if dept else None,
                source_key=source_file_key,
                receipt=receipt,
            )
            employee_by_identity[identity] = employee
        db.add(
            AttendanceDailyRecord(
                tenant_id=tenant_id_for_write(),
                batch_id=batch.id,
                employee_id=employee.id,
                department_id=employee.department_id,
                source_file=source_file_key,
                month_label=month_label,
                source_row=int(record.source_row),
                employee_name=record.employee_name,
                attendance_group=record.attendance_group,
                department=record.department,
                employee_no=record.employee_no,
                position=record.position,
                external_user_id=record.user_id,
                work_date=record.work_date,
                shift_name=record.shift_name,
                daily_times_json=json.dumps(_datetime_list(record.daily_times), ensure_ascii=False),
                raw_times_json=json.dumps(_datetime_list(record.raw_times), ensure_ascii=False),
                all_times_json=json.dumps(
                    _datetime_list(record.all_punch_times()), ensure_ascii=False
                ),
                leave_hours=float(record.leave_hours),
                absent_days=float(record.absent_days),
                late_count_hint=float(record.late_count_hint),
                early_count_hint=float(record.early_count_hint),
                missing_card_count=float(record.missing_card_count),
                notes_json=json.dumps(record.notes, ensure_ascii=False),
                imported_at=imported_at,
            )
        )

    batch.month_label = month_label
    batch.rows_in = rows_in or len(employees)
    batch.rows_written = len(daily_records) or len(employees)
    batch.department_rows = len(departments)
    batch.employee_rows = len(employees)
    receipt.update(
        {
            "batch_id": batch.id,
            "workbook_kind": workbook_kind,
            "month_label": month_label,
            "department_rows": len(departments),
            "employee_rows": len(employees),
            "daily_rows_in": rows_in,
            "daily_rows_written": len(daily_records),
            "sync_ui_tables": False,
        }
    )
    batch.receipt_json = json.dumps(receipt, ensure_ascii=False, sort_keys=True)
    db.flush()
    return receipt


def rollback_attendance_import(
    db: Session, *, source_file: str, batch_id: int | None = None
) -> int:
    query = db.query(AttendanceImportBatch).filter(AttendanceImportBatch.source_file == source_file)
    if batch_id:
        query = query.filter(AttendanceImportBatch.id == int(batch_id))
    batch = query.first()
    if batch is None:
        return 0
    try:
        receipt = json.loads(batch.receipt_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        receipt = {}

    deleted = int(
        db.query(AttendanceDailyRecord)
        .filter(AttendanceDailyRecord.batch_id == batch.id)
        .delete(synchronize_session=False)
        or 0
    )
    for item in reversed(receipt.get("updated_employees") or []):
        obj = db.query(ErpEmployee).filter(ErpEmployee.id == int(item.get("id") or 0)).first()
        if obj:
            for field, value in (item.get("before") or {}).items():
                if hasattr(obj, field):
                    setattr(obj, field, value)
    for employee_id in reversed(receipt.get("created_employee_ids") or []):
        employee_id = int(employee_id)
        still_used = (
            db.query(AttendanceDailyRecord.id)
            .filter(AttendanceDailyRecord.employee_id == employee_id)
            .first()
            or db.query(AttendanceLeaveRecord.id)
            .filter(AttendanceLeaveRecord.employee_id == employee_id)
            .first()
        )
        if not still_used:
            deleted += int(
                db.query(ErpEmployee)
                .filter(ErpEmployee.id == employee_id)
                .delete(synchronize_session=False)
                or 0
            )
    for item in reversed(receipt.get("updated_departments") or []):
        obj = db.query(ErpDepartment).filter(ErpDepartment.id == int(item.get("id") or 0)).first()
        if obj:
            for field, value in (item.get("before") or {}).items():
                if hasattr(obj, field):
                    setattr(obj, field, value)
    for department_id in reversed(receipt.get("created_department_ids") or []):
        department_id = int(department_id)
        still_used = (
            db.query(ErpEmployee.id).filter(ErpEmployee.department_id == department_id).first()
            or db.query(AttendanceDailyRecord.id)
            .filter(AttendanceDailyRecord.department_id == department_id)
            .first()
        )
        if not still_used:
            deleted += int(
                db.query(ErpDepartment)
                .filter(ErpDepartment.id == department_id)
                .delete(synchronize_session=False)
                or 0
            )
    db.delete(batch)
    db.flush()
    return deleted


def legacy_attendance_preview(legacy_db_path: Path) -> dict[str, Any]:
    """Return non-sensitive migration counts from the old Mod-private database."""

    counts = {
        "employees": 0,
        "departments": 0,
        "daily_records": 0,
        "leave_records": 0,
        "import_batches": 0,
    }
    if not legacy_db_path.is_file():
        return {"available": False, "counts": counts}
    table_map = {
        "employees": "attendance_employees",
        "departments": "attendance_departments",
        "daily_records": "attendance_daily_records",
        "leave_records": "attendance_leave_records",
        "import_batches": "attendance_import_batches",
    }
    with sqlite3.connect(str(legacy_db_path)) as conn:
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        for key, table in table_map.items():
            if table in tables:
                counts[key] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] or 0)
    return {"available": any(counts.values()), "counts": counts}


def _legacy_datetime(value: Any, fallback: datetime) -> datetime:
    raw = _clean(value)
    if not raw:
        return fallback
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return fallback


def migrate_legacy_attendance_to_erp(
    db: Session,
    *,
    legacy_db_path: Path,
    owner_user_id: int | None,
) -> dict[str, Any]:
    """Copy one tenant's legacy side database into canonical ERP tables once."""

    preview = legacy_attendance_preview(legacy_db_path)
    if not preview["available"]:
        return {"status": "empty", **preview, "storage": "erp"}
    migration_source = "legacy-migration:taiyangniao-pro"
    existing = (
        db.query(AttendanceImportBatch)
        .filter(AttendanceImportBatch.source_file == migration_source)
        .first()
    )
    if existing is not None:
        return {
            "status": "already_migrated",
            "batch_id": existing.id,
            "storage": "erp",
            **preview,
        }

    conn = sqlite3.connect(str(legacy_db_path))
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        departments = (
            [dict(row) for row in conn.execute("SELECT * FROM attendance_departments").fetchall()]
            if "attendance_departments" in tables
            else []
        )
        employees = (
            [dict(row) for row in conn.execute("SELECT * FROM attendance_employees").fetchall()]
            if "attendance_employees" in tables
            else []
        )
        daily = (
            [dict(row) for row in conn.execute("SELECT * FROM attendance_daily_records").fetchall()]
            if "attendance_daily_records" in tables
            else []
        )
        leaves = (
            [dict(row) for row in conn.execute("SELECT * FROM attendance_leave_records").fetchall()]
            if "attendance_leave_records" in tables
            else []
        )
    finally:
        conn.close()

    now = datetime.now(UTC)
    receipt: dict[str, Any] = {
        "storage": "erp",
        "source": "legacy:taiyangniao-pro",
        "source_file": migration_source,
        "created_department_ids": [],
        "created_employee_ids": [],
        "updated_departments": [],
        "updated_employees": [],
    }
    batch = AttendanceImportBatch(
        tenant_id=tenant_id_for_write(),
        owner_user_id=owner_user_id,
        source_file=migration_source,
        source_name="旧版考勤数据迁移",
        source_hash="",
        month_label="",
        workbook_kind="legacy_migration",
        rows_in=len(daily) or len(employees),
        rows_written=len(daily) or len(employees),
        department_rows=len(departments),
        employee_rows=len(employees),
        receipt_json="{}",
        imported_at=now,
    )
    db.add(batch)
    db.flush()

    departments_by_name: dict[tuple[str, str], ErpDepartment] = {}
    for row in departments:
        obj = _department(
            db,
            name=_clean(row.get("department")),
            parent_name=_clean(row.get("main_department")),
            attendance_group=_clean(row.get("attendance_group")),
            source_key=migration_source,
            receipt=receipt,
        )
        if obj:
            obj.source_system = "legacy_attendance_migration"
            departments_by_name[(obj.name, obj.parent_name)] = obj

    employees_by_identity: dict[str, ErpEmployee] = {}
    for row in employees:
        dept_name = _clean(row.get("department"))
        parent = _clean(row.get("main_department"))
        department = departments_by_name.get((dept_name, parent))
        obj = _employee(
            db,
            row={
                "name": row.get("employee_name"),
                "dept": dept_name,
                "main_dept": parent,
                "group": row.get("attendance_group"),
                "emp_no": row.get("employee_no"),
                "position": row.get("position"),
                "uid": row.get("user_id"),
            },
            department_id=department.id if department else None,
            source_key=migration_source,
            receipt=receipt,
        )
        obj.source_system = "legacy_attendance_migration"
        employees_by_identity[obj.identity_key] = obj

    daily_written = 0
    for row in daily:
        employee = None
        identity = employee_identity_key(
            employee_name=_clean(row.get("employee_name")),
            department=_clean(row.get("department")),
            employee_no=_clean(row.get("employee_no")),
            external_user_id=_clean(row.get("user_id")),
        )
        employee = (
            employees_by_identity.get(identity)
            or db.query(ErpEmployee).filter(ErpEmployee.identity_key == identity).first()
        )
        if employee is None:
            employee = _employee(
                db,
                row={
                    "name": row.get("employee_name"),
                    "dept": row.get("department"),
                    "group": row.get("attendance_group"),
                    "emp_no": row.get("employee_no"),
                    "position": row.get("position"),
                    "uid": row.get("user_id"),
                },
                department_id=None,
                source_key=migration_source,
                receipt=receipt,
            )
        source_token = hashlib.sha256(_clean(row.get("source_file")).encode("utf-8")).hexdigest()[
            :24
        ]
        work_date_raw = _clean(row.get("work_date"))
        try:
            work_date = date.fromisoformat(work_date_raw[:10])
        except ValueError:
            continue
        db.add(
            AttendanceDailyRecord(
                tenant_id=tenant_id_for_write(),
                batch_id=batch.id,
                employee_id=employee.id,
                department_id=employee.department_id,
                source_file=f"legacy:{source_token}",
                month_label=_clean(row.get("month_label")),
                source_row=int(row.get("source_row") or row.get("id") or 0),
                employee_name=employee.employee_name,
                attendance_group=_clean(row.get("attendance_group")),
                department=_clean(row.get("department")),
                employee_no=_clean(row.get("employee_no")),
                position=_clean(row.get("position")),
                external_user_id=_clean(row.get("user_id")),
                work_date=work_date,
                shift_name=_clean(row.get("shift_name")),
                daily_times_json=_clean(row.get("daily_times_json")) or "[]",
                raw_times_json=_clean(row.get("raw_times_json")) or "[]",
                all_times_json=_clean(row.get("all_times_json")) or "[]",
                leave_hours=float(row.get("leave_hours") or 0),
                absent_days=float(row.get("absent_days") or 0),
                late_count_hint=float(row.get("late_count_hint") or 0),
                early_count_hint=float(row.get("early_count_hint") or 0),
                missing_card_count=float(row.get("missing_card_count") or 0),
                notes_json=_clean(row.get("notes_json")) or "[]",
                imported_at=_legacy_datetime(row.get("imported_at"), now),
            )
        )
        daily_written += 1

    leave_written = 0
    for row in leaves:
        employee = find_employee(
            db,
            employee_name=_clean(row.get("employee_name")),
            employee_no=_clean(row.get("employee_no")),
        )
        if employee is None:
            continue
        try:
            leave_date = date.fromisoformat(_clean(row.get("leave_date"))[:10])
        except ValueError:
            continue
        exists = (
            db.query(AttendanceLeaveRecord.id)
            .filter(
                AttendanceLeaveRecord.employee_id == employee.id,
                AttendanceLeaveRecord.leave_date == leave_date,
                AttendanceLeaveRecord.period == _clean(row.get("period")),
                AttendanceLeaveRecord.leave_type == _clean(row.get("leave_type")),
            )
            .first()
        )
        if exists:
            continue
        db.add(
            AttendanceLeaveRecord(
                tenant_id=tenant_id_for_write(),
                receipt_id=_clean(row.get("receipt_id")) or f"legacy_leave_{row.get('id')}",
                employee_id=employee.id,
                employee_name=employee.employee_name,
                employee_no=employee.employee_no,
                external_user_id=employee.external_user_id,
                leave_type=_clean(row.get("leave_type")),
                leave_date=leave_date,
                period=_clean(row.get("period")),
                hours=float(row.get("hours") or 0),
                approval_status=_clean(row.get("approval_status")) or "pending",
                approval_evidence=_clean(row.get("approval_evidence")),
                source_message=_clean(row.get("source_message")),
            )
        )
        leave_written += 1

    receipt.update(
        {
            "batch_id": batch.id,
            "daily_rows_written": daily_written,
            "leave_rows_written": leave_written,
            "employee_rows": len(employees),
            "department_rows": len(departments),
        }
    )
    batch.rows_written = daily_written or len(employees)
    batch.receipt_json = json.dumps(receipt, ensure_ascii=False, sort_keys=True)
    db.flush()
    return {"status": "migrated", **receipt, "counts": preview["counts"]}


def find_employee(
    db: Session,
    *,
    employee_name: str = "",
    employee_no: str = "",
    identifiers: list[str] | None = None,
    names: list[str] | None = None,
) -> ErpEmployee | None:
    query = db.query(ErpEmployee).filter(ErpEmployee.is_active.is_(True))
    if _clean(employee_no):
        value = _clean(employee_no)
        return query.filter(
            or_(ErpEmployee.employee_no == value, ErpEmployee.external_user_id == value)
        ).first()
    if _clean(employee_name):
        return query.filter(ErpEmployee.employee_name == _clean(employee_name)).first()
    clauses = []
    for value in dict.fromkeys(_clean(v) for v in (identifiers or []) if _clean(v)):
        clauses.extend(
            [
                ErpEmployee.external_user_id == value,
                ErpEmployee.employee_no == value,
                ErpEmployee.account_user_id == int(value) if value.isdigit() else False,
            ]
        )
    for value in dict.fromkeys(_clean(v) for v in (names or []) if _clean(v)):
        clauses.append(ErpEmployee.employee_name == value)
    return query.filter(or_(*clauses)).order_by(ErpEmployee.id.desc()).first() if clauses else None


def attendance_rows(
    db: Session,
    *,
    date_start: str = "",
    date_end: str = "",
    employee_name: str = "",
    employee_no: str = "",
    department: str = "",
    limit: int = 5000,
) -> list[dict[str, Any]]:
    _total, rows = attendance_record_page(
        db,
        date_start=date_start,
        date_end=date_end,
        employee_name=employee_name,
        employee_no=employee_no,
        department=department,
        offset=0,
        limit=limit,
    )
    return rows


def attendance_record_page(
    db: Session,
    *,
    date_start: str = "",
    date_end: str = "",
    employee_name: str = "",
    employee_no: str = "",
    department: str = "",
    offset: int = 0,
    limit: int = 50,
) -> tuple[int, list[dict[str, Any]]]:
    """Return an exact ERP attendance page and total without a hidden row cap."""

    query = db.query(AttendanceDailyRecord)
    if date_start:
        query = query.filter(AttendanceDailyRecord.work_date >= date.fromisoformat(date_start))
    if date_end:
        query = query.filter(AttendanceDailyRecord.work_date <= date.fromisoformat(date_end))
    if employee_no:
        query = query.filter(AttendanceDailyRecord.employee_no == _clean(employee_no))
    if employee_name:
        query = query.filter(AttendanceDailyRecord.employee_name == _clean(employee_name))
    if department:
        query = query.filter(AttendanceDailyRecord.department == _clean(department))
    total = query.count()
    rows = (
        query.order_by(
            AttendanceDailyRecord.work_date,
            AttendanceDailyRecord.employee_name,
            AttendanceDailyRecord.id,
        )
        .offset(max(0, int(offset)))
        .limit(max(1, min(5000, int(limit))))
        .all()
    )
    return total, [
        {
            "id": row.id,
            "employee_name": row.employee_name,
            "employee_no": row.employee_no,
            "department": row.department,
            "position": row.position,
            "user_id": row.external_user_id,
            "work_date": row.work_date.isoformat(),
            "shift_name": row.shift_name,
            "daily_times_json": row.daily_times_json,
            "raw_times_json": row.raw_times_json,
            "all_times_json": row.all_times_json,
            "leave_hours": row.leave_hours,
            "absent_days": row.absent_days,
            "late_count_hint": row.late_count_hint,
            "early_count_hint": row.early_count_hint,
            "missing_card_count": row.missing_card_count,
            "notes_json": row.notes_json,
            "source_file": row.source_file,
            "imported_at": row.imported_at.isoformat(),
        }
        for row in rows
    ]


__all__ = [
    "ERP_ATTENDANCE_SOURCE",
    "attendance_record_page",
    "attendance_rows",
    "employee_identity_key",
    "erp_attendance_schema_available",
    "find_employee",
    "import_attendance_workbook_to_erp",
    "legacy_attendance_preview",
    "migrate_legacy_attendance_to_erp",
    "rollback_attendance_import",
]
