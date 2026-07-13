"""Verified personnel read operations for business chat."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict
from typing import Any

from app.application.chat_business_safety import (
    _DB_NAME,
    BusinessActorIdentity,
    BusinessChatIntent,
    _connect_existing,
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
        query_kind = "all"
        if employee_no:
            query_kind = "employee_no"
            params = [employee_no, employee_no]
        elif person_name:
            query_kind = "person_name"
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
            query_kind = "current_user"
            params = [
                str(person["employee_name"] or ""),
                str(person["employee_no"] or ""),
                str(person["user_id"] or ""),
            ]
        row_queries = {
            "all": """SELECT employee_name, employee_no, department, position, user_id
                FROM attendance_employees ORDER BY employee_name, id LIMIT 50""",
            "employee_no": """SELECT employee_name, employee_no, department, position, user_id
                FROM attendance_employees
                WHERE TRIM(employee_no) = ? OR TRIM(user_id) = ?
                ORDER BY employee_name, id LIMIT 50""",
            "person_name": """SELECT employee_name, employee_no, department, position, user_id
                FROM attendance_employees WHERE TRIM(employee_name) = ?
                ORDER BY employee_name, id LIMIT 50""",
            "current_user": """SELECT employee_name, employee_no, department, position, user_id
                FROM attendance_employees
                WHERE TRIM(employee_name) = ?
                  AND (TRIM(employee_no) = ? OR TRIM(user_id) = ?)
                ORDER BY employee_name, id LIMIT 50""",
        }
        count_queries = {
            "all": "SELECT COUNT(*) FROM attendance_employees",
            "employee_no": """SELECT COUNT(*) FROM attendance_employees
                WHERE TRIM(employee_no) = ? OR TRIM(user_id) = ?""",
            "person_name": """SELECT COUNT(*) FROM attendance_employees
                WHERE TRIM(employee_name) = ?""",
            "current_user": """SELECT COUNT(*) FROM attendance_employees
                WHERE TRIM(employee_name) = ?
                  AND (TRIM(employee_no) = ? OR TRIM(user_id) = ?)""",
        }
        rows = conn.execute(row_queries[query_kind], params).fetchall()
        total = int(conn.execute(count_queries[query_kind], params).fetchone()[0] or 0)
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
