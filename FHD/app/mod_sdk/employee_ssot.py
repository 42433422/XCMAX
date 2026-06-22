# -*- coding: utf-8 -*-
"""员工 & 部门系统单一真相源（SSOT）+ 自动派生。

唯一数据源：``config/duty_roster.json``（由 :mod:`app.mod_sdk.duty_roster` 加载）。

两套部门 / 两类员工，互不重叠：

* 管理端（六线）  : ``departments`` —— 6 个部门管理「上岗员工」(on-duty)。
  上岗 = 编制内 ID ∩ 本机已安装 employee_pack（派生量，非存储状态）。
* 企业端（四层）  : ``enterprise_layers`` + ``enterprise_employees``。
  - ``listing == "listed"``   → 「上架员工」：员工商店可挑选。
  - ``listing == "unlisted"`` → 「未上架员工」：宿主入门服务器补的「定制员工」。

本模块只做「读 SSOT → 派生视图」，不写任何状态；上架/下架的真实写入仍在
MODstore catalog（见 ``catalog_visibility``）。所有派生函数均为纯函数，便于测试。
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from app.mod_sdk.duty_roster import (
    all_planned_duty_employee_ids,
    load_departments,
    load_duty_roster_document,
    primary_department_for_pkg,
)

# ---------------------------------------------------------------------------
# 企业端四层 —— 缺省定义（SSOT 缺失时的兜底，须与 config/duty_roster.json 一致）
# ---------------------------------------------------------------------------
DEFAULT_ENTERPRISE_LAYERS: tuple[dict[str, str], ...] = (
    {"id": "tools", "code": "L1", "label": "工具层", "desc": "连接、授权、技能与通用工具 Mod", "color": "#4f46e5"},
    {"id": "execution", "code": "L2", "label": "执行层", "desc": "出货、打单、单据与履约执行", "color": "#d97706"},
    {"id": "service", "code": "L3", "label": "服务层", "desc": "微信触达、客服沟通与人事服务", "color": "#059669"},
    {"id": "management", "code": "L4", "label": "管理层", "desc": "流程编排、路由协同与自治监控", "color": "#7c3aed"},
)

ENTERPRISE_LAYER_IDS: tuple[str, ...] = tuple(layer["id"] for layer in DEFAULT_ENTERPRISE_LAYERS)
LISTING_LISTED = "listed"
LISTING_UNLISTED = "unlisted"

# manifest / 别名 → 规范层 id（与 frontend enterpriseWorkflowEstablishment.ts 对齐）
_LAYER_ALIASES: dict[str, str] = {
    "tools": "tools", "tool": "tools", "tool_layer": "tools", "工具层": "tools", "工具": "tools",
    "execution": "execution", "action": "execution", "execution_layer": "execution", "执行层": "execution", "执行": "execution",
    "service": "service", "collaboration": "service", "service_layer": "service", "服务层": "service", "服务": "service",
    "management": "management", "manage": "management", "management_layer": "management", "管理层": "management", "管理": "management",
}

# 关键词推断（仅用于 SSOT 未登记的员工，保证「自动派生」对未知员工也成立）
_KEYWORD_LAYER_RULES: tuple[tuple[str, str], ...] = (
    ("tools", r"局域网|lan|授权|接入|gate|token|连接|工具|tool|skill|ocr|adapter"),
    ("execution", r"出货|收货|发货|shipment|receipt|delivery|履约|订单|对账|标签|打印|label|print|单据|票据|条码|excel|word|pdf|ppt|csv"),
    ("service", r"微信|wechat|消息|触点|客服|沟通|contacts|考勤|attendance|人事|排班|出勤|taiyangniao|太阳鸟"),
    ("management", r"编排|路由|orchestr|router|监控|自治|管理|workflow_auto|automator|dispatcher"),
)


def normalize_enterprise_layer_id(raw: Any) -> str | None:
    """把任意层名/别名规范成 4 个层 id 之一；无法识别返回 ``None``。"""
    key = str(raw or "").strip().lower()
    if not key:
        return None
    if key in ENTERPRISE_LAYER_IDS:
        return key
    return _LAYER_ALIASES.get(key) or _LAYER_ALIASES.get(str(raw or "").strip())


# ---------------------------------------------------------------------------
# 低层读取
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def load_enterprise_layers() -> tuple[dict[str, Any], ...]:
    """企业端四部门(层)定义，按声明顺序；SSOT 缺失时回退缺省。"""
    doc = load_duty_roster_document()
    raw = doc.get("enterprise_layers")
    out: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and normalize_enterprise_layer_id(item.get("id")):
                out.append(dict(item))
    if out:
        return tuple(out)
    return tuple(dict(x) for x in DEFAULT_ENTERPRISE_LAYERS)


@lru_cache(maxsize=1)
def load_enterprise_employees() -> dict[str, dict[str, Any]]:
    """企业员工注册表：``{emp_id: {label, enterprise_layer, listing, source, mod_id}}``。"""
    doc = load_duty_roster_document()
    raw = doc.get("enterprise_employees")
    out: dict[str, dict[str, Any]] = {}
    if isinstance(raw, dict):
        for emp_id, meta in raw.items():
            eid = str(emp_id or "").strip()
            if not eid or not isinstance(meta, dict):
                continue
            layer = normalize_enterprise_layer_id(meta.get("enterprise_layer")) or "management"
            listing = str(meta.get("listing") or "").strip().lower()
            if listing not in (LISTING_LISTED, LISTING_UNLISTED):
                listing = LISTING_UNLISTED
            out[eid] = {
                "id": eid,
                "label": str(meta.get("label") or eid),
                "enterprise_layer": layer,
                "listing": listing,
                "source": str(meta.get("source") or "").strip(),
                "mod_id": str(meta.get("mod_id") or "").strip(),
            }
    return out


# ---------------------------------------------------------------------------
# 自动派生 —— 企业端（4 层 / 上架 / 未上架）
# ---------------------------------------------------------------------------
def _infer_layer_by_keyword(blob: str) -> str:
    normalized = re.sub(r"[_-]+", " ", blob.lower())
    for layer_id, pattern in _KEYWORD_LAYER_RULES:
        if re.search(pattern, normalized):
            return layer_id
    return "management"


def enterprise_layer_for(
    emp_id: str, *, label: str = "", title: str = "", manifest_layer: Any = None
) -> str:
    """把工作流员工归入企业四部门之一。

    优先级：manifest 显式 ``enterprise_layer`` > SSOT 注册表 > 关键词推断 > management。
    """
    from_manifest = normalize_enterprise_layer_id(manifest_layer)
    if from_manifest:
        return from_manifest
    eid = str(emp_id or "").strip()
    registry = load_enterprise_employees()
    if eid in registry:
        return registry[eid]["enterprise_layer"]
    return _infer_layer_by_keyword(f"{eid} {label} {title}")


def listing_for(emp_id: str) -> str | None:
    """返回员工上架状态：``listed`` / ``unlisted``；未登记返回 ``None``。"""
    meta = load_enterprise_employees().get(str(emp_id or "").strip())
    return meta["listing"] if meta else None


def listed_employee_ids() -> frozenset[str]:
    """上架员工（员工商店可挑选）。"""
    return frozenset(
        eid for eid, m in load_enterprise_employees().items() if m["listing"] == LISTING_LISTED
    )


def unlisted_employee_ids() -> frozenset[str]:
    """未上架员工（宿主入门服务器补的定制员工）。"""
    return frozenset(
        eid for eid, m in load_enterprise_employees().items() if m["listing"] == LISTING_UNLISTED
    )


def employees_by_enterprise_layer() -> dict[str, list[dict[str, Any]]]:
    """企业端 4 部门 → 员工列表（含 listing），层顺序固定。"""
    buckets: dict[str, list[dict[str, Any]]] = {lid: [] for lid in ENTERPRISE_LAYER_IDS}
    for meta in load_enterprise_employees().values():
        buckets.setdefault(meta["enterprise_layer"], []).append(dict(meta))
    for rows in buckets.values():
        rows.sort(key=lambda r: r["id"])
    return buckets


def derive_enterprise_org() -> dict[str, Any]:
    """企业端 4 部门视图：每层含 listed/unlisted 员工。"""
    by_layer = employees_by_enterprise_layer()
    layers_out: list[dict[str, Any]] = []
    for layer in load_enterprise_layers():
        lid = str(layer.get("id"))
        members = by_layer.get(lid, [])
        layers_out.append(
            {
                **layer,
                "employees": members,
                "listed": [m for m in members if m["listing"] == LISTING_LISTED],
                "unlisted": [m for m in members if m["listing"] == LISTING_UNLISTED],
                "count": len(members),
            }
        )
    return {
        "layers": layers_out,
        "listed_employee_ids": sorted(listed_employee_ids()),
        "unlisted_employee_ids": sorted(unlisted_employee_ids()),
    }


# ---------------------------------------------------------------------------
# 自动派生 —— 管理端（6 部门 / 上岗）
# ---------------------------------------------------------------------------
def _dept_employee_ids(dept: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    subzones = dept.get("subzones")
    if isinstance(subzones, dict):
        for block in subzones.values():
            if isinstance(block, dict) and isinstance(block.get("ids"), list):
                ids.extend(str(x).strip() for x in block["ids"] if str(x).strip())
    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for x in ids:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def compute_duty_staffing(
    planned_ids: set[str] | frozenset[str], installed_ids: set[str] | frozenset[str]
) -> dict[str, Any]:
    """上岗派生的**唯一算法**：on_duty = 编制 ∩ 已安装；缺岗 = 编制 - 已安装。

    纯函数，被 :func:`derive_admin_duty_roster` 与
    ``app.application.local_duty_graph_health`` 共用，避免上岗逻辑多处重复。
    """
    planned = frozenset(str(x).strip() for x in planned_ids if str(x).strip())
    installed = frozenset(str(x).strip() for x in installed_ids if str(x).strip())
    on_duty = planned & installed
    return {
        "planned": sorted(planned),
        "installed": sorted(installed),
        "on_duty": sorted(on_duty),
        "missing": sorted(planned - installed),
        "extra": sorted(installed - planned),
        "planned_count": len(planned),
        "on_duty_count": len(on_duty),
    }


def derive_admin_duty_roster(installed_ids: set[str] | frozenset[str] | None = None) -> dict[str, Any]:
    """管理端 6 部门视图：每部门列出上岗员工。

    ``installed_ids`` 为本机已安装 employee_pack 集合（``None`` 时仅给编制，不判在岗）。
    上岗(on_duty) = 编制内 ∩ 已安装（经 :func:`compute_duty_staffing`）。
    """
    planned = all_planned_duty_employee_ids()
    staffing = (
        compute_duty_staffing(planned, installed_ids) if installed_ids is not None else None
    )
    on_duty_set = set(staffing["on_duty"]) if staffing is not None else None
    depts_out: list[dict[str, Any]] = []
    for dept_key, dept in load_departments().items():
        if not isinstance(dept, dict):
            continue
        emp_ids = _dept_employee_ids(dept)
        members: list[dict[str, Any]] = []
        for eid in emp_ids:
            on_duty = (eid in on_duty_set) if on_duty_set is not None else None
            members.append({"id": eid, "on_duty": on_duty})
        depts_out.append(
            {
                "id": str(dept.get("five_line_id") or dept_key),
                "key": dept_key,
                "label": str(dept.get("label") or dept_key),
                "employees": members,
                "planned_count": len(emp_ids),
                "on_duty_count": (
                    sum(1 for m in members if m["on_duty"]) if on_duty_set is not None else None
                ),
            }
        )
    return {
        "departments": depts_out,
        "planned_employee_ids": sorted(planned),
        "on_duty_employee_ids": (staffing["on_duty"] if staffing is not None else None),
    }


# ---------------------------------------------------------------------------
# 顶层聚合 —— 给 API / 前端的完整派生包
# ---------------------------------------------------------------------------
def derive_employee_ssot(installed_ids: set[str] | frozenset[str] | None = None) -> dict[str, Any]:
    """完整派生包：管理端 6 部门(上岗) + 企业端 4 部门(上架/未上架)。"""
    return {
        "schema_version": int(load_duty_roster_document().get("schema_version") or 0),
        "admin": derive_admin_duty_roster(installed_ids),
        "enterprise": derive_enterprise_org(),
    }


def primary_admin_department_for(emp_id: str) -> str | None:
    """员工在管理端 6 部门中的主归属（首次出现的 five_line_id）。"""
    return primary_department_for_pkg(emp_id)


__all__ = [
    "DEFAULT_ENTERPRISE_LAYERS",
    "ENTERPRISE_LAYER_IDS",
    "LISTING_LISTED",
    "LISTING_UNLISTED",
    "normalize_enterprise_layer_id",
    "load_enterprise_layers",
    "load_enterprise_employees",
    "enterprise_layer_for",
    "listing_for",
    "listed_employee_ids",
    "unlisted_employee_ids",
    "employees_by_enterprise_layer",
    "derive_enterprise_org",
    "compute_duty_staffing",
    "derive_admin_duty_roster",
    "derive_employee_ssot",
    "primary_admin_department_for",
]
