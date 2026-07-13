"""Verified write, export, and print actions for chat business safety."""

from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.application import chat_business_safety as compatibility_module
from app.application.chat_business_safety import (
    _DB_NAME,
    _LEAVE_CANCEL_RE,
    _LEAVE_MODIFY_RE,
    _LEAVE_TYPES,
    BusinessActorIdentity,
    BusinessChatIntent,
    _compact,
    _connect_existing,
    _extract_person_name,
    _new_receipt,
    _not_executed,
    _payload,
    _resolve_person_from_actor,
    _table_exists,
)
from app.application.chat_business_safety_read import (
    _attendance_error_payload,
    _attendance_rows,
    _json_list,
    _parse_date_scope,
)


def _db_path() -> Path:
    return compatibility_module._db_path()


def resolve_safe_workspace_relpath(relpath: str) -> Path:
    return compatibility_module.resolve_safe_workspace_relpath(relpath)


def _get_printer_service():
    return compatibility_module._get_printer_service()


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
    if not fields.get("employee_name") and re.search(r"我|本人", message):
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

    db_path = _db_path()
    if not db_path.is_file():
        return _not_executed(
            intent,
            "请假未登记：本机尚无人员库，无法核验员工身份。请先导入人员名单。",
            reason="personnel_database_missing",
            source=f"{_DB_NAME}:attendance_leave_records",
            status="unavailable",
        )
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    source = f"{_DB_NAME}:attendance_leave_records"
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
            record_id = int(cur.lastrowid)
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


_EXPORT_COLUMNS = (
    ("work_date", "日期"),
    ("employee_name", "姓名"),
    ("employee_no", "工号"),
    ("department", "部门"),
    ("position", "岗位"),
    ("shift_name", "班次"),
    ("all_times_json", "打卡时间"),
    ("leave_hours", "请假小时"),
    ("absent_days", "缺勤天数"),
    ("late_count_hint", "迟到标记"),
    ("early_count_hint", "早退标记"),
    ("missing_card_count", "缺卡次数"),
)

_PERSONNEL_EXPORT_COLUMNS = (
    ("employee_name", "姓名"),
    ("employee_no", "工号"),
    ("department", "部门"),
    ("main_department", "主部门"),
    ("attendance_group", "考勤组"),
    ("position", "岗位"),
    ("user_id", "绑定账号"),
)


def _create_personnel_export(rows: list[dict[str, Any]]) -> tuple[Path, str]:
    import openpyxl

    token = uuid.uuid4().hex[:12]
    filename = f"personnel-roster-{token}.xlsx"
    relpath = f"attendance_exports/{filename}"
    output = resolve_safe_workspace_relpath(relpath)
    output.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "人员名单"
    ws.append([label for _, label in _PERSONNEL_EXPORT_COLUMNS])
    for row in rows:
        ws.append([row.get(key) for key, _ in _PERSONNEL_EXPORT_COLUMNS])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for col in ws.columns:
        width = min(36, max(10, max(len(str(cell.value or "")) for cell in col) + 2))
        ws.column_dimensions[col[0].column_letter].width = width
    wb.save(output)
    wb.close()
    return output, relpath


def _handle_personnel_export(
    message: str, intent: BusinessChatIntent, *, actor: BusinessActorIdentity
) -> dict[str, Any]:
    del message, actor  # Route authentication already protects this operation.
    conn = _connect_existing()
    source = f"{_DB_NAME}:attendance_employees"
    if conn is None:
        return _not_executed(
            intent,
            "人员名单未导出：本机尚无可核验的人员库。请先导入人员名单。",
            reason="personnel_database_missing",
            source=source,
            status="unavailable",
        )
    try:
        if not _table_exists(conn, "attendance_employees"):
            return _not_executed(
                intent,
                "人员名单未导出：人员库尚未初始化。请先导入人员名单。",
                reason="personnel_table_missing",
                source=source,
                status="unavailable",
            )
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT employee_name, employee_no, department, main_department,
                       attendance_group, position, user_id
                FROM attendance_employees
                ORDER BY employee_name, id
                LIMIT 50000
                """
            ).fetchall()
        ]
    except sqlite3.Error as exc:
        return _not_executed(
            intent,
            "人员名单未导出：读取真实人员库失败。",
            reason=f"personnel_query_failed:{exc}",
            source=source,
            status="failed",
        )
    finally:
        conn.close()

    if not rows:
        return _not_executed(
            intent,
            "人员名单未导出：已查询真实人员库，但当前没有人员记录。",
            reason="no_personnel_rows",
            source=source,
        )
    try:
        output, relpath = _create_personnel_export(rows)
    except Exception as exc:  # noqa: BLE001 - converted to a truthful receipt
        return _not_executed(
            intent,
            "人员名单未导出：文件写出失败。",
            reason=f"personnel_export_failed:{exc}",
            source=source,
            status="failed",
        )

    url = f"/api/mod/taiyangniao-pro/attendance/download?relpath={quote(relpath)}"
    artifact = {
        "kind": "file",
        "filename": output.name,
        "path": str(output),
        "download_url": url,
        "size_bytes": output.stat().st_size,
    }
    receipt = _new_receipt(
        intent,
        status="completed",
        executed=True,
        verified=output.is_file() and output.stat().st_size > 0,
        source=source,
        affected_rows=len(rows),
        artifacts=[artifact],
    )
    text = (
        f"人员名单已根据真实人员库生成，共 {len(rows)} 行。\n"
        f"[下载 {output.name}]({url})\n"
        f"导出回执：{receipt['receipt_id']}。"
    )
    return _payload(text, intent, receipt)


def _create_attendance_export(rows: list[dict[str, Any]], meta: dict[str, Any]) -> tuple[Path, str]:
    import openpyxl

    token = uuid.uuid4().hex[:12]
    label = str(meta.get("date_start") or "records")
    if meta.get("scope") == "month":
        label = label[:7]
    filename = f"attendance-{label}-{token}.xlsx"
    relpath = f"attendance_exports/{filename}"
    output = resolve_safe_workspace_relpath(relpath)
    output.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "考勤明细"
    ws.append([label for _, label in _EXPORT_COLUMNS])
    for row in rows:
        values: list[Any] = []
        for key, _ in _EXPORT_COLUMNS:
            value = row.get(key)
            if key == "all_times_json":
                value = "、".join(_json_list(value))
            values.append(value)
        ws.append(values)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for col in ws.columns:
        width = min(36, max(10, max(len(str(cell.value or "")) for cell in col) + 2))
        ws.column_dimensions[col[0].column_letter].width = width
    wb.save(output)
    wb.close()
    return output, relpath


def _handle_attendance_export(
    message: str, intent: BusinessChatIntent, *, actor: BusinessActorIdentity
) -> dict[str, Any]:
    from app.application.chat_business_safety_attendance_actions import (
        handle_attendance_export,
    )

    return handle_attendance_export(
        message,
        intent,
        actor=actor,
        attendance_rows=_attendance_rows,
        attendance_error_payload=_attendance_error_payload,
        create_attendance_export=_create_attendance_export,
    )


def _handle_attendance_print(
    message: str, intent: BusinessChatIntent, *, actor: BusinessActorIdentity
) -> dict[str, Any]:
    from app.application.chat_business_safety_attendance_actions import (
        handle_attendance_print,
    )

    return handle_attendance_print(
        message,
        intent,
        actor=actor,
        attendance_rows=_attendance_rows,
        attendance_error_payload=_attendance_error_payload,
        create_attendance_export=_create_attendance_export,
        get_printer_service=_get_printer_service,
    )
