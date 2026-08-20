"""员工联系人 SSOT 派生（三端统一 contacts 契约）。

从 :mod:`app.mod_sdk.employee_ssot` 拆出，避免 ``employee_ssot.py`` 超过架构 fitness 上限。
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from app.mod_sdk.host_profile import resolve_fhd_config_dir
from app.utils.operational_errors import RECOVERABLE_ERRORS

SUPER_EMPLOYEE_CONTACT_ORDER: tuple[str, ...] = (
    "codex-super-employee",
    "cursor-super-employee",
    "claude-super-employee",
    "trae-super-employee",
)


@lru_cache(maxsize=1)
def load_employee_manifest_meta() -> dict[str, dict[str, str]]:
    """从 ``mods/_employees/*/manifest.json`` 派生 ``{emp_id: {name, description}}``。"""
    out: dict[str, dict[str, str]] = {}
    cfg_dir = resolve_fhd_config_dir()
    if cfg_dir is None:
        return out
    employees_dir = cfg_dir.parent / "mods" / "_employees"
    if not employees_dir.is_dir():
        return out
    for manifest_path in employees_dir.glob("*/manifest.json"):
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            emp_id = str(data.get("id") or "").strip()
            if not emp_id:
                continue
            raw_employee_meta = data.get("employee")
            employee_meta: dict[str, Any] = (
                dict(raw_employee_meta) if isinstance(raw_employee_meta, dict) else {}
            )
            name = str(data.get("name") or employee_meta.get("label") or "").strip()
            desc = str(data.get("description") or "").strip()
            row: dict[str, str] = {}
            if name:
                row["name"] = name
            if desc:
                row["description"] = desc
            if row:
                out[emp_id] = row
        except RECOVERABLE_ERRORS:
            continue
    return out


def employee_display_name(emp_id: str) -> str:
    meta = load_employee_manifest_meta().get(str(emp_id or "").strip()) or {}
    return str(meta.get("name") or emp_id).strip() or emp_id


def employee_description(emp_id: str) -> str:
    meta = load_employee_manifest_meta().get(str(emp_id or "").strip()) or {}
    return str(meta.get("description") or "").strip()


def _employee_contact_record(
    employee_id: str,
    *,
    display_name: str,
    department: str,
    source: str,
    installed: bool,
    pinned: bool = False,
    surface_name: str | None = None,
    description: str = "",
    capabilities: list[str] | None = None,
    contact_route: str | None = None,
    mobile_contact_route: str | None = None,
    last_task_status: str = "idle",
) -> dict[str, Any]:
    eid = str(employee_id or "").strip()
    runnable = bool(installed and source in {"installed", "builtin", "codex"})
    avatar_key = eid.split("-")[0][:24] if eid else "employee"
    return {
        "employee_id": eid,
        "display_name": display_name,
        "surface_name": surface_name or display_name,
        "department": department,
        "source": source,
        "installed": installed,
        "runnable": runnable,
        "online": runnable,
        "pinned": pinned,
        "avatar_key": avatar_key,
        "contact_route": contact_route or f"/api/admin/employees/chat/{eid}",
        "mobile_contact_route": mobile_contact_route or f"/api/mobile/v1/employees/{eid}/messages",
        "capabilities": list(capabilities or []),
        "last_task_status": last_task_status,
        "description": description,
    }


def _super_employee_contacts() -> list[dict[str, Any]]:
    from app.mod_sdk import assistant_ssot

    registry = assistant_ssot.super_employees()
    out: list[dict[str, Any]] = []
    for emp_id in SUPER_EMPLOYEE_CONTACT_ORDER:
        meta = registry.get(emp_id)
        if not isinstance(meta, dict):
            continue
        if assistant_ssot.is_factory_employee(emp_id):
            continue
        display = str(meta.get("display_name") or emp_id).strip()
        summary = str(
            meta.get("summary") or f"{meta.get('display_tool') or ''} 超级员工 · 多设备派工".strip()
        ).strip()
        source = "codex" if emp_id == "codex-super-employee" else "builtin"
        out.append(
            _employee_contact_record(
                emp_id,
                display_name=display,
                department="super",
                source=source,
                installed=True,
                pinned=emp_id == "codex-super-employee",
                description=summary,
                contact_route=f"/api/admin/{emp_id}/messages",
                mobile_contact_route=f"/api/mobile/v1/admin/{emp_id}/messages",
            )
        )
    return out


def derive_employee_contacts(
    installed_ids: set[str] | frozenset[str] | None = None,
    *,
    include_super: bool = True,
    include_enterprise_listed: bool = True,
) -> list[dict[str, Any]]:
    """三端统一的员工联系人列表（Web IM / 手机消息 / AI 员工页共用）。"""
    from app.mod_sdk.employee_ssot import (
        LISTING_LISTED,
        derive_admin_duty_roster,
        load_enterprise_employees,
    )

    installed = frozenset(str(x).strip() for x in (installed_ids or ()) if str(x).strip())
    manifest_meta = load_employee_manifest_meta()
    admin = derive_admin_duty_roster(installed_ids=installed)
    on_duty = set(admin.get("on_duty_employee_ids") or [])
    seen: set[str] = set()
    contacts: list[dict[str, Any]] = []

    if include_super:
        for row in _super_employee_contacts():
            eid = str(row.get("employee_id") or "").strip()
            if not eid or eid in seen:
                continue
            seen.add(eid)
            contacts.append(row)

    for dept in admin.get("departments") or []:
        if not isinstance(dept, dict):
            continue
        department = str(dept.get("id") or dept.get("key") or dept.get("label") or "admin").strip()
        for emp in dept.get("employees") or []:
            if not isinstance(emp, dict):
                continue
            eid = str(emp.get("id") or "").strip()
            if not eid or eid in seen:
                continue
            seen.add(eid)
            meta = manifest_meta.get(eid) or {}
            display = str(meta.get("name") or eid).strip() or eid
            desc = str(meta.get("description") or "").strip()
            is_installed = eid in on_duty
            contacts.append(
                _employee_contact_record(
                    eid,
                    display_name=display,
                    department=department,
                    source="installed" if is_installed else "planned",
                    installed=is_installed,
                    description=desc
                    or ("已安装，可联系" if is_installed else "编制内但未安装 employee_pack"),
                )
            )

    if include_enterprise_listed:
        for meta in load_enterprise_employees().values():
            if meta.get("listing") != LISTING_LISTED:
                continue
            eid = str(meta.get("id") or "").strip()
            if not eid or eid in seen:
                continue
            seen.add(eid)
            display = str(
                meta.get("label") or manifest_meta.get(eid, {}).get("name") or eid
            ).strip()
            desc = str(manifest_meta.get(eid, {}).get("description") or "").strip()
            is_installed = eid in installed
            contacts.append(
                _employee_contact_record(
                    eid,
                    display_name=display or eid,
                    department=str(meta.get("enterprise_layer") or "management"),
                    source="installed" if is_installed else "planned",
                    installed=is_installed,
                    description=desc,
                )
            )

    return contacts


def employee_label_maps() -> tuple[dict[str, str], dict[str, str]]:
    manifest_meta = load_employee_manifest_meta()
    employee_labels = {
        eid: str(meta.get("name") or eid) for eid, meta in manifest_meta.items() if meta.get("name")
    }
    employee_descriptions = {
        eid: str(meta.get("description") or "")
        for eid, meta in manifest_meta.items()
        if meta.get("description")
    }
    return employee_labels, employee_descriptions


__all__ = [
    "SUPER_EMPLOYEE_CONTACT_ORDER",
    "derive_employee_contacts",
    "employee_description",
    "employee_display_name",
    "employee_label_maps",
    "load_employee_manifest_meta",
]
