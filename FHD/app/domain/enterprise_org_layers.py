"""企业端四部门（工具层/执行层/服务层/管理层）— 后端 SSOT。

镜像前端 ``frontend/src/constants/enterpriseWorkflowEstablishment.ts``，
与管理端六部门（``config/duty_roster.json``）相互独立。
员工从 AI 市场安装后，由 ``resolve_enterprise_org_layer()`` 自动派生至对应栏位。
"""

from __future__ import annotations

import re

ENTERPRISE_ORG_LAYER_IDS = ("tools", "execution", "service", "management")

ENTERPRISE_ORG_LAYERS: tuple[dict[str, str], ...] = (
    {"id": "tools", "code": "L1", "label": "工具层", "desc": "连接、授权、技能与通用工具 Mod"},
    {"id": "execution", "code": "L2", "label": "执行层", "desc": "出货、打单、单据与履约执行"},
    {"id": "service", "code": "L3", "label": "服务层", "desc": "微信触达、客服沟通与人事服务"},
    {"id": "management", "code": "L4", "label": "管理层", "desc": "流程编排、路由协同与自治监控"},
)

_LAYER_ID_SET = frozenset(ENTERPRISE_ORG_LAYER_IDS)

_MANIFEST_LAYER_ALIASES: dict[str, str] = {
    "tools": "tools",
    "tool": "tools",
    "tool_layer": "tools",
    "工具层": "tools",
    "工具": "tools",
    "execution": "execution",
    "action": "execution",
    "execution_layer": "execution",
    "执行层": "execution",
    "执行": "execution",
    "service": "service",
    "collaboration": "service",
    "service_layer": "service",
    "服务层": "service",
    "服务": "service",
    "management": "management",
    "manage": "management",
    "management_layer": "management",
    "管理层": "management",
    "管理": "management",
}

_EMP_ID_LAYER: dict[str, str] = {
    "label_print": "execution",
    "shipment_mgmt": "execution",
    "receipt_confirm": "execution",
    "wechat_msg": "service",
    "wechat_contacts": "service",
    "wechat_contacts_hub": "service",
    "wechat_phone": "service",
    "lan_gate": "tools",
    "lan_gate_hub": "tools",
    "lan_gate_ai": "tools",
    "attendance_ai": "service",
    "coating_ai": "service",
    "taiyangniao_attendance": "service",
    "workflow_automator": "management",
    "task_router_officer": "management",
    "daily_orchestrator": "management",
}

_KW_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"局域网|lan|授权|接入|gate|token|连接|工具|tool|skill|ocr|adapter"), "tools"),
    (
        re.compile(
            r"出货|收货|发货|shipment|receipt|delivery|履约|订单|对账|标签|打印|label|print|单据|票据|条码|excel|word|pdf|ppt|csv"
        ),
        "execution",
    ),
    (
        re.compile(r"微信|wechat|消息|触点|客服|沟通|contacts|考勤|attendance|人事|排班|出勤|taiyangniao|太阳鸟"),
        "service",
    ),
    (re.compile(r"编排|路由|orchestr|router|监控|自治|管理|workflow_auto|automator|dispatcher"), "management"),
)


def _normalize_blob(emp_id: str, short_name: str = "", panel_title: str = "") -> str:
    return f"{emp_id} {short_name} {panel_title}".lower().replace("_", " ").replace("-", " ")


def normalize_enterprise_org_layer_id(raw: str | None | None) -> str | None:
    key = str(raw or "").strip().lower()
    if not key:
        return None
    if key in _LAYER_ID_SET:
        return key
    return _MANIFEST_LAYER_ALIASES.get(key) or _MANIFEST_LAYER_ALIASES.get(str(raw or "").strip())


def resolve_enterprise_org_layer(
    emp_id: str,
    short_name: str = "",
    panel_title: str = "",
    manifest_layer: str | None = None,
) -> str:
    """将工作流员工归入企业四部门之一；manifest 显式 enterprise_layer 优先。"""
    from_manifest = normalize_enterprise_org_layer_id(manifest_layer)
    if from_manifest:
        return from_manifest

    eid = str(emp_id or "").strip().lower()
    if eid and eid in _EMP_ID_LAYER:
        return _EMP_ID_LAYER[eid]

    blob = _normalize_blob(eid, short_name, panel_title)
    for pattern, layer_id in _KW_RULES:
        if pattern.search(blob):
            return layer_id
    return "management"


def enterprise_departments() -> dict[str, dict[str, str]]:
    """返回 4 部门字典（与 ``load_departments()`` 结构对齐）。"""
    return {layer["id"]: {"label": layer["label"], "desc": layer["desc"]} for layer in ENTERPRISE_ORG_LAYERS}


def enterprise_org_layer_label(layer_id: str) -> str:
    for layer in ENTERPRISE_ORG_LAYERS:
        if layer["id"] == layer_id:
            return str(layer["label"])
    return layer_id


__all__ = [
    "ENTERPRISE_ORG_LAYER_IDS",
    "ENTERPRISE_ORG_LAYERS",
    "enterprise_departments",
    "enterprise_org_layer_label",
    "normalize_enterprise_org_layer_id",
    "resolve_enterprise_org_layer",
]
