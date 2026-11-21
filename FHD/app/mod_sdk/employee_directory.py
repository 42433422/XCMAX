"""企业端统一员工目录（智能对话 / 员工工作台 / 信息形象共用同一口径）。

口径固定为：本机已安装 employee_pack 中 ``runtime_ok`` 且不属于宿主管理岗
（``EMPLOYEE_TOOLS``）的员工。任何界面需要“可用员工”时都应读这里，
避免对话、工作台、通讯录各自筛选导致名单不一致。

展示类调用方可传 ``include_prompt_only=True``，把只有系统提示词、没有本地
Python 运行时的员工（如导入的对话型专家）一并纳入目录；执行类调用方保持
默认值，只拿 runnable 员工。
"""

from __future__ import annotations

import logging
from typing import Any

from app.application.employee_runtime.loader import candidate_pack_ids, list_installed_pack_records
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _roster_area_labels() -> dict[str, str]:
    """编制区域 key → 中文部门名（仅用于展示分组，不参与可见性）。"""
    try:
        from app.mod_sdk.duty_roster import load_duty_roster_document

        doc = load_duty_roster_document()
    except RECOVERABLE_ERRORS:
        return {}
    areas = doc.get("areas") if isinstance(doc, dict) else {}
    if not isinstance(areas, dict):
        return {}
    labels: dict[str, str] = {}
    for key, block in areas.items():
        if isinstance(block, dict) and str(block.get("label") or "").strip():
            labels[str(key)] = str(block["label"]).strip()
    return labels


def _roster_area_for_employee(pack_id: str) -> str:
    try:
        from app.mod_sdk.duty_roster import load_duty_roster_document

        doc = load_duty_roster_document()
    except RECOVERABLE_ERRORS:
        return ""
    areas = doc.get("areas") if isinstance(doc, dict) else {}
    if not isinstance(areas, dict):
        return ""
    for key, block in areas.items():
        if not isinstance(block, dict):
            continue
        ids = block.get("ids")
        if isinstance(ids, list) and pack_id in {str(x).strip() for x in ids}:
            return str(key)
    return ""


def _manifest_identity(manifest: dict[str, Any]) -> dict[str, Any]:
    cfg = manifest.get("employee_config_v2")
    if not isinstance(cfg, dict):
        return {}
    identity = cfg.get("identity")
    return identity if isinstance(identity, dict) else {}


def _display_label(manifest: dict[str, Any], pack_id: str) -> str:
    raw_employee = manifest.get("employee")
    employee = raw_employee if isinstance(raw_employee, dict) else {}
    identity = _manifest_identity(manifest)
    for raw in (
        employee.get("label"),
        identity.get("name"),
        manifest.get("name"),
    ):
        text = str(raw or "").strip()
        if text:
            return text
    return pack_id


def _description(manifest: dict[str, Any]) -> str:
    identity = _manifest_identity(manifest)
    for raw in (manifest.get("description"), identity.get("description")):
        text = str(raw or "").strip()
        if text:
            return text[:240]
    return ""


def _has_explicit_system_prompt(manifest: dict[str, Any]) -> bool:
    """员工是否显式声明了系统提示词（仅提示词型员工的判定依据）。"""
    cfg = manifest.get("employee_config_v2")
    if not isinstance(cfg, dict):
        return False
    cognition = cfg.get("cognition")
    if not isinstance(cognition, dict):
        return False
    agent = cognition.get("agent")
    if not isinstance(agent, dict):
        return False
    return bool(str(agent.get("system_prompt") or "").strip())


def build_employee_directory(
    include_prompt_only: bool = False, *, include_management: bool = False
) -> list[dict[str, Any]]:
    """返回统一员工目录（已排序）。

    ``include_prompt_only`` 仅给展示层使用：没有 direct_python 运行时、但显式
    声明了系统提示词的员工以 ``prompt_only=True`` 纳入目录。
    ``include_management`` 供随后执行账号授权检查的统一能力目录使用。
    """
    from app.mod_sdk.employee_specialized_tools_employee_map import EMPLOYEE_TOOLS
    from app.mod_sdk.employee_tool_registry import build_employee_tools_status

    status = build_employee_tools_status()
    tools = {
        str(row.get("pack_id") or ""): row
        for row in status.get("employee_pack_tools") or []
        if isinstance(row, dict) and row.get("pack_id")
    }
    records = {
        str(row.get("pack_id") or ""): row
        for row in list_installed_pack_records()
        if isinstance(row, dict) and row.get("pack_id")
    }
    area_labels = _roster_area_labels()

    employees: list[dict[str, Any]] = []
    for pack_id, tool in tools.items():
        if not pack_id:
            continue
        if not include_management and any(
            EMPLOYEE_TOOLS.get(candidate) for candidate in candidate_pack_ids(pack_id)
        ):
            continue
        manifest = records.get(pack_id, {}).get("manifest")
        manifest = manifest if isinstance(manifest, dict) else {}
        runtime_ok = bool(tool.get("runtime_ok"))
        handlers = list(tool.get("handlers") or [])
        prompt_only = (
            include_prompt_only
            and not runtime_ok
            and "direct_python" not in handlers
            and _has_explicit_system_prompt(manifest)
        )
        if not runtime_ok and not prompt_only:
            continue
        identity = _manifest_identity(manifest)
        area = str(identity.get("area") or "").strip() or _roster_area_for_employee(pack_id)
        employees.append(
            {
                "pack_id": pack_id,
                "label": _display_label(manifest, pack_id),
                "description": _description(manifest),
                "area": area,
                "department": area_labels.get(area, ""),
                "runtime_ok": runtime_ok,
                "prompt_only": prompt_only,
                "runtime_kind": "direct_python" if runtime_ok else "prompt_only",
                "handlers": handlers,
            }
        )
    employees.sort(key=lambda row: (row["label"], row["pack_id"]))
    return employees


__all__ = ["build_employee_directory"]
