"""Verified personnel and attendance reads for chat business safety."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict
from datetime import date, timedelta
from typing import Any

from app.application.chat_business_safety import (
    _DB_NAME,
    _LEAVE_RE,
    BusinessActorIdentity,
    BusinessChatIntent,
    _compact,
    _connect_existing,
    _extract_department,
    _extract_employee_no,
    _extract_person_name,
    _new_receipt,
    _not_executed,
    _payload,
    _resolve_person_from_actor,
    _table_exists,
)


def _handle_personnel_read(
    message: str, intent: BusinessChatIntent, *, actor: BusinessActorIdentity
) -> dict[str, Any]:
    conn = _connect_existing()
    source = f"{_DB_NAME}:attendance_employees"
    if conn is None:
        return _not_executed(
            intent,
            "人员查询未执行：本机尚无可核验的人员库。请先导入人员名单。",
            reason="personnel_database_missing",
            source=source,
            status="unavailable",
        )
    try:
        if not _table_exists(conn, "attendance_employees"):
            return _not_executed(
                intent,
                "人员查询未执行：人员库尚未初始化。请先导入人员名单。",
                reason="personnel_table_missing",
                source=source,
                status="unavailable",
            )
        employee_no = _extract_employee_no(message)
        person_name = _extract_person_name(message)
        params: list[Any] = []
        where = "1=1"
        if employee_no:
            where = "TRIM(employee_no) = ? OR TRIM(user_id) = ?"
            params = [employee_no, employee_no]
        elif person_name:
            where = "TRIM(employee_name) = ?"
            params = [person_name]
        elif re.search(r"我|本人", message):
            person = _resolve_person_from_actor(conn, actor)
            if person is None:
                return _not_executed(
                    intent,
                    "已尝试查询，但当前登录账号没有绑定人员档案。请先在人员管理中绑定账号，或提供姓名/工号。",
                    reason="current_user_not_mapped",
                    source=source,
                    details={"actor": asdict(actor)},
                )
            where = "TRIM(employee_name) = ? AND (TRIM(employee_no) = ? OR TRIM(user_id) = ?)"
            params = [
                str(person["employee_name"] or ""),
                str(person["employee_no"] or ""),
                str(person["user_id"] or ""),
            ]
        rows = conn.execute(
            """
            SELECT employee_name, employee_no, department, position, user_id
            FROM attendance_employees WHERE """
            + where
            + """
            ORDER BY employee_name, id LIMIT 50
            """,
            params,
        ).fetchall()
        total = int(
            conn.execute(
                "SELECT COUNT(*) FROM attendance_employees WHERE " + where, params
            ).fetchone()[0]
            or 0
        )
    except sqlite3.Error as exc:
        return _not_executed(
            intent,
            "人员查询未执行：读取人员库失败。",
            reason=f"personnel_query_failed:{exc}",
            source=source,
            status="failed",
        )
    finally:
        conn.close()

    receipt = _new_receipt(
        intent,
        status="verified" if rows else "verified_empty",
        executed=True,
        verified=True,
        source=source,
        affected_rows=len(rows),
        details={"matched_total": total, "employee_no": employee_no, "employee_name": person_name},
    )
    if not rows:
        key = employee_no or person_name or "当前登录账号"
        return _payload(
            f"已查询真实人员库，但没有找到“{key}”对应的员工；本次没有猜测姓名或部门。",
            intent,
            receipt,
        )
    lines = ["已查询真实人员库："]
    for row in rows[:20]:
        lines.append(
            f"- {str(row['employee_name'] or '未命名')}｜工号 {str(row['employee_no'] or '未设置')}｜"
            f"{str(row['department'] or '未设置部门')}｜{str(row['position'] or '未设置岗位')}"
        )
    if total > len(rows):
        lines.append(f"另有 {total - len(rows)} 条匹配记录未展开。")
    lines.append(f"数据来源：{source}；查询回执：{receipt['receipt_id']}。")
    return _payload("\n".join(lines), intent, receipt)


def _parse_date_scope(message: str, *, now: date | None = None) -> tuple[str, str, str] | None:
    today = now or date.today()
    text = _compact(message)
    if "前天" in text:
        d = today - timedelta(days=2)
        return "day", d.isoformat(), d.isoformat()
    if "昨天" in text or "昨日" in text:
        d = today - timedelta(days=1)
        return "day", d.isoformat(), d.isoformat()
    if "明天" in text:
        d = today + timedelta(days=1)
        return "day", d.isoformat(), d.isoformat()
    if "后天" in text:
        d = today + timedelta(days=2)
        return "day", d.isoformat(), d.isoformat()
    if "今天" in text or "今日" in text:
        return "day", today.isoformat(), today.isoformat()

    full = re.search(r"(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?", text)
    if full:
        try:
            d = date(int(full.group(1)), int(full.group(2)), int(full.group(3)))
            return "day", d.isoformat(), d.isoformat()
        except ValueError:
            return None
    md = re.search(r"(?<!\d)(\d{1,2})月(\d{1,2})日", text)
    if md:
        try:
            d = date(today.year, int(md.group(1)), int(md.group(2)))
            return "day", d.isoformat(), d.isoformat()
        except ValueError:
            return None

    month = re.search(r"(20\d{2})[年./-](\d{1,2})月?", text)
    if month and not full:
        year, mon = int(month.group(1)), int(month.group(2))
        if 1 <= mon <= 12:
            start = date(year, mon, 1)
            next_month = date(year + (mon == 12), 1 if mon == 12 else mon + 1, 1)
            return "month", start.isoformat(), (next_month - timedelta(days=1)).isoformat()
    if any(token in text for token in ("本月", "这个月", "当月")):
        start = today.replace(day=1)
        next_month = date(
            today.year + (today.month == 12), 1 if today.month == 12 else today.month + 1, 1
        )
        return "month", start.isoformat(), (next_month - timedelta(days=1)).isoformat()
    return None


def _attendance_rows(
    message: str,
    *,
    actor: BusinessActorIdentity,
    require_scope: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
    scope = _parse_date_scope(message)
    if require_scope and scope is None:
        return [], {}, "missing_date_scope"

    conn = _connect_existing()
    if conn is None:
        return [], {}, "attendance_database_missing"
    try:
        if not _table_exists(conn, "attendance_daily_records"):
            return [], {}, "attendance_records_missing"

        clauses: list[str] = []
        params: list[Any] = []
        meta: dict[str, Any] = {}
        if scope:
            scope_kind, start, end = scope
            clauses.append("work_date BETWEEN ? AND ?")
            params.extend([start, end])
            meta.update({"scope": scope_kind, "date_start": start, "date_end": end})

        employee_no = _extract_employee_no(message)
        person_name = _extract_person_name(message)
        department = _extract_department(message)
        if employee_no:
            clauses.append("TRIM(employee_no) = ?")
            params.append(employee_no)
            meta["employee_no"] = employee_no
        elif person_name:
            clauses.append("TRIM(employee_name) = ?")
            params.append(person_name)
            meta["employee_name"] = person_name
        elif re.search(r"我|本人|我的", message):
            person = _resolve_person_from_actor(conn, actor)
            if person is None:
                return [], {**meta, "actor": asdict(actor)}, "current_user_not_mapped"
            person_name_value = str(person["employee_name"] or "")
            employee_no_value = str(person["employee_no"] or "")
            employee_user_id = str(person["user_id"] or "")
            clauses.append(
                "(TRIM(employee_name) = ? AND (TRIM(employee_no) = ? OR TRIM(user_id) = ?))"
            )
            params.extend([person_name_value, employee_no_value, employee_user_id])
            meta.update(
                {
                    "actor": asdict(actor),
                    "employee_name": person_name_value,
                    "employee_no": employee_no_value,
                }
            )
        elif department:
            clauses.append("TRIM(department) = ?")
            params.append(department)
            meta["department"] = department

        where = " AND ".join(clauses) if clauses else "1=1"
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT employee_name, employee_no, department, position, user_id,
                       work_date, shift_name, daily_times_json, raw_times_json,
                       all_times_json, leave_hours, absent_days, late_count_hint,
                       early_count_hint, missing_card_count, notes_json, source_file,
                       imported_at
                FROM attendance_daily_records
                WHERE """
                + where
                + """
                ORDER BY work_date, employee_name, id
                LIMIT 5000
                """,
                params,
            ).fetchall()
        ]
        return rows, meta, None
    except sqlite3.Error as exc:
        return [], {}, f"attendance_query_failed:{exc}"
    finally:
        conn.close()


def _json_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _attendance_error_payload(
    intent: BusinessChatIntent, error: str, meta: dict[str, Any]
) -> dict[str, Any]:
    source = f"{_DB_NAME}:attendance_daily_records"
    if error == "missing_date_scope":
        text = "考勤查询未执行：请明确要查询的日期或月份，例如“今天”“2026年7月14日”或“本月”。"
    elif error == "current_user_not_mapped":
        text = "已尝试查询，但当前登录账号没有绑定人员档案，无法判断“我”的考勤。请先在人员管理中绑定账号或提供姓名/工号。"
    elif error in {"attendance_database_missing", "attendance_records_missing"}:
        text = "考勤查询未执行：当前没有可核验的打卡明细。请先通过“考勤表转换/考勤数据源”导入原始考勤表。"
    else:
        text = "考勤查询未执行：读取真实考勤数据失败。"
    return _not_executed(
        intent,
        text,
        reason=error,
        source=source,
        status="unavailable" if "missing" in error or "not_mapped" in error else "failed",
        details=meta,
    )


def _handle_attendance_read(
    message: str, intent: BusinessChatIntent, *, actor: BusinessActorIdentity
) -> dict[str, Any]:
    rows, meta, error = _attendance_rows(message, actor=actor)
    if error:
        return _attendance_error_payload(intent, error, meta)

    source = f"{_DB_NAME}:attendance_daily_records"
    receipt = _new_receipt(
        intent,
        status="verified" if rows else "verified_empty",
        executed=True,
        verified=True,
        source=source,
        affected_rows=len(rows),
        details=meta,
    )
    scope_label = meta.get("date_start")
    if meta.get("date_end") and meta.get("date_end") != scope_label:
        scope_label = f"{scope_label} 至 {meta['date_end']}"
    if not rows:
        return _payload(
            f"已查询真实考勤库，但没有找到 {scope_label or '指定范围'} 的匹配记录，因此无法判断出勤或迟到；本次没有猜测。\n"
            f"数据来源：{source}；查询回执：{receipt['receipt_id']}。",
            intent,
            receipt,
        )

    wants_punch = bool(re.search(r"几点|时间|打卡|签到", message))
    wants_late = "迟到" in message
    wants_leave = bool(_LEAVE_RE.search(message))
    if wants_late:
        late_rows = [row for row in rows if float(row.get("late_count_hint") or 0) > 0]
        if len(rows) == 1:
            row = rows[0]
            late_count = float(row.get("late_count_hint") or 0)
            status = "有迟到标记" if late_count > 0 else "迟到标记为 0"
            times = _json_list(row.get("all_times_json"))
            time_text = f"；打卡时间：{', '.join(times)}" if times else "；没有打卡时间明细"
            text = (
                f"已查询 {row.get('work_date')} 的导入考勤记录：{row.get('employee_name') or '该员工'}{status}{time_text}。\n"
                "该结论只代表当前已导入的数据，不代表未同步的数据。"
            )
        else:
            text = f"已查询 {len(rows)} 条真实考勤记录，其中 {len(late_rows)} 条带迟到标记。"
            if late_rows:
                text += "\n" + "\n".join(
                    f"- {row.get('work_date')} {row.get('employee_name')}：迟到标记 {row.get('late_count_hint')}"
                    for row in late_rows[:20]
                )
    elif wants_punch:
        lines = []
        for row in rows[:30]:
            times = _json_list(row.get("all_times_json"))
            lines.append(
                f"- {row.get('work_date')} {row.get('employee_name')}："
                + (", ".join(times) if times else "无打卡时间")
            )
        text = f"已查询真实打卡明细（{len(rows)} 条）：\n" + "\n".join(lines)
    elif wants_leave:
        leave_rows = [row for row in rows if float(row.get("leave_hours") or 0) > 0]
        text = f"已查询 {len(rows)} 条真实考勤记录，其中 {len(leave_rows)} 条含请假时长。"
        if leave_rows:
            text += "\n" + "\n".join(
                f"- {row.get('work_date')} {row.get('employee_name')}：{row.get('leave_hours')} 小时"
                for row in leave_rows[:20]
            )
    else:
        punched = sum(1 for row in rows if _json_list(row.get("all_times_json")))
        absent = sum(1 for row in rows if float(row.get("absent_days") or 0) > 0)
        late = sum(1 for row in rows if float(row.get("late_count_hint") or 0) > 0)
        text = (
            f"已查询真实考勤记录 {len(rows)} 条：有打卡时间 {punched} 条，"
            f"迟到标记 {late} 条，缺勤标记 {absent} 条。"
        )
    text += f"\n数据来源：{source}；查询回执：{receipt['receipt_id']}。"
    return _payload(text, intent, receipt)
