"""Personnel, organization, attendance, approval, print, and template sync appliers."""

from __future__ import annotations

import logging
import sys
from datetime import UTC
from typing import Any

logger = logging.getLogger(__name__)


def _facade() -> Any:
    return sys.modules["app.services.xcmax_sync_service"]


@_facade().register_entity_applier("personnel")
def _apply_personnel(item: dict[str, Any]) -> None:
    """人员变更：写入 ERP 人员档案，不再镜像成产品。"""
    payload = item.get("payload") or {}
    name = str(payload.get("name") or payload.get("employee_name") or "").strip()
    if not name:
        return
    try:
        from app.application.erp_attendance_app_service import employee_identity_key
        from app.db import HostSessionLocal
        from app.db.models.hr_attendance import ErpDepartment, ErpEmployee
        from app.infrastructure.tenant_scope import (
            current_tenant_id,
            tenant_id_for_write,
            tenant_scope,
        )

        dept = str(payload.get("department") or "").strip()
        requested_tenant = payload.get("tenant_id") or item.get("tenant_id") or current_tenant_id()
        with tenant_scope(int(requested_tenant) if requested_tenant is not None else None):
            db = HostSessionLocal()
            try:
                department = None
                if dept:
                    parent = str(payload.get("main_department") or "").strip()
                    department = (
                        db.query(ErpDepartment)
                        .filter(ErpDepartment.name == dept, ErpDepartment.parent_name == parent)
                        .first()
                    )
                    if department is None:
                        department = ErpDepartment(
                            tenant_id=tenant_id_for_write(),
                            name=dept,
                            parent_name=parent,
                            attendance_group=str(payload.get("attendance_group") or "XCmax"),
                            source_system="xcmax_sync",
                            source_key=str(item.get("entity_id") or dept),
                        )
                        db.add(department)
                        db.flush()
                identity = employee_identity_key(
                    employee_name=name,
                    department=dept,
                    employee_no=str(payload.get("employee_no") or ""),
                    external_user_id=str(payload.get("user_id") or ""),
                )
                obj = db.query(ErpEmployee).filter(ErpEmployee.identity_key == identity).first()
                if str(item.get("operation") or "sync") == "delete":
                    if obj:
                        obj.is_active = False
                        db.commit()
                    return
                if obj is None:
                    obj = ErpEmployee(
                        tenant_id=tenant_id_for_write(),
                        identity_key=identity,
                        employee_name=name,
                        department_id=department.id if department else None,
                        department=dept,
                        main_department=str(payload.get("main_department") or dept),
                        attendance_group=str(payload.get("attendance_group") or "XCmax"),
                        employee_no=str(payload.get("employee_no") or ""),
                        position=str(payload.get("position") or ""),
                        external_user_id=str(payload.get("user_id") or ""),
                        account_user_id=(
                            int(payload["account_user_id"])
                            if str(payload.get("account_user_id") or "").isdigit()
                            else None
                        ),
                        source_system="xcmax_sync",
                        source_key=str(item.get("entity_id") or payload.get("employee_id") or name),
                        is_active=True,
                    )
                    db.add(obj)
                else:
                    obj.employee_name = name
                    obj.department_id = department.id if department else obj.department_id
                    obj.department = dept
                    obj.main_department = str(payload.get("main_department") or dept)
                    obj.attendance_group = str(
                        payload.get("attendance_group") or obj.attendance_group or "XCmax"
                    )
                    obj.employee_no = str(payload.get("employee_no") or obj.employee_no or "")
                    obj.position = str(payload.get("position") or obj.position or "")
                    obj.external_user_id = str(payload.get("user_id") or obj.external_user_id or "")
                    obj.is_active = True
                db.commit()
            finally:
                db.close()
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("apply_personnel failed for %s: %s", name, exc)


@_facade().register_entity_applier("department")
def _apply_department(item: dict[str, Any]) -> None:
    """部门变更：写入 ERP 组织档案，不再镜像成客户。"""
    payload = item.get("payload") or {}
    dept = str(payload.get("department") or payload.get("customer_name") or "").strip()
    if not dept:
        return
    try:
        from app.db import HostSessionLocal
        from app.db.models.hr_attendance import ErpDepartment
        from app.infrastructure.tenant_scope import (
            current_tenant_id,
            tenant_id_for_write,
            tenant_scope,
        )

        requested_tenant = payload.get("tenant_id") or item.get("tenant_id") or current_tenant_id()
        with tenant_scope(int(requested_tenant) if requested_tenant is not None else None):
            db = HostSessionLocal()
            try:
                parent = str(payload.get("main_department") or dept).strip()
                obj = (
                    db.query(ErpDepartment)
                    .filter(ErpDepartment.name == dept, ErpDepartment.parent_name == parent)
                    .first()
                )
                if str(item.get("operation") or "sync") == "delete":
                    if obj:
                        obj.is_active = False
                        db.commit()
                    return
                if obj is None:
                    obj = ErpDepartment(
                        tenant_id=tenant_id_for_write(),
                        name=dept,
                        parent_name=parent,
                        attendance_group=str(payload.get("attendance_group") or "XCmax"),
                        source_system="xcmax_sync",
                        source_key=str(item.get("entity_id") or dept),
                        is_active=True,
                    )
                    db.add(obj)
                else:
                    obj.attendance_group = str(
                        payload.get("attendance_group") or obj.attendance_group or "XCmax"
                    )
                    obj.is_active = True
                db.commit()
            finally:
                db.close()
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("apply_department failed for %s: %s", dept, exc)


@_facade().register_entity_applier("attendance")
def _apply_attendance(item: dict[str, Any]) -> None:
    """考勤记录变更：写入 ERP 考勤表，不再复用发货记录。"""
    payload = item.get("payload") or {}
    operation = item.get("operation", "sync")
    try:
        import json
        from datetime import date, datetime

        from app.application.erp_attendance_app_service import find_employee
        from app.db import HostSessionLocal
        from app.db.models.hr_attendance import AttendanceDailyRecord, AttendanceImportBatch
        from app.infrastructure.tenant_scope import (
            current_tenant_id,
            tenant_id_for_write,
            tenant_scope,
        )

        employee_name = str(
            payload.get("employee_name") or payload.get("purchase_unit") or ""
        ).strip()
        work_date_raw = str(payload.get("work_date") or payload.get("date") or "").strip()
        if not employee_name or not work_date_raw:
            return
        work_date = date.fromisoformat(work_date_raw[:10])
        source_key = f"xcmax_sync:{item.get('entity_id') or payload.get('id') or employee_name + ':' + work_date.isoformat()}"
        requested_tenant = payload.get("tenant_id") or item.get("tenant_id") or current_tenant_id()
        with tenant_scope(int(requested_tenant) if requested_tenant is not None else None):
            db = HostSessionLocal()
            try:
                batch = (
                    db.query(AttendanceImportBatch)
                    .filter(AttendanceImportBatch.source_file == source_key)
                    .first()
                )
                if operation == "delete":
                    if batch:
                        db.query(AttendanceDailyRecord).filter(
                            AttendanceDailyRecord.batch_id == batch.id
                        ).delete(synchronize_session=False)
                        db.delete(batch)
                        db.commit()
                    return
                employee = find_employee(
                    db,
                    employee_name=employee_name,
                    employee_no=str(payload.get("employee_no") or ""),
                )
                if employee is None:
                    logger.warning(
                        "apply_attendance skipped unknown ERP employee: %s", employee_name
                    )
                    return
                now = datetime.now(UTC)
                if batch is None:
                    batch = AttendanceImportBatch(
                        tenant_id=tenant_id_for_write(),
                        owner_user_id=None,
                        source_file=source_key,
                        source_name="XCmax sync",
                        source_hash="",
                        month_label=work_date.strftime("%Y-%m"),
                        workbook_kind="xcmax_sync",
                        rows_in=1,
                        rows_written=1,
                        department_rows=0,
                        employee_rows=0,
                        receipt_json=json.dumps(
                            {"storage": "erp", "source_file": source_key}, ensure_ascii=False
                        ),
                        imported_at=now,
                    )
                    db.add(batch)
                    db.flush()
                row = (
                    db.query(AttendanceDailyRecord)
                    .filter(
                        AttendanceDailyRecord.source_file == source_key,
                        AttendanceDailyRecord.source_row == int(payload.get("source_row") or 1),
                    )
                    .first()
                )
                values = {
                    "employee_id": employee.id,
                    "department_id": employee.department_id,
                    "employee_name": employee.employee_name,
                    "attendance_group": str(
                        payload.get("attendance_group") or employee.attendance_group or ""
                    ),
                    "department": str(payload.get("department") or employee.department or ""),
                    "employee_no": employee.employee_no,
                    "position": employee.position,
                    "external_user_id": employee.external_user_id,
                    "work_date": work_date,
                    "shift_name": str(payload.get("shift_name") or ""),
                    "daily_times_json": json.dumps(
                        payload.get("daily_times") or [], ensure_ascii=False
                    ),
                    "raw_times_json": json.dumps(
                        payload.get("raw_times") or [], ensure_ascii=False
                    ),
                    "all_times_json": json.dumps(
                        payload.get("all_times") or [], ensure_ascii=False
                    ),
                    "leave_hours": float(payload.get("leave_hours") or 0),
                    "absent_days": float(payload.get("absent_days") or 0),
                    "late_count_hint": float(payload.get("late_count_hint") or 0),
                    "early_count_hint": float(payload.get("early_count_hint") or 0),
                    "missing_card_count": float(payload.get("missing_card_count") or 0),
                    "notes_json": json.dumps(payload.get("notes") or [], ensure_ascii=False),
                    "imported_at": now,
                }
                if row is None:
                    row = AttendanceDailyRecord(
                        tenant_id=tenant_id_for_write(),
                        batch_id=batch.id,
                        source_file=source_key,
                        month_label=work_date.strftime("%Y-%m"),
                        source_row=int(payload.get("source_row") or 1),
                        **values,
                    )
                    db.add(row)
                else:
                    for field, value in values.items():
                        setattr(row, field, value)
                db.commit()
            finally:
                db.close()
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("apply_attendance failed: %s", exc)


@_facade().register_entity_applier("approval")
def _apply_approval(item: dict[str, Any]) -> None:
    """审批请求变更：更新 approval_requests 表的状态字段。"""
    payload = item.get("payload") or {}
    operation = item.get("operation", "sync")
    try:
        from datetime import datetime as _dt

        from app.db import get_db
        from app.db.models.approval import ApprovalRequest

        with get_db() as db:
            record_id = payload.get("id")
            if not record_id:
                return
            obj = db.query(ApprovalRequest).filter(ApprovalRequest.id == record_id).first()
            if not obj:
                return
            if operation == "delete":
                db.delete(obj)
            else:
                for col in ("status", "title", "description", "priority", "applicant_name"):
                    if col in payload:
                        setattr(obj, col, payload[col])
                obj.updated_at = _dt.now()
            db.commit()
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("apply_approval failed: %s", exc)


@_facade().register_entity_applier("approval_flow")
def _apply_approval_flow(item: dict[str, Any]) -> None:
    """审批流程定义变更：同步 approval_flows 表的 is_active 和配置字段。"""
    payload = item.get("payload") or {}
    try:
        from datetime import datetime as _dt

        from app.db import get_db
        from app.db.models.approval import ApprovalFlow

        with get_db() as db:
            flow_key = str(payload.get("flow_key") or "").strip()
            if not flow_key:
                return
            obj = db.query(ApprovalFlow).filter(ApprovalFlow.flow_key == flow_key).first()
            if obj:
                for col in ("flow_name", "description", "is_active", "timeout_hours"):
                    if col in payload:
                        setattr(obj, col, payload[col])
                obj.updated_at = _dt.now()
                db.commit()
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("apply_approval_flow failed: %s", exc)


@_facade().register_entity_applier("print_job")
def _apply_print_job(item: dict[str, Any]) -> None:
    """打印任务变更：写入打印作业日志表（若存在），否则记录结构化日志。"""
    payload = item.get("payload") or {}
    operation = item.get("operation", "sync")
    try:
        from app.db import get_db

        with get_db() as db:
            from sqlalchemy import text

            db.execute(
                text(
                    "\n                INSERT INTO print_jobs (entity_id, template, status, payload_json, created_at)\n                VALUES (:eid, :tpl, :status, :payload, NOW())\n                ON CONFLICT (entity_id) DO UPDATE SET\n                    status = EXCLUDED.status,\n                    payload_json = EXCLUDED.payload_json\n            "
                ),
                {
                    "eid": item.get("entity_id") or "",
                    "tpl": str(payload.get("template") or ""),
                    "status": str(payload.get("status") or operation),
                    "payload": _facade().json.dumps(payload, ensure_ascii=False, default=str),
                },
            )
            db.commit()
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.info(
            "print_job sync [%s] entity=%s status=%s",
            operation,
            item.get("entity_id"),
            payload.get("status"),
        )


@_facade().register_entity_applier("template")
def _apply_template(item: dict[str, Any]) -> None:
    """文档/打印模板变更：更新 document_templates 表或本地模板文件路径记录。"""
    payload = item.get("payload") or {}
    operation = item.get("operation", "sync")
    try:
        from sqlalchemy import text

        from app.db import get_db

        template_id = str(payload.get("template_id") or item.get("entity_id") or "").strip()
        if not template_id:
            return
        with get_db() as db:
            if operation == "delete":
                db.execute(
                    text("DELETE FROM document_templates WHERE slug = :s"), {"s": template_id}
                )
            else:
                db.execute(
                    text(
                        "\n                    INSERT INTO document_templates (slug, name, category, is_active, created_at)\n                    VALUES (:slug, :name, :cat, true, NOW())\n                    ON CONFLICT (slug) DO UPDATE SET\n                        name = EXCLUDED.name,\n                        category = EXCLUDED.category\n                "
                    ),
                    {
                        "slug": template_id,
                        "name": str(payload.get("name") or template_id),
                        "cat": str(payload.get("category") or "word"),
                    },
                )
            db.commit()
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.debug("apply_template non-fatal: %s", exc)
