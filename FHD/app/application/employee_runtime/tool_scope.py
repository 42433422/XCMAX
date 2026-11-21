"""员工能力声明只收窄当前账号的权威能力目录，不注册独立工具契约。"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

READ_TOOLS = ("excel_analysis", "excel_toolkit", "excel_analyzer")
DOC_TOOLS = ("generate_office_document",)


def __getattr__(name: str):
    if name == "WRITE_TOOLS":
        from resources.config.risk_actions_loader import list_write_tools

        return list_write_tools()
    if name == "CODE_WRITE_TOOLS":
        from resources.config.risk_actions_loader import list_code_write_tools

        return list_code_write_tools()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


_EXCEL_KW = (
    "excel",
    "表格",
    "spreadsheet",
    "数据",
    "data",
    "sheet",
    "csv",
    "汇总",
    "统计",
    "analy",
    "分析",
    "报表",
)
_CHART_KW = ("chart", "图表", "可视", "viz", "plot", "看板", "dashboard")
_DOC_KW = (
    "文档",
    "报告",
    "报表",
    "document",
    "word",
    "报价",
    "单据",
    "receipt",
    "deliver",
    "交付",
    "generate",
    "合同",
    "contract",
    "letter",
    "函",
    "ppt",
    "幻灯",
    "pdf",
)
_IMPORT_KW = ("导入", "入库", "import", "批量", "bulk", "录入", "ingest", "写库")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _explicit_allowlist(config: dict[str, Any], manifest: dict[str, Any]) -> list[str] | None:
    actions = _as_dict(config.get("actions"))
    agent = _as_dict(actions.get("agent"))
    v2 = _as_dict(manifest.get("employee_config_v2"))
    for candidate in (
        config.get("tools"),
        actions.get("tools"),
        agent.get("tools"),
        v2.get("tools"),
        manifest.get("tools"),
    ):
        if isinstance(candidate, list):
            return [x.strip() for x in candidate if isinstance(x, str) and x.strip()]
    return None


def _capability_text(manifest: dict[str, Any], config: dict[str, Any]) -> str:
    parts: list[str] = []
    emp = _as_dict(manifest.get("employee"))
    for cap in emp.get("capabilities") or []:
        if isinstance(cap, dict):
            parts.append(str(cap.get("label") or ""))
            parts.append(str(cap.get("description") or ""))
        else:
            parts.append(str(cap))
    cog = _as_dict(config.get("cognition"))
    agent = _as_dict(cog.get("agent"))
    role = _as_dict(agent.get("role"))
    for exp in role.get("expertise") or []:
        parts.append(str(exp))
    for skill in cog.get("skills") or []:
        if isinstance(skill, dict):
            parts.append(str(skill.get("name") or ""))
            parts.append(str(skill.get("brief") or ""))
        else:
            parts.append(str(skill))
    identity = _as_dict(config.get("identity"))
    for key in ("domain", "area", "description", "name"):
        if not isinstance(identity, dict):
            identity = {}
        parts.append(str(identity.get(key) or ""))
    parts.append(str(manifest.get("description") or ""))
    return " ".join(p for p in parts if p).lower()


def is_read_only(manifest: dict[str, Any], config: dict[str, Any]) -> bool:
    actions = _as_dict(config.get("actions"))
    agent = _as_dict(actions.get("agent"))
    ws = _as_dict(agent.get("workspace"))
    if bool(ws.get("read_only")) or bool(_as_dict(config.get("workspace_policy")).get("read_only")):
        return True
    v2 = _as_dict(manifest.get("employee_config_v2"))
    wp = _as_dict(v2.get("workspace_policy"))
    return bool(wp.get("read_only"))


def resolve_employee_tools(
    employee_id: str,
    manifest: dict[str, Any],
    config: dict[str, Any],
    runtime_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    from app.application.tools.workflow import get_workflow_tool_registry

    allow = _explicit_allowlist(config, manifest)
    if allow is None:
        text = _capability_text(manifest, config)
        allow = []
        if any(word in text for word in (*_EXCEL_KW, *_CHART_KW)):
            allow.extend(READ_TOOLS)
        if any(word in text for word in _DOC_KW):
            allow.extend(DOC_TOOLS)
        if any(word in text for word in _IMPORT_KW):
            allow.extend(("elt_import", "excel_import"))
        if not allow:
            allow = [*READ_TOOLS, *DOC_TOOLS]
    return get_workflow_tool_registry(
        runtime_context,
        allowed_tools=allow,
        read_only=is_read_only(manifest, config),
        exclude_tools={"employee"},
    )


def employee_tool_names(
    employee_id: str,
    manifest: dict[str, Any],
    config: dict[str, Any],
    runtime_context: dict[str, Any] | None = None,
) -> list[str]:
    """返回实际已投影的能力动作，而不是统一传输工具名。"""
    return [
        f"{branch['properties']['tool_id']['enum'][0]}.{branch['properties']['action']['enum'][0]}"
        for spec in resolve_employee_tools(employee_id, manifest, config, runtime_context)
        for branch in spec["function"]["parameters"]["anyOf"]
    ]


__all__ = ["employee_tool_names", "is_read_only", "resolve_employee_tools"]


def host_employee_denial(
    employee_ids: list[str], payload: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any] | None:
    """Customer execution grants do not grant host-side management tools."""
    if "_actor_authorization" not in context:
        return None
    from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError, _bound_actor
    from app.mod_sdk.employee_specialized_tools_employee_map import EMPLOYEE_TOOLS

    try:
        actor = _bound_actor(context)
        if actor.role == "admin" and actor.tier == "admin" and actor.tenant_id is None:
            return None
    except AgentModAuthorizationError:
        return {
            "success": False,
            "error_code": "tool_identity_required",
            "error": "员工身份授权无效",
        }
    if str(payload.get("handler") or "").strip() == "specialized" or any(
        EMPLOYEE_TOOLS.get(name) for name in employee_ids
    ):
        return {
            "success": False,
            "error_code": "employee_host_admin_required",
            "error": "宿主管理员工和专用工具需要平台管理员权限",
        }
    return None
