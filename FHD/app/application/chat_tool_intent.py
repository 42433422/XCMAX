"""Shared intent guards for chat paths that may otherwise bypass the workflow planner."""

from __future__ import annotations

import re
from typing import Any

_BUSINESS_DB_MUTATION_KEYWORDS = frozenset(
    {
        "新增",
        "新建",
        "添加",
        "创建",
        "写入",
        "加入数据库",
        "添加到数据库",
        "保存到数据库",
        "入库",
        "修改",
        "更新",
        "改为",
        "改成",
        "删除",
        "移除",
    }
)

_UNAMBIGUOUS_BUSINESS_DB_MUTATION_KEYWORDS = frozenset(
    {
        "新建",
        "创建",
        "写入",
        "修改",
        "更新",
        "改为",
        "改成",
        "删除",
        "移除",
    }
)


def attach_explicit_tenant_id(payload: dict[str, Any], message: str) -> dict[str, Any]:
    """Keep an explicit tenant target so the execution guard can reject it."""
    match = re.search(
        r"(?:tenant[\s_-]*id|租户\s*(?:id|编号))\s*[:：=]?\s*(\d+)", str(message or ""), re.I
    )
    if match:
        payload["tenant_id"] = int(match.group(1))
    return payload


def looks_like_business_db_write(message: str, lower: str | None = None) -> bool:
    """Recognize explicit CRUD without requiring users to say database jargon."""
    value = str(message or "")
    normalized = str(lower if lower is not None else value.lower())
    if not any(k in value for k in _BUSINESS_DB_MUTATION_KEYWORDS) and not any(
        k in normalized for k in ("add", "create", "insert", "upsert", "update", "delete", "remove")
    ):
        return False
    db_marker = (
        any(k in value for k in ("数据库", "入库", "写库"))
        or "db" in normalized
        or "database" in normalized
    )
    business_entity = any(
        k in value for k in ("客户", "单位", "产品", "商品", "原材料", "物料", "发货", "出货")
    )
    if db_marker:
        return True

    # Keep the legacy customer/product onboarding route for generic “添加/新增”
    # phrases.  Without explicit database wording, only verbs that unambiguously
    # describe record CRUD may enter the guarded business-database write path.
    unambiguous_mutation = any(
        keyword in value for keyword in _UNAMBIGUOUS_BUSINESS_DB_MUTATION_KEYWORDS
    )
    return business_entity and unambiguous_mutation


def looks_like_erp_hr_management_intent(message: str) -> bool:
    """Recognize host ERP personnel/department management, not AI employee packs."""
    value = str(message or "").strip()
    if not value:
        return False
    lower = value.lower()
    if any(token in value for token in ("AI员工", "智能员工", "员工包")):
        return False
    if (
        any(token in value for token in ("调用", "交给", "让员工", "运行员工"))
        and "部门" not in value
        and not any(token in value for token in ("人员档案", "员工档案", "员工信息"))
    ):
        return False
    entity_named = (
        any(
            token in value
            for token in (
                "人员",
                "人事",
                "部门",
                "员工档案",
                "员工名单",
                "员工信息",
                "在职员工",
                "离职员工",
            )
        )
        or "department" in lower
        or "personnel" in lower
    )
    if not entity_named and "员工" in value:
        entity_named = any(
            token in value
            for token in (
                "查询",
                "查看",
                "名单",
                "档案",
                "新增",
                "新建",
                "创建",
                "修改",
                "更新",
                "删除",
                "移除",
                "停用",
                "归档",
                "所有",
                "全部",
            )
        )
    if not entity_named:
        return False
    action_named = any(
        token in value
        for token in (
            "查",
            "看",
            "列出",
            "名单",
            "档案",
            "新增",
            "新建",
            "创建",
            "添加",
            "修改",
            "更新",
            "改为",
            "改成",
            "调到",
            "删除",
            "移除",
            "清空",
            "停用",
            "归档",
        )
    ) or any(
        token in lower
        for token in ("list", "query", "create", "update", "delete", "deactivate", "archive")
    )
    return action_named


def looks_like_explicit_workflow_tool_intent(text: str) -> bool:
    """Return whether the user explicitly asked for an executable workflow tool."""
    value = str(text or "").strip()
    if not value:
        return False
    lower = value.lower()
    if looks_like_erp_hr_management_intent(value):
        return True
    employee_mentioned = any(k in value for k in ("员工", "调用", "交给")) or "employee" in lower
    employee_action = any(k in value for k in ("调用", "执行", "运行", "交给", "让")) or any(
        k in lower for k in ("call", "run", "execute", "employee")
    )
    if employee_mentioned and employee_action:
        return True

    db_object = any(k in value for k in ("客户", "单位", "产品", "物料", "原材料", "发货", "出货"))
    mutation_action = any(
        k in value
        for k in (
            "写",
            "写入",
            "新建",
            "新增",
            "添加",
            "创建",
            "修改",
            "更新",
            "删除",
            "移除",
            "删掉",
        )
    ) or any(k in lower for k in ("write", "create", "update", "delete"))
    # Office users naturally say "新建客户" or "修改刚才的产品" without
    # spelling out "database".  A known business entity plus an explicit
    # mutation verb is already a sufficiently narrow workflow-tool request.
    if db_object and mutation_action:
        return True

    db_mentioned = (
        any(k in value for k in ("数据库", "查库", "读库", "写库"))
        or "database" in lower
        or bool(re.search(r"\bdb\b", lower))
    )
    db_action = any(k in value for k in ("查", "读", "读取")) or any(
        k in lower for k in ("read", "query")
    )
    return db_mentioned and db_object and db_action
