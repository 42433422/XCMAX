"""Verified leave writes for protected natural-language chat actions."""

from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import UTC, date, datetime
from typing import Any

from app.application.chat_business_safety_attendance import _parse_date_scope
from app.application.chat_business_safety_core import (
    _DB_NAME,
    _LEAVE_CANCEL_RE,
    _LEAVE_MODIFY_RE,
    _LEAVE_TYPES,
    BusinessActorIdentity,
    BusinessChatIntent,
    _compact,
    _connect_existing,
    _db_path,
    _extract_person_name,
    _new_receipt,
    _not_executed,
    _payload,
    _resolve_person_from_actor,
    _table_exists,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS


def _ensure_leave_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance_leave_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id TEXT NOT NULL UNIQUE,
            employee_name TEXT NOT NULL,
            employee_no TEXT NOT NULL DEFAULT '',
            user_id TEXT NOT NULL DEFAULT '',
            leave_type TEXT NOT NULL,
            leave_date TEXT NOT NULL,
            period TEXT NOT NULL,
            hours REAL NOT NULL,
            approval_status TEXT NOT NULL,
            approval_evidence TEXT NOT NULL DEFAULT '',
            source_message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(employee_name, leave_date, period, leave_type)
        )
        """
    )


def _leave_fields(message: str) -> dict[str, Any]:
    text = _compact(message)
    leave_type = next((item for item in _LEAVE_TYPES if item in text), "")
    scope = _parse_date_scope(text)
    leave_date = scope[1] if scope and scope[0] == "day" else ""
    if "上午" in text:
        period, hours = "morning", 4.0
    elif "下午" in text:
        period, hours = "afternoon", 4.0
    elif "半天" in text:
        period, hours = "half_day_unspecified", 4.0
    elif "全天" in text or "一天" in text:
        period, hours = "full_day", 8.0
    else:
        match = re.search(r"(\d+(?:\.\d+)?)小时", text)
        period, hours = ("hours", float(match.group(1))) if match else ("", 0.0)
    approval_positive = bool(
        re.search(r"(?:主管|领导|经理)?.{0,8}(?:已|已经)?(?:审批通过|批准|同意)", text)
    )
    approval_negative = bool(
        re.search(r"未(?:审批|批准|同意)|没有(?:审批|批准|同意)|不(?:批准|同意)|拒绝", text)
    )
    approved = approval_positive and not approval_negative
    return {
        "employee_name": _extract_person_name(text),
        "leave_type": leave_type,
        "leave_date": leave_date,
        "period": period,
        "hours": hours,
        "approval_status": "reported_approved" if approved else "pending",
        "approval_evidence": "用户声明已审批通过，未核验审批单或审批 ID" if approved else "",
        "approval_verified": False,
    }


def _legacy_leave_write(
    message: str,
    intent: BusinessChatIntent,
    *,
    actor: BusinessActorIdentity,
    fields: dict[str, Any],
) -> dict[str, Any]:
    """Transitional write used only while an old desktop has not migrated schema."""

    db_path = _db_path()
    if not db_path.is_file():
        return _not_executed(
            intent,
            "请假未登记：本机尚无人员库，无法核验员工身份。请先导入人员名单。",
            reason="personnel_database_missing",
            source=f"legacy:{_DB_NAME}:attendance_leave_records",
            status="unavailable",
        )
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    source = f"legacy:{_DB_NAME}:attendance_leave_records"
    try:
        if not _table_exists(conn, "attendance_employees"):
            return _not_executed(
                intent,
                "请假未登记：人员库尚未初始化，无法核验员工身份。",
                reason="personnel_table_missing",
                source=source,
                status="unavailable",
            )
        employee = conn.execute(
            """
            SELECT employee_name, employee_no, user_id FROM attendance_employees
            WHERE TRIM(employee_name) = ? ORDER BY id DESC LIMIT 1
            """,
            (fields["employee_name"],),
        ).fetchone()
        if employee is None:
            return _not_executed(
                intent,
                f"请假未登记：真实人员库中没有找到“{fields['employee_name']}”，系统不会为未知员工创建记录。",
                reason="employee_not_found",
                source=source,
                details={"employee_name": fields["employee_name"]},
            )
        _ensure_leave_schema(conn)
        existing = conn.execute(
            """
            SELECT * FROM attendance_leave_records
            WHERE employee_name=? AND leave_date=? AND period=? AND leave_type=?
            LIMIT 1
            """,
            (
                fields["employee_name"],
                fields["leave_date"],
                fields["period"],
                fields["leave_type"],
            ),
        ).fetchone()
        now = datetime.now().isoformat(timespec="seconds")
        if existing is not None:
            if (
                fields["approval_status"] == "reported_approved"
                and existing["approval_status"] != "reported_approved"
            ):
                conn.execute(
                    """
                    UPDATE attendance_leave_records
                    SET approval_status='reported_approved', approval_evidence=?, updated_at=?
                    WHERE id=?
                    """,
                    (fields["approval_evidence"], now, existing["id"]),
                )
                conn.commit()
                existing = conn.execute(
                    "SELECT * FROM attendance_leave_records WHERE id=?", (existing["id"],)
                ).fetchone()
                status = "updated"
            else:
                status = "already_exists"
            receipt_id = str(existing["receipt_id"])
            record_id = int(existing["id"])
        else:
            receipt_id = f"leave_{uuid.uuid4().hex}"
            cur = conn.execute(
                """
                INSERT INTO attendance_leave_records (
                    receipt_id, employee_name, employee_no, user_id, leave_type,
                    leave_date, period, hours, approval_status, approval_evidence,
                    source_message, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    fields["employee_name"],
                    str(employee["employee_no"] or ""),
                    str(employee["user_id"] or actor.local_user_id or ""),
                    fields["leave_type"],
                    fields["leave_date"],
                    fields["period"],
                    fields["hours"],
                    fields["approval_status"],
                    fields["approval_evidence"],
                    message[:2000],
                    now,
                    now,
                ),
            )
            record_id = int(cur.lastrowid or 0)
            conn.commit()
            status = "created"
    except sqlite3.Error as exc:
        conn.rollback()
        return _not_executed(
            intent,
            "请假未登记：写入真实请假记录失败。",
            reason=f"leave_write_failed:{exc}",
            source=source,
            status="failed",
        )
    finally:
        conn.close()
    return _leave_success_payload(
        intent,
        fields=fields,
        source=source,
        status=status,
        record_id=record_id,
        receipt_id=receipt_id,
    )


def _leave_success_payload(
    intent: BusinessChatIntent,
    *,
    fields: dict[str, Any],
    source: str,
    status: str,
    record_id: int,
    receipt_id: str,
) -> dict[str, Any]:
    approval_label = (
        "按用户声明记录为已审批（未核验审批单/审批 ID）"
        if fields["approval_status"] == "reported_approved"
        else "待审批"
    )
    receipt = _new_receipt(
        intent,
        status=status,
        executed=True,
        verified=True,
        source=source,
        affected_rows=1,
        details={
            **fields,
            "record_id": record_id,
            "write_receipt_id": receipt_id,
        },
    )
    action_label = "记录已存在" if status == "already_exists" else "登记成功"
    text = (
        f"请假{action_label}：{fields['employee_name']}，{fields['leave_date']}，"
        f"{fields['leave_type']} {fields['hours']:g} 小时，状态为{approval_label}。\n"
        f"业务记录 ID：{record_id}；写入回执：{receipt_id}。"
    )
    return _payload(text, intent, receipt)


def _handle_leave_write(
    message: str, intent: BusinessChatIntent, *, actor: BusinessActorIdentity
) -> dict[str, Any]:
    if _LEAVE_CANCEL_RE.search(message):
        return _not_executed(
            intent,
            "请假取消未执行：当前聊天工具只支持新增登记，尚未接入可核验的撤销接口。请在请假记录中选择原记录取消；系统不会把聊天回复当成取消回执。",
            reason="leave_cancel_tool_unavailable",
        )
    if _LEAVE_MODIFY_RE.search(message):
        return _not_executed(
            intent,
            "请假修改未执行：当前聊天工具尚未接入可核验的修改接口。请在请假记录中编辑原记录；没有更新回执前系统不会声称修改成功。",
            reason="leave_modify_tool_unavailable",
        )
    fields = _leave_fields(message)
    from app.application.erp_attendance_app_service import (
        erp_attendance_schema_available,
        find_employee,
    )
    from app.db import HostSessionLocal

    schema_db = HostSessionLocal()
    try:
        erp_schema_ready = erp_attendance_schema_available(schema_db)
    finally:
        schema_db.close()
    if not fields.get("employee_name") and re.search(r"我|本人", message):
        if erp_schema_ready:
            identity_db = HostSessionLocal()
            try:
                person = find_employee(
                    identity_db,
                    identifiers=[
                        item
                        for item in (
                            actor.local_user_id,
                            actor.username,
                            actor.trusted_client_user_id,
                        )
                        if item
                    ],
                    names=[item for item in (actor.display_name, actor.username) if item],
                )
                if person is not None:
                    fields["employee_name"] = str(person.employee_name or "")
            finally:
                identity_db.close()
        else:
            identity_conn = _connect_existing()
            try:
                person = _resolve_person_from_actor(identity_conn, actor) if identity_conn else None
                if person is not None:
                    fields["employee_name"] = str(person["employee_name"] or "")
            finally:
                if identity_conn is not None:
                    identity_conn.close()
    missing = [
        label
        for key, label in (
            ("employee_name", "员工姓名"),
            ("leave_type", "请假类型"),
            ("leave_date", "请假日期"),
            ("period", "时段或时长"),
        )
        if not fields.get(key)
    ]
    if missing:
        return _not_executed(
            intent,
            f"请假未登记：还缺少{'、'.join(missing)}。补全后我才能写入并返回真实登记回执。",
            reason="missing_required_fields",
            details={"missing_fields": missing},
        )

    if not erp_schema_ready:
        return _legacy_leave_write(message, intent, actor=actor, fields=fields)

    from app.db.models.hr_attendance import AttendanceLeaveRecord

    db = HostSessionLocal()
    source = "erp:erp_attendance_leave_records"
    try:
        employee = find_employee(db, employee_name=fields["employee_name"])
        if employee is None:
            return _not_executed(
                intent,
                f"请假未登记：ERP 人员档案中没有找到“{fields['employee_name']}”，系统不会为未知员工创建记录。",
                reason="employee_not_found",
                source=source,
                details={"employee_name": fields["employee_name"]},
            )

        leave_date = date.fromisoformat(str(fields["leave_date"]))
        existing = (
            db.query(AttendanceLeaveRecord)
            .filter(
                AttendanceLeaveRecord.employee_id == employee.id,
                AttendanceLeaveRecord.leave_date == leave_date,
                AttendanceLeaveRecord.period == fields["period"],
                AttendanceLeaveRecord.leave_type == fields["leave_type"],
            )
            .first()
        )
        now = datetime.now(UTC)
        if existing is not None:
            if (
                fields["approval_status"] == "reported_approved"
                and existing.approval_status != "reported_approved"
            ):
                existing.approval_status = "reported_approved"
                existing.approval_evidence = fields["approval_evidence"]
                existing.updated_at = now
                db.commit()
                status = "updated"
            else:
                status = "already_exists"
            receipt_id = str(existing.receipt_id)
            record_id = int(existing.id)
        else:
            receipt_id = f"leave_{uuid.uuid4().hex}"
            obj = AttendanceLeaveRecord(
                receipt_id=receipt_id,
                employee_id=employee.id,
                employee_name=employee.employee_name,
                employee_no=employee.employee_no,
                external_user_id=employee.external_user_id or actor.local_user_id or "",
                leave_type=fields["leave_type"],
                leave_date=leave_date,
                period=fields["period"],
                hours=fields["hours"],
                approval_status=fields["approval_status"],
                approval_evidence=fields["approval_evidence"],
                source_message=message[:2000],
                created_at=now,
                updated_at=now,
            )
            db.add(obj)
            db.commit()
            record_id = int(obj.id)
            status = "created"
    except RECOVERABLE_ERRORS as exc:
        db.rollback()
        return _not_executed(
            intent,
            "请假未登记：写入真实请假记录失败。",
            reason=f"leave_write_failed:{exc}",
            source=source,
            status="failed",
        )
    finally:
        db.close()

    return _leave_success_payload(
        intent,
        fields=fields,
        source=source,
        status=status,
        record_id=record_id,
        receipt_id=receipt_id,
    )
