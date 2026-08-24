"""Verified personnel reads for protected natural-language chat actions."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict
from typing import Any

from app.application.chat_business_safety_core import (
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
from app.utils.operational_errors import RECOVERABLE_ERRORS


def _handle_legacy_personnel_read(
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
        # ``where`` is selected only from the constant clauses above; all actor
        # and message-derived values remain bound parameters.
        rows = conn.execute(
            "SELECT employee_name, employee_no, department, position, user_id "
            "FROM attendance_employees WHERE " + where + " ORDER BY employee_name, id LIMIT 50",
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


def _handle_personnel_read(
    message: str, intent: BusinessChatIntent, *, actor: BusinessActorIdentity
) -> dict[str, Any]:
    """Read canonical ERP personnel; use the side DB only before ERP migration."""

    try:
        from sqlalchemy import or_

        from app.application.erp_attendance_app_service import (
            erp_attendance_schema_available,
            find_employee,
        )
        from app.db import HostSessionLocal
        from app.db.models.hr_attendance import ErpEmployee

        db = HostSessionLocal()
        try:
            if not erp_attendance_schema_available(db):
                return _handle_legacy_personnel_read(message, intent, actor=actor)
            employee_no = _extract_employee_no(message)
            person_name = _extract_person_name(message)
            query = db.query(ErpEmployee).filter(ErpEmployee.is_active.is_(True))
            if employee_no:
                query = query.filter(
                    or_(
                        ErpEmployee.employee_no == employee_no,
                        ErpEmployee.external_user_id == employee_no,
                    )
                )
            elif person_name:
                query = query.filter(ErpEmployee.employee_name == person_name)
            elif re.search(r"我|本人", message):
                person = find_employee(
                    db,
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
                if person is None:
                    if db.query(ErpEmployee.id).first() is None:
                        return _handle_legacy_personnel_read(message, intent, actor=actor)
                    return _not_executed(
                        intent,
                        "已尝试查询，但当前登录账号没有绑定 ERP 人员档案。请先在人员管理中绑定账号，或提供姓名/工号。",
                        reason="current_user_not_mapped",
                        source="erp:erp_employees",
                        details={"actor": asdict(actor)},
                    )
                query = query.filter(ErpEmployee.id == person.id)
            total = query.count()
            rows = query.order_by(ErpEmployee.employee_name, ErpEmployee.id).limit(50).all()
            if not rows and db.query(ErpEmployee.id).first() is None:
                return _handle_legacy_personnel_read(message, intent, actor=actor)
        finally:
            db.close()
    except RECOVERABLE_ERRORS as exc:
        return _not_executed(
            intent,
            "人员查询未执行：读取 ERP 人员档案失败。",
            reason=f"personnel_query_failed:{exc}",
            source="erp:erp_employees",
            status="failed",
        )

    receipt = _new_receipt(
        intent,
        status="verified" if rows else "verified_empty",
        executed=True,
        verified=True,
        source="erp:erp_employees",
        affected_rows=len(rows),
        details={"matched_total": total, "employee_no": employee_no, "employee_name": person_name},
    )
    if not rows:
        key = employee_no or person_name or "当前登录账号"
        return _payload(
            f"已查询 ERP 人员档案，但没有找到“{key}”对应的员工；本次没有猜测姓名或部门。",
            intent,
            receipt,
        )
    lines = ["已查询 ERP 人员档案："]
    for row in rows[:20]:
        lines.append(
            f"- {row.employee_name or '未命名'}｜工号 {row.employee_no or '未设置'}｜"
            f"{row.department or '未设置部门'}｜{row.position or '未设置岗位'}"
        )
    if total > len(rows):
        lines.append(f"另有 {total - len(rows)} 条匹配记录未展开。")
    lines.append(f"数据来源：erp:erp_employees；查询回执：{receipt['receipt_id']}。")
    return _payload("\n".join(lines), intent, receipt)
