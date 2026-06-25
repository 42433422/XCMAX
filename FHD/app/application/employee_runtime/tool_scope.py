"""按员工能力派生「作用域工具子集」。

此前所有员工的 agent handler 共享同一份全量工具表 —— 差异只在 prompt。
本模块让差异真实生效：根据 manifest 的 capabilities / expertise / read_only，
从 ``get_workflow_tool_registry()`` 的基础工具里挑选适配子集（剔除员工包工具本身，避免递归）。

优先级：
1. 显式声明（``employee_config_v2.tools`` / ``actions.tools`` / ``actions.agent.tools``）—— 为 P4 迁移预留。
2. 能力关键词派生（excel / 图表 / 文档 / 导入 …）。
3. 兜底：只读员工给只读分析工具，其它给分析 + 文档生成。
"""

from __future__ import annotations

import logging
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

READ_TOOLS = ("excel_analysis", "excel_schema_understand", "excel_join_compare")
CHART_TOOLS = ("excel_chart_recommend",)
DOC_TOOLS = ("generate_office_document",)
WRITE_TOOLS = frozenset({"import_excel_to_database", "products_bulk_import"})
# 代码修改工具（patch_file/write_file 等）—— 受 scope_globs + write_approval gate 强制
CODE_WRITE_TOOLS = frozenset({"patch_file", "write_file"})

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


def _base_tool_specs() -> dict[str, dict[str, Any]]:
    """基础（非员工包）工具：name -> spec。"""
    try:
        from app.application.tools.workflow import get_workflow_tool_registry
        from app.mod_sdk.employee_tool_registry import is_employee_tool

        out: dict[str, dict[str, Any]] = {}
        for spec in get_workflow_tool_registry() or []:
            if not isinstance(spec, dict):
                continue
            name = str((spec.get("function") or {}).get("name") or "")
            if name and not is_employee_tool(name):
                out[name] = spec
        return out
    except RECOVERABLE_ERRORS:
        logger.debug("base tool specs unavailable", exc_info=True)
        return {}


def _explicit_allowlist(config: dict[str, Any], manifest: dict[str, Any]) -> list[str] | None:
    actions = config.get("actions") if isinstance(config.get("actions"), dict) else {}
    agent = actions.get("agent") if isinstance(actions.get("agent"), dict) else {}
    v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    for candidate in (
        config.get("tools"),
        actions.get("tools"),
        agent.get("tools"),
        v2.get("tools"),
        manifest.get("tools"),
    ):
        if isinstance(candidate, list):
            names = [str(x).strip() for x in candidate if str(x).strip()]
            if names:
                return names
    return None


def _capability_text(manifest: dict[str, Any], config: dict[str, Any]) -> str:
    parts: list[str] = []
    emp = manifest.get("employee") if isinstance(manifest.get("employee"), dict) else {}
    for cap in emp.get("capabilities") or []:
        if isinstance(cap, dict):
            parts.append(str(cap.get("label") or ""))
            parts.append(str(cap.get("description") or ""))
        else:
            parts.append(str(cap))
    cog = config.get("cognition") if isinstance(config.get("cognition"), dict) else {}
    agent = cog.get("agent") if isinstance(cog.get("agent"), dict) else {}
    role = agent.get("role") if isinstance(agent.get("role"), dict) else {}
    for exp in role.get("expertise") or []:
        parts.append(str(exp))
    for skill in cog.get("skills") or []:
        if isinstance(skill, dict):
            parts.append(str(skill.get("name") or ""))
            parts.append(str(skill.get("brief") or ""))
        else:
            parts.append(str(skill))
    identity = config.get("identity") if isinstance(config.get("identity"), dict) else {}
    for key in ("domain", "area", "description", "name"):
        parts.append(str(identity.get(key) or ""))
    parts.append(str(manifest.get("description") or ""))
    return " ".join(p for p in parts if p).lower()


def is_read_only(manifest: dict[str, Any], config: dict[str, Any]) -> bool:
    actions = config.get("actions") if isinstance(config.get("actions"), dict) else {}
    agent = actions.get("agent") if isinstance(actions.get("agent"), dict) else {}
    ws = agent.get("workspace") if isinstance(agent.get("workspace"), dict) else {}
    if bool(ws.get("read_only")):
        return True
    v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    wp = v2.get("workspace_policy") if isinstance(v2.get("workspace_policy"), dict) else {}
    return bool(wp.get("read_only"))


def resolve_employee_tools(
    employee_id: str, manifest: dict[str, Any], config: dict[str, Any]
) -> list[dict[str, Any]] | None:
    base = _base_tool_specs()
    if not base:
        return None

    allow = _explicit_allowlist(config, manifest)
    if allow is not None:
        selected = [n for n in allow if n in base]
        return [base[n] for n in selected] or None

    text = _capability_text(manifest, config)
    read_only = is_read_only(manifest, config)
    selected: list[str] = []

    def add(name: str) -> None:
        if name in base and name not in selected:
            selected.append(name)

    if any(k in text for k in _EXCEL_KW):
        for n in READ_TOOLS:
            add(n)
    if any(k in text for k in _CHART_KW):
        for n in CHART_TOOLS:
            add(n)
    if any(k in text for k in _DOC_KW):
        for n in DOC_TOOLS:
            add(n)
    if not read_only and any(k in text for k in _IMPORT_KW):
        for n in ("import_excel_to_database", "products_bulk_import"):
            add(n)

    if not selected:
        for n in ("excel_analysis", "excel_schema_understand", "generate_office_document"):
            add(n)

    if read_only:
        selected = [n for n in selected if n not in WRITE_TOOLS]

    return [base[n] for n in selected] or None


def employee_tool_names(
    employee_id: str, manifest: dict[str, Any], config: dict[str, Any]
) -> list[str]:
    """供可观测/测试使用：返回作用域工具名列表。"""
    specs = resolve_employee_tools(employee_id, manifest, config) or []
    return [str((s.get("function") or {}).get("name") or "") for s in specs]


__all__ = ["employee_tool_names", "is_read_only", "resolve_employee_tools"]
