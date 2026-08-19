"""Employee / department SSOT loaders for AI group chat."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.application.group_chat.constants import (
    _BRANCH_SAFE_RE,
    _REQUIRED_GROUP_MEMBER_IDS,
    _XIAOC_ASSISTANT_ID,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_json_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


async def _default_completion(messages: list[dict[str, str]]) -> dict[str, Any]:
    # 延迟导入，避免在不需要 LLM 的路径（建群/拉人/读消息）上引入依赖。
    from app.mod_sdk.mod_employee_llm import mod_employee_complete

    return await mod_employee_complete(messages, max_tokens=600, temperature=0.4)


def _default_employee_executor(
    employee_id: str,
    task: str,
    input_data: dict[str, Any],
    user_id: int,
) -> dict[str, Any]:
    from app.application.employee_runtime.executor import execute_employee_task_local

    return execute_employee_task_local(employee_id, task, input_data, user_id=user_id)


def _xiaoc_assistant_member() -> dict[str, Any]:
    return {
        "employee_id": _XIAOC_ASSISTANT_ID,
        "mod_id": "xcagi-core-assistant",
        "name": "小C助理",
        "avatar": "",
        "avatar_key": "assistant",
        "summary": "企业智能助手，负责群内上下文、任务拆解和工作汇报串联。",
        "department_key": "",
    }


def _member_public_shape(member: dict[str, Any]) -> dict[str, Any]:
    employee_id = str(member.get("employee_id") or "").strip()
    name = str(member.get("name") or employee_id)[:60]
    avatar = str(member.get("avatar") or "")
    avatar_key = str(member.get("avatar_key") or "").strip()
    is_xiaoc = employee_id in {_XIAOC_ASSISTANT_ID, "xiaoc-assistant"} or "小c" in name.lower()
    if avatar_key == "assistant" and not is_xiaoc:
        avatar_key = ""
    if not avatar_key:
        identity = f"{employee_id} {name} {avatar}".lower()
        if is_xiaoc:
            avatar_key = "assistant"
        elif "codex" in identity:
            avatar_key = "codex"
        elif "cursor" in identity:
            avatar_key = "cursor"
        elif "claude" in identity:
            avatar_key = "claude"
        elif "trae" in identity:
            avatar_key = "trae"
    return {
        "employee_id": employee_id,
        "mod_id": str(member.get("mod_id") or ""),
        "name": name,
        "avatar": avatar,
        "avatar_key": avatar_key,
        "summary": str(member.get("summary") or "")[:280],
    }


def _with_required_group_members(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for member in [_xiaoc_assistant_member(), *members]:
        if not isinstance(member, dict):
            continue
        shaped = _member_public_shape(member)
        employee_id = shaped["employee_id"]
        if not employee_id or employee_id in seen:
            continue
        seen.add(employee_id)
        out.append(shaped)
    return out


def _is_required_group_member(employee_id: str) -> bool:
    return str(employee_id or "").strip() in _REQUIRED_GROUP_MEMBER_IDS


def _member_employee_id(member: dict[str, Any]) -> str:
    return str(member.get("employee_id") or member.get("id") or "").strip()


def _normalize_branch_context(raw: Any) -> str:
    branch = str(raw or "").strip()
    if branch.startswith("origin/"):
        branch = branch[len("origin/") :]
    branch = _BRANCH_SAFE_RE.sub("-", branch.replace(" ", "-"))
    branch = re.sub(r"/+", "/", branch).strip("/.")
    while ".." in branch:
        branch = branch.replace("..", ".")
    if branch in {"", ".", "..", "HEAD"}:
        return ""
    return branch[:180]


def _default_departments() -> dict[str, Any]:
    """admin 模式默认部门：从 ``config/duty_roster.json`` 加载 6 部门。"""
    try:
        from app.mod_sdk.duty_roster import load_departments

        depts = load_departments()
        return depts if isinstance(depts, dict) else {}
    except RECOVERABLE_ERRORS:  # noqa: BLE001 - 部门配置缺失时回退到内置 6 部门
        return {}


def _default_enterprise_departments() -> dict[str, Any]:
    """enterprise 模式默认部门：4 层（工具层/执行层/服务层/管理层）。"""
    from app.domain.enterprise_org_layers import enterprise_departments

    return enterprise_departments()


def _dept_key_to_employee_ids(depts: dict[str, Any]) -> dict[str, list[str]]:
    """从 duty_roster 的 departments 展平 dept_key → [employee_id]。"""
    mapping: dict[str, list[str]] = {}
    for dept_key, dept in depts.items():
        if not isinstance(dept, dict):
            continue
        ids: list[str] = []
        subzones = dept.get("subzones") or {}
        if isinstance(subzones, dict):
            for block in subzones.values():
                if not isinstance(block, dict):
                    continue
                raw = block.get("ids")
                if isinstance(raw, list):
                    ids.extend(str(x).strip() for x in raw if str(x).strip())
        if ids:
            mapping[str(dept_key)] = ids
    return mapping


def _employee_manifest(employee_id: str) -> dict[str, Any]:
    manifest = (
        Path(__file__).resolve().parents[2] / "mods" / "_employees" / employee_id / "manifest.json"
    )
    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _default_duty_employee_loader() -> list[dict[str, Any]]:
    """admin 模式员工加载器：``config/duty_roster.json`` 编制员工。

    ``duty_roster.json`` 是员工 ID 与部门归属 SSOT；``duty_employee_registry.json`` 与
    本地 employee manifest 仅补充名称、描述、头像等展示元数据。
    返回 ``[{employee_id, mod_id, name, avatar, summary, department_key}]``。
    """
    from app.mod_sdk.duty_roster import load_departments, load_duty_employee_records

    depts = load_departments()
    if not isinstance(depts, dict) or not depts:
        return []
    emp_to_dept: dict[str, str] = {}
    for dept_key, ids in _dept_key_to_employee_ids(depts).items():
        for eid in ids:
            if eid not in emp_to_dept:
                emp_to_dept[eid] = str(dept_key)

    records_by_id: dict[str, dict[str, Any]] = {}
    for raw in load_duty_employee_records():
        eid = str(raw.get("id") or raw.get("pkg_id") or "").strip()
        if eid and eid not in records_by_id:
            records_by_id[eid] = raw

    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager
    except RECOVERABLE_ERRORS:  # noqa: BLE001
        get_mod_manager = None  # type: ignore[assignment]

    installed_by_id: dict[str, tuple[str, dict[str, Any], dict[str, Any]]] = {}
    if get_mod_manager is not None:
        try:
            mods = get_mod_manager().list_all_mods() or []
        except RECOVERABLE_ERRORS:  # noqa: BLE001
            mods = []
        for m in mods:
            if not isinstance(m, dict):
                continue
            mod_id = str(m.get("id") or m.get("mod_id") or "").strip()
            wf = m.get("workflow_employees")
            if not isinstance(wf, list):
                continue
            for emp in wf:
                if not isinstance(emp, dict):
                    continue
                eid = str(emp.get("id") or "").strip()
                if eid and eid not in installed_by_id:
                    installed_by_id[eid] = (mod_id, emp, m)

    employees = []
    for eid, dept_key in emp_to_dept.items():
        raw = records_by_id.get(eid, {})
        mod_id, emp, mod = installed_by_id.get(eid, ("", {}, {}))
        manifest = _employee_manifest(eid)
        manifest_employee = (
            manifest.get("employee") if isinstance(manifest.get("employee"), dict) else {}
        )
        if not isinstance(manifest_employee, dict):
            manifest_employee = {}
        name = str(
            raw.get("name")
            or raw.get("label")
            or raw.get("title")
            or emp.get("name")
            or emp.get("label")
            or emp.get("title")
            or emp.get("panel_title")
            or manifest.get("name")
            or manifest_employee.get("label")
            or eid
        ).strip()
        employees.append(
            {
                "employee_id": eid,
                "mod_id": str(raw.get("mod_id") or raw.get("pkg_id") or mod_id or eid),
                "name": name[:60],
                "avatar": str(
                    raw.get("avatar")
                    or raw.get("logo")
                    or raw.get("icon")
                    or emp.get("avatar")
                    or emp.get("avatar_url")
                    or mod.get("avatar")
                    or mod.get("logo")
                    or manifest.get("avatar")
                    or ""
                ),
                "summary": str(
                    raw.get("panel_summary")
                    or raw.get("description")
                    or emp.get("panel_summary")
                    or emp.get("market_description")
                    or mod.get("description")
                    or manifest.get("description")
                    or ""
                )[:280],
                "department_key": dept_key,
            }
        )
    _append_super_employees(employees)
    return employees


def _append_super_employees(employees: list[dict[str, Any]]) -> None:
    """追加超级员工（Codex / Cursor / Claude）到员工列表，使其可被拉入群聊。

    超级员工不属于任何部门（department_key 留空），不参与部门群自动补员，
    仅出现在手机端选人列表中供用户手动拉入。
    """
    try:
        from app.application.super_employee_service import (
            CLAUDE_PROFILE,
            CODEX_PROFILE,
            CURSOR_PROFILE,
            TRAE_PROFILE,
        )
    except RECOVERABLE_ERRORS:  # noqa: BLE001 - 超级员工模块不可用时静默跳过
        return
    existing = {str(e.get("employee_id") or "") for e in employees if isinstance(e, dict)}
    for profile in (CODEX_PROFILE, CURSOR_PROFILE, CLAUDE_PROFILE, TRAE_PROFILE):
        if profile.employee_id in existing:
            continue
        employees.append(
            {
                "employee_id": profile.employee_id,
                "mod_id": "super-employee",
                "name": profile.employee_name,
                "avatar": profile.avatar_path,
                "avatar_key": profile.avatar_key,
                "summary": f"{profile.display_tool} 超级员工，支持 CLI 直答与多设备派工。",
                "department_key": "",
            }
        )


def _default_enterprise_employee_loader() -> list[dict[str, Any]]:
    """enterprise 模式员工加载器：上架员工（MODstore 安装）+ 未上架员工（宿主定制）。

    数据源为 ``list_all_mods()``（已安装的 mod + employee_pack，含 host_foundation）。
    部门归属由 ``resolve_enterprise_org_layer()`` 自动派生至 4 层之一。
    """
    from app.domain.enterprise_org_layers import resolve_enterprise_org_layer

    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager
    except RECOVERABLE_ERRORS:  # noqa: BLE001
        return []

    employees: list[dict[str, Any]] = []
    try:
        mods = get_mod_manager().list_all_mods() or []
    except RECOVERABLE_ERRORS:  # noqa: BLE001
        return []
    for m in mods:
        if not isinstance(m, dict):
            continue
        mod_id = str(m.get("id") or m.get("mod_id") or "").strip()
        wf = m.get("workflow_employees")
        if not isinstance(wf, list):
            continue
        for emp in wf:
            if not isinstance(emp, dict):
                continue
            eid = str(emp.get("id") or "").strip()
            if not eid:
                continue
            name = str(
                emp.get("name")
                or emp.get("label")
                or emp.get("title")
                or emp.get("panel_title")
                or eid
            ).strip()
            panel_title = str(emp.get("panel_title") or "")
            manifest_layer = str(emp.get("enterprise_layer") or "")
            layer = resolve_enterprise_org_layer(eid, name, panel_title, manifest_layer or None)
            employees.append(
                {
                    "employee_id": eid,
                    "mod_id": mod_id,
                    "name": name[:60],
                    "avatar": str(
                        emp.get("avatar")
                        or emp.get("avatar_url")
                        or m.get("avatar")
                        or m.get("logo")
                        or ""
                    ),
                    "summary": str(
                        emp.get("panel_summary")
                        or emp.get("market_description")
                        or m.get("description")
                        or ""
                    )[:280],
                    "department_key": layer,
                }
            )
    # 超级员工(tier 2)仅对管理端开放：企业端群聊不追加，不可选、不可邀请、不可派工。
    return employees


# 部门配置不可用时的内置兜底（保证"默认 6 部门 6 个群"始终成立）。
_FALLBACK_DEPARTMENTS: list[tuple[str, str]] = [
    ("ops_acquisition", "O-A 获客部"),
    ("ops_partner", "O-B 伙伴部"),
    ("prod_web", "P-W 网站部"),
    ("prod_mod", "P-M Mod 部"),
    ("prod_software", "P-S 软件部"),
    ("shared_retention", "S-R 归档部"),
]

_FALLBACK_ENTERPRISE_DEPARTMENTS: list[tuple[str, str]] = [
    ("tools", "工具层"),
    ("execution", "执行层"),
    ("service", "服务层"),
    ("management", "管理层"),
]
