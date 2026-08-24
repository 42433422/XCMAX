"""Tenant-scoped ERP personnel and department management for AI workflows.

This module is the host-owned write boundary for personnel master data.  The
chat planner may describe a delete, but the host always translates it to a
recoverable deactivation so attendance history and references remain intact.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import HostSessionLocal
from app.db.models.hr_attendance import (
    AttendanceDailyRecord,
    AttendanceLeaveRecord,
    ErpDepartment,
    ErpEmployee,
)
from app.infrastructure.tenant_scope import current_tenant_id, tenant_id_for_write
from app.utils.operational_errors import RECOVERABLE_ERRORS

_EMPLOYEE_ALIASES = frozenset({"employee", "employees", "personnel", "人员", "员工"})
_DEPARTMENT_ALIASES = frozenset({"department", "departments", "dept", "部门"})
_BOTH_ALIASES = frozenset(
    {
        "all",
        "both",
        "employees_and_departments",
        "personnel_and_departments",
        "人员和部门",
        "部门和人员",
    }
)
_FORBIDDEN_KEYS = frozenset({"tenant_id", "sql", "raw_sql", "query_sql"})
_EMPLOYEE_FIELDS = frozenset(
    {
        "employee_name",
        "department_id",
        "department",
        "main_department",
        "attendance_group",
        "employee_no",
        "position",
        "external_user_id",
        "account_user_id",
        "is_active",
    }
)
_DEPARTMENT_FIELDS = frozenset({"name", "parent_name", "attendance_group", "is_active"})
_WRITE_ACTIONS = frozenset({"create", "update", "deactivate", "bulk_deactivate"})


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _entity(value: Any) -> str:
    normalized = _clean(value).lower()
    if normalized in _EMPLOYEE_ALIASES:
        return "employees"
    if normalized in _DEPARTMENT_ALIASES:
        return "departments"
    if normalized in _BOTH_ALIASES:
        return "employees_and_departments"
    return ""


def _tenant_for_read() -> int:
    tenant_id = current_tenant_id()
    if tenant_id is None:
        raise RuntimeError("缺少有效租户上下文，拒绝读取 ERP 人员数据")
    return int(tenant_id)


def _reject_unsafe_payload(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).strip().lower() in _FORBIDDEN_KEYS:
                raise ValueError(f"不允许在工具参数中指定 {key}")
            _reject_unsafe_payload(item)
    elif isinstance(value, list):
        for item in value:
            _reject_unsafe_payload(item)


def _employee_identity_key(
    *, employee_name: str, department: str = "", employee_no: str = "", external_user_id: str = ""
) -> str:
    from app.application.erp_attendance_app_service import employee_identity_key

    return employee_identity_key(
        employee_name=employee_name,
        department=department,
        employee_no=employee_no,
        external_user_id=external_user_id,
    )


def _employee_query(
    db: Session,
    *,
    tenant_id: int,
    selector: dict[str, Any] | None = None,
    active_only: bool = False,
):
    query = db.query(ErpEmployee).filter(ErpEmployee.tenant_id == tenant_id)
    if active_only:
        query = query.filter(ErpEmployee.is_active.is_(True))
    selector = dict(selector or {})
    if selector.get("id") is not None:
        query = query.filter(ErpEmployee.id == int(selector["id"]))
    if selector.get("ids"):
        ids = [int(value) for value in selector["ids"]]
        query = query.filter(ErpEmployee.id.in_(ids))
    if _clean(selector.get("employee_name") or selector.get("name")):
        query = query.filter(
            ErpEmployee.employee_name
            == _clean(selector.get("employee_name") or selector.get("name"))
        )
    if _clean(selector.get("employee_no")):
        query = query.filter(ErpEmployee.employee_no == _clean(selector["employee_no"]))
    if _clean(selector.get("external_user_id")):
        query = query.filter(ErpEmployee.external_user_id == _clean(selector["external_user_id"]))
    if _clean(selector.get("department")):
        query = query.filter(ErpEmployee.department == _clean(selector["department"]))
    return query


def _department_query(
    db: Session,
    *,
    tenant_id: int,
    selector: dict[str, Any] | None = None,
    active_only: bool = False,
):
    query = db.query(ErpDepartment).filter(ErpDepartment.tenant_id == tenant_id)
    if active_only:
        query = query.filter(ErpDepartment.is_active.is_(True))
    selector = dict(selector or {})
    if selector.get("id") is not None:
        query = query.filter(ErpDepartment.id == int(selector["id"]))
    if selector.get("ids"):
        ids = [int(value) for value in selector["ids"]]
        query = query.filter(ErpDepartment.id.in_(ids))
    if _clean(selector.get("name") or selector.get("department")):
        query = query.filter(
            ErpDepartment.name == _clean(selector.get("name") or selector.get("department"))
        )
    if _clean(selector.get("parent_name")):
        query = query.filter(ErpDepartment.parent_name == _clean(selector["parent_name"]))
    return query


def _history_counts(
    db: Session,
    *,
    tenant_id: int,
    employee_ids: list[int],
    department_ids: list[int],
) -> dict[str, int]:
    daily_query = db.query(AttendanceDailyRecord.id).filter(
        AttendanceDailyRecord.tenant_id == tenant_id
    )
    if employee_ids and department_ids:
        daily_query = daily_query.filter(
            or_(
                AttendanceDailyRecord.employee_id.in_(employee_ids),
                AttendanceDailyRecord.department_id.in_(department_ids),
            )
        )
    elif employee_ids:
        daily_query = daily_query.filter(AttendanceDailyRecord.employee_id.in_(employee_ids))
    elif department_ids:
        daily_query = daily_query.filter(AttendanceDailyRecord.department_id.in_(department_ids))
    else:
        return {"attendance_records": 0, "leave_records": 0}
    leave_count = 0
    if employee_ids:
        leave_count = (
            db.query(AttendanceLeaveRecord.id)
            .filter(
                AttendanceLeaveRecord.tenant_id == tenant_id,
                AttendanceLeaveRecord.employee_id.in_(employee_ids),
            )
            .count()
        )
    return {
        "attendance_records": int(daily_query.count()),
        "leave_records": int(leave_count),
    }


def preview_erp_hr_change(params: dict[str, Any], *, db: Session | None = None) -> dict[str, Any]:
    """Return an exact, tenant-scoped impact preview without modifying data."""

    _reject_unsafe_payload(params)
    owns_session = db is None
    session = db or HostSessionLocal()
    try:
        tenant_id = _tenant_for_read()
        scope = _entity(params.get("scope") or params.get("entity"))
        if not scope:
            scope = "employees_and_departments"
        selector = params.get("selector")
        selector = dict(selector) if isinstance(selector, dict) else {}
        all_records = bool(params.get("all"))
        if not all_records and not selector:
            raise ValueError("预览停用操作需要 selector；批量全部操作必须显式传 all=true")

        employees: list[ErpEmployee] = []
        departments: list[ErpDepartment] = []
        if scope in {"employees", "employees_and_departments"}:
            employees = _employee_query(
                session,
                tenant_id=tenant_id,
                selector={} if all_records else selector,
                active_only=True,
            ).all()
        if scope in {"departments", "employees_and_departments"}:
            departments = _department_query(
                session,
                tenant_id=tenant_id,
                selector={} if all_records else selector,
                active_only=True,
            ).all()
        employee_ids = [int(row.id) for row in employees]
        department_ids = [int(row.id) for row in departments]
        history = _history_counts(
            session,
            tenant_id=tenant_id,
            employee_ids=employee_ids,
            department_ids=department_ids,
        )
        return {
            "success": True,
            "message": "ERP 人员变更影响预览已生成",
            "scope": scope,
            "mode": "soft_deactivate",
            "active_employees": len(employee_ids),
            "active_departments": len(department_ids),
            "employee_ids": employee_ids[:100],
            "department_ids": department_ids[:100],
            "history_preserved": history,
            "physical_delete": False,
        }
    finally:
        if owns_session:
            session.close()


def _list_records(db: Session, params: dict[str, Any]) -> dict[str, Any]:
    tenant_id = _tenant_for_read()
    entity = _entity(params.get("entity")) or "employees"
    if entity == "employees_and_departments":
        raise ValueError("list 每次只能查询 employees 或 departments")
    search = _clean(params.get("search") or params.get("keyword"))
    include_inactive = bool(params.get("include_inactive", False))
    limit = min(100, max(1, int(params.get("limit") or 50)))
    if entity == "employees":
        query = _employee_query(db, tenant_id=tenant_id, active_only=not include_inactive)
        if search:
            like = f"%{search}%"
            query = query.filter(
                or_(
                    ErpEmployee.employee_name.ilike(like),
                    ErpEmployee.employee_no.ilike(like),
                    ErpEmployee.department.ilike(like),
                    ErpEmployee.position.ilike(like),
                )
            )
        total = query.count()
        rows = query.order_by(ErpEmployee.id).limit(limit).all()
        items = [
            {
                "id": row.id,
                "employee_name": row.employee_name,
                "employee_no": row.employee_no,
                "department_id": row.department_id,
                "department": row.department,
                "main_department": row.main_department,
                "attendance_group": row.attendance_group,
                "position": row.position,
                "external_user_id": row.external_user_id,
                "account_user_id": row.account_user_id,
                "is_active": row.is_active,
            }
            for row in rows
        ]
    else:
        query = _department_query(db, tenant_id=tenant_id, active_only=not include_inactive)
        if search:
            like = f"%{search}%"
            query = query.filter(
                or_(
                    ErpDepartment.name.ilike(like),
                    ErpDepartment.parent_name.ilike(like),
                    ErpDepartment.attendance_group.ilike(like),
                )
            )
        total = query.count()
        rows = query.order_by(ErpDepartment.id).limit(limit).all()
        items = [
            {
                "id": row.id,
                "name": row.name,
                "parent_name": row.parent_name,
                "attendance_group": row.attendance_group,
                "is_active": row.is_active,
            }
            for row in rows
        ]
    return {
        "success": True,
        "message": f"已查询 ERP {entity}",
        "entity": entity,
        "data": items,
        "total": int(total),
        "source": f"erp:erp_{entity}",
    }


def _resolve_department(
    db: Session, tenant_id: int, payload: dict[str, Any]
) -> ErpDepartment | None:
    department_id = payload.get("department_id")
    department_name = _clean(payload.get("department"))
    if department_id is not None:
        row = _department_query(
            db, tenant_id=tenant_id, selector={"id": int(department_id)}
        ).first()
        if row is None:
            raise ValueError("指定部门不存在于当前租户")
        return row
    if department_name:
        return _department_query(
            db, tenant_id=tenant_id, selector={"name": department_name}
        ).first()
    return None


def _create_record(db: Session, params: dict[str, Any]) -> dict[str, Any]:
    tenant_id = tenant_id_for_write()
    entity = _entity(params.get("entity"))
    payload = params.get("payload")
    if entity not in {"employees", "departments"} or not isinstance(payload, dict):
        raise ValueError("create 需要 entity=employees/departments 和 dict payload")
    _reject_unsafe_payload(payload)
    if entity == "departments":
        name = _clean(payload.get("name") or payload.get("department"))
        if not name:
            raise ValueError("创建部门缺少 name")
        parent_name = _clean(payload.get("parent_name") or payload.get("main_department"))
        existed = _department_query(
            db,
            tenant_id=tenant_id,
            selector={"name": name, "parent_name": parent_name},
        ).first()
        if existed is not None:
            raise ValueError("当前租户已存在同名同上级部门")
        row = ErpDepartment(
            tenant_id=tenant_id,
            name=name,
            parent_name=parent_name,
            attendance_group=_clean(payload.get("attendance_group")),
            source_system="ai_host_management",
            source_key=f"ai:{uuid.uuid4().hex}",
            is_active=True,
        )
    else:
        employee_name = _clean(payload.get("employee_name") or payload.get("name"))
        if not employee_name:
            raise ValueError("创建员工缺少 employee_name")
        department = _resolve_department(db, tenant_id, payload)
        department_name = (
            department.name if department is not None else _clean(payload.get("department"))
        )
        identity_key = _employee_identity_key(
            employee_name=employee_name,
            department=department_name,
            employee_no=_clean(payload.get("employee_no")),
            external_user_id=_clean(payload.get("external_user_id")),
        )
        existed = (
            _employee_query(db, tenant_id=tenant_id)
            .filter(ErpEmployee.identity_key == identity_key)
            .first()
        )
        if existed is not None:
            raise ValueError("当前租户已存在相同人员身份记录")
        row = ErpEmployee(
            tenant_id=tenant_id,
            identity_key=identity_key,
            employee_name=employee_name,
            department_id=department.id if department is not None else None,
            department=department_name,
            main_department=(
                department.parent_name
                if department is not None
                else _clean(payload.get("main_department"))
            ),
            attendance_group=(
                _clean(payload.get("attendance_group"))
                or (department.attendance_group if department is not None else "")
            ),
            employee_no=_clean(payload.get("employee_no")),
            position=_clean(payload.get("position")),
            external_user_id=_clean(payload.get("external_user_id")),
            account_user_id=(
                int(payload["account_user_id"])
                if payload.get("account_user_id") is not None
                else None
            ),
            source_system="ai_host_management",
            source_key=f"ai:{uuid.uuid4().hex}",
            is_active=True,
        )
    db.add(row)
    db.flush()
    return {
        "success": True,
        "message": f"ERP {entity} 已创建",
        "entity": entity,
        "affected_rows": 1,
        "record_id": int(row.id),
    }


def _single_target(db: Session, entity: str, selector: dict[str, Any], tenant_id: int):
    if not selector:
        raise ValueError("操作缺少唯一 selector")
    query = (
        _employee_query(db, tenant_id=tenant_id, selector=selector)
        if entity == "employees"
        else _department_query(db, tenant_id=tenant_id, selector=selector)
    )
    rows = query.limit(2).all()
    if not rows:
        raise ValueError("当前租户未找到操作目标")
    if len(rows) != 1:
        raise ValueError("操作目标不唯一，请提供 ID、工号或完整名称")
    return rows[0]


def _update_record(db: Session, params: dict[str, Any]) -> dict[str, Any]:
    tenant_id = tenant_id_for_write()
    entity = _entity(params.get("entity"))
    selector = params.get("selector")
    changes = params.get("changes") or params.get("fields")
    if entity not in {"employees", "departments"}:
        raise ValueError("update 需要 entity=employees/departments")
    if not isinstance(selector, dict) or not isinstance(changes, dict) or not changes:
        raise ValueError("update 需要唯一 selector 和非空 changes")
    _reject_unsafe_payload({"selector": selector, "changes": changes})
    allowed = _EMPLOYEE_FIELDS if entity == "employees" else _DEPARTMENT_FIELDS
    invalid = sorted(set(changes) - allowed)
    if invalid:
        raise ValueError(f"不允许更新字段：{', '.join(invalid)}")
    row = _single_target(db, entity, selector, tenant_id)
    before = {key: getattr(row, key) for key in changes}
    if entity == "employees" and ("department" in changes or "department_id" in changes):
        department = _resolve_department(db, tenant_id, changes)
        if department is not None:
            changes = {
                **changes,
                "department_id": department.id,
                "department": department.name,
                "main_department": department.parent_name,
            }
    old_department_name = row.name if entity == "departments" else ""
    for key, value in changes.items():
        setattr(row, key, _clean(value) if isinstance(value, str) else value)
    if entity == "employees":
        row.identity_key = _employee_identity_key(
            employee_name=row.employee_name,
            department=row.department,
            employee_no=row.employee_no,
            external_user_id=row.external_user_id,
        )
    elif "name" in changes and row.name != old_department_name:
        db.query(ErpEmployee).filter(
            ErpEmployee.tenant_id == tenant_id,
            ErpEmployee.department_id == row.id,
        ).update({ErpEmployee.department: row.name}, synchronize_session=False)
    db.flush()
    return {
        "success": True,
        "message": f"ERP {entity} 已更新",
        "entity": entity,
        "affected_rows": 1,
        "record_id": int(row.id),
        "before": before,
    }


def _deactivate(db: Session, params: dict[str, Any]) -> dict[str, Any]:
    tenant_id = tenant_id_for_write()
    entity = _entity(params.get("entity"))
    selector = params.get("selector")
    if entity not in {"employees", "departments"} or not isinstance(selector, dict):
        raise ValueError("deactivate 需要 entity 和唯一 selector")
    _reject_unsafe_payload(selector)
    row = _single_target(db, entity, selector, tenant_id)
    if not row.is_active:
        return {
            "success": True,
            "message": "目标此前已停用，本次未重复修改",
            "entity": entity,
            "affected_rows": 0,
            "record_id": int(row.id),
        }
    employee_count = 0
    if entity == "departments":
        active_employees = _employee_query(
            db,
            tenant_id=tenant_id,
            selector={"department": row.name},
            active_only=True,
        )
        employee_count = active_employees.count()
        if employee_count and not bool(params.get("cascade")):
            raise ValueError(f"该部门仍有 {employee_count} 名在职员工；请明确 cascade=true")
        if employee_count:
            active_employees.update({ErpEmployee.is_active: False}, synchronize_session=False)
    row.is_active = False
    db.flush()
    return {
        "success": True,
        "message": f"ERP {entity} 已软停用；历史记录保留",
        "entity": entity,
        "affected_rows": 1 + employee_count,
        "record_id": int(row.id),
        "physical_delete": False,
        "history_preserved": True,
    }


def _bulk_deactivate(db: Session, params: dict[str, Any]) -> dict[str, Any]:
    if params.get("all") is not True:
        raise ValueError("批量停用全部记录必须显式传 all=true")
    preview = preview_erp_hr_change(params, db=db)
    expected_employees = params.get("expected_active_employees")
    expected_departments = params.get("expected_active_departments")
    if expected_employees is not None and int(expected_employees) != int(
        preview["active_employees"]
    ):
        raise ValueError("审批期间员工数量已变化，拒绝执行；请重新生成影响预览")
    if expected_departments is not None and int(expected_departments) != int(
        preview["active_departments"]
    ):
        raise ValueError("审批期间部门数量已变化，拒绝执行；请重新生成影响预览")
    tenant_id = tenant_id_for_write()
    employee_count = 0
    department_count = 0
    if preview["scope"] in {"employees", "employees_and_departments"}:
        employee_count = int(
            _employee_query(db, tenant_id=tenant_id, active_only=True).update(
                {ErpEmployee.is_active: False}, synchronize_session=False
            )
            or 0
        )
    if preview["scope"] in {"departments", "employees_and_departments"}:
        if preview["scope"] == "departments":
            remaining = _employee_query(db, tenant_id=tenant_id, active_only=True).count()
            if remaining:
                raise ValueError(
                    f"仍有 {remaining} 名在职员工，不能单独停用全部部门；请同时选择人员"
                )
        department_count = int(
            _department_query(db, tenant_id=tenant_id, active_only=True).update(
                {ErpDepartment.is_active: False}, synchronize_session=False
            )
            or 0
        )
    return {
        "success": True,
        "message": (
            f"已软停用 {employee_count} 名员工、{department_count} 个部门；考勤与请假历史完整保留"
        ),
        "entity": preview["scope"],
        "affected_rows": employee_count + department_count,
        "deactivated_employees": employee_count,
        "deactivated_departments": department_count,
        "physical_delete": False,
        "history_preserved": preview["history_preserved"],
    }


def execute_erp_hr_management(action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute one registered ERP HR action with an atomic transaction receipt."""

    normalized_action = _clean(action).lower()
    payload = dict(params or {})
    receipt_id = f"erp-hr-{uuid.uuid4().hex}"
    if normalized_action not in {"list", "preview", *_WRITE_ACTIONS}:
        return {
            "success": False,
            "message": f"未知 ERP HR 动作：{normalized_action}",
            "error_code": "erp_hr_unknown_action",
            "receipt_id": receipt_id,
        }
    try:
        _reject_unsafe_payload(payload)
        if normalized_action == "preview":
            result = preview_erp_hr_change(payload)
        elif normalized_action == "list":
            db = HostSessionLocal()
            try:
                result = _list_records(db, payload)
            finally:
                db.close()
        else:
            db = HostSessionLocal()
            try:
                with db.begin():
                    handlers = {
                        "create": _create_record,
                        "update": _update_record,
                        "deactivate": _deactivate,
                        "bulk_deactivate": _bulk_deactivate,
                    }
                    result = handlers[normalized_action](db, payload)
            finally:
                db.close()
        result = dict(result)
        result.setdefault("success", True)
        result["receipt_id"] = receipt_id
        result["action"] = normalized_action
        result["transaction"] = "committed" if normalized_action in _WRITE_ACTIONS else "read_only"
        result["executed_at"] = datetime.now(UTC).isoformat()
        return result
    except (*RECOVERABLE_ERRORS, SQLAlchemyError) as exc:
        return {
            "success": False,
            "message": str(exc).strip() or "ERP 人员管理执行失败",
            "error_code": "erp_hr_management_failed",
            "receipt_id": receipt_id,
            "action": normalized_action,
            "transaction": "rolled_back" if normalized_action in _WRITE_ACTIONS else "read_only",
            "rolled_back": normalized_action in _WRITE_ACTIONS,
            "executed_at": datetime.now(UTC).isoformat(),
        }


def _extract_named_value(message: str, labels: tuple[str, ...]) -> str:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:{label_pattern})\s*[:：是为]?\s*[「“\"']?([^，,。；;\n]+?)[」”\"']?"
        rf"(?=\s+(?:姓名|员工|人员|部门|上级部门|工号|岗位|职位|考勤组|ID|id)\s*[:：是为]?|[，,。；;]|$)",
        message,
        flags=re.I,
    )
    return _clean(match.group(1)) if match else ""


def _selector_from_message(message: str, entity: str) -> dict[str, Any]:
    id_match = re.search(r"(?:人员|员工|部门)?\s*(?:ID|id|编号)\s*[:：#]?\s*(\d+)", message)
    if id_match:
        return {"id": int(id_match.group(1))}
    if entity == "employees":
        employee_no = _extract_named_value(message, ("工号",))
        if employee_no:
            return {"employee_no": employee_no}
        name = _extract_named_value(message, ("员工姓名", "人员姓名", "姓名", "员工", "人员"))
        if name:
            return {"employee_name": name}
    else:
        name = _extract_named_value(message, ("部门名称", "部门"))
        if name:
            return {"name": name}
    quoted = re.search(r"[「“\"']([^」”\"']+)[」”\"']", message)
    if quoted:
        return {"employee_name" if entity == "employees" else "name": _clean(quoted.group(1))}
    return {}


def build_erp_hr_workflow_node(message: str):
    """Build the deterministic host-management node for an HR chat request."""

    from app.application.workflow.types import WorkflowNode

    text = _clean(message)
    lower = text.lower()
    has_employee = any(token in text for token in ("员工", "人员", "人事"))
    has_department = "部门" in text
    entity = (
        "employees_and_departments"
        if has_employee and has_department
        else "departments"
        if has_department
        else "employees"
    )
    delete = any(token in text for token in ("删除", "移除", "清空", "停用", "归档")) or any(
        token in lower for token in ("delete", "remove", "deactivate", "archive")
    )
    all_records = any(token in text for token in ("所有", "全部", "全体", "一键", "清空"))
    if delete:
        if all_records:
            preview_params = {"scope": entity, "all": True}
            try:
                preview = preview_erp_hr_change(preview_params)
            except (*RECOVERABLE_ERRORS, SQLAlchemyError):
                preview = {
                    "active_employees": 0,
                    "active_departments": 0,
                    "history_preserved": {"attendance_records": 0, "leave_records": 0},
                }
            params = {
                **preview_params,
                "expected_active_employees": int(preview.get("active_employees") or 0),
                "expected_active_departments": int(preview.get("active_departments") or 0),
                "impact_preview": preview,
            }
            return WorkflowNode(
                node_id="erp_hr_bulk_deactivate",
                tool_id="erp_hr",
                action="bulk_deactivate",
                params=params,
                risk="high",
                idempotent=True,
                description=(
                    f"软停用 {params['expected_active_employees']} 名员工和 "
                    f"{params['expected_active_departments']} 个部门，保留历史"
                ),
            )
        single_entity = "departments" if entity == "departments" else "employees"
        selector = _selector_from_message(text, single_entity)
        return WorkflowNode(
            node_id=f"erp_hr_deactivate_{single_entity}",
            tool_id="erp_hr",
            action="deactivate",
            params={"entity": single_entity, "selector": selector, "cascade": False},
            risk="high",
            idempotent=True,
            description=f"软停用 ERP {single_entity}，保留历史",
        )
    if any(token in text for token in ("新增", "新建", "创建", "添加")) or "create" in lower:
        single_entity = "departments" if entity == "departments" else "employees"
        payload: dict[str, Any] = {}
        if single_entity == "departments":
            payload["name"] = _extract_named_value(text, ("部门名称", "部门"))
            payload["parent_name"] = _extract_named_value(text, ("上级部门", "主部门"))
            payload["attendance_group"] = _extract_named_value(text, ("考勤组",))
        else:
            payload["employee_name"] = _extract_named_value(
                text, ("员工姓名", "人员姓名", "姓名", "员工", "人员")
            )
            payload["department"] = _extract_named_value(text, ("部门",))
            payload["employee_no"] = _extract_named_value(text, ("工号",))
            payload["position"] = _extract_named_value(text, ("岗位", "职位"))
        payload = {key: value for key, value in payload.items() if value not in (None, "")}
        return WorkflowNode(
            node_id=f"erp_hr_create_{single_entity}",
            tool_id="erp_hr",
            action="create",
            params={"entity": single_entity, "payload": payload},
            risk="medium",
            idempotent=False,
            description=f"创建 ERP {single_entity}",
        )
    if (
        any(token in text for token in ("修改", "更新", "改为", "改成", "调到"))
        or "update" in lower
    ):
        single_entity = "departments" if entity == "departments" else "employees"
        selector = _selector_from_message(text, single_entity)
        changes: dict[str, Any] = {}
        if single_entity == "employees":
            department = _extract_named_value(text, ("调到", "部门", "改到"))
            position = _extract_named_value(text, ("岗位", "职位"))
            if department:
                changes["department"] = department
            if position:
                changes["position"] = position
        else:
            new_name = _extract_named_value(text, ("改为", "改成", "新名称"))
            if new_name:
                changes["name"] = new_name
        return WorkflowNode(
            node_id=f"erp_hr_update_{single_entity}",
            tool_id="erp_hr",
            action="update",
            params={"entity": single_entity, "selector": selector, "changes": changes},
            risk="medium",
            idempotent=False,
            description=f"更新 ERP {single_entity}",
        )
    list_entity = "departments" if entity == "departments" else "employees"
    return WorkflowNode(
        node_id=f"erp_hr_list_{list_entity}",
        tool_id="erp_hr",
        action="list",
        params={"entity": list_entity, "search": "", "limit": 50},
        risk="low",
        idempotent=True,
        description=f"查询 ERP {list_entity}",
    )


__all__ = [
    "build_erp_hr_workflow_node",
    "execute_erp_hr_management",
    "preview_erp_hr_change",
]
