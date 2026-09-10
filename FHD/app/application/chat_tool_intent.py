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

# 拒绝类请求（2026-09-09 审计 R02）：否定词直接紧邻动作动词时视为“不要做 X”，
# 不得进入写入/打印/开单等执行计划。只认紧邻形态，避免「特别好用」「别的客户」
# 这类词内假阳性；与 intent_config.yaml negation 段口径保持一致。
_NEGATED_ACTION_RE = re.compile(
    r"(?:不要|不用|不需要|不必|不想|不想再|别再|禁止|千万别|别)\s*"
    r"(?:再|先|马上|立刻|帮我|给我|帮|给|去|来)?\s*"
    r"(?:打印|打单|开单|发货|送货|出货|导出|导入|上传|下载|生成|制作|"
    r"删除|移除|删掉|删了|新增|添加|创建|新建|修改|更新|改为|改成|写入|入库|"
    r"发送|发微信|通知|登记|录入|安排|取消|撤销|打印标签|贴标)"
)


def is_negated_action_request(text: str) -> bool:
    """Return True when the message refuses an action ("不要打印…", "别删除…")."""
    value = str(text or "")
    if not value:
        return False
    normalized = re.sub(r"\s+", "", value)
    return bool(_NEGATED_ACTION_RE.search(normalized))


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
    # 拒绝类请求（审计 R02）：「不要删除客户X」不得判定为数据库写操作。
    if is_negated_action_request(value):
        return False
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

    # A named customer creation is explicit CRUD even without the word database.
    # The name must be explicitly delimited ("新增客户 蓝天科技" / "新增客户：蓝天科技")
    # or the ask must carry a request prefix ("请帮我添加客户星光贸易"); the bare
    # "添加客户公司A" wording stays on the legacy onboarding route.  Keep
    # underspecified onboarding and customer-product/order requests separate.
    stripped_value = value.strip()
    named_customer_create = re.match(
        r"^(?:请)?(?:帮我)?\s*(?:新增|添加)\s*(?:客户|购买单位)"
        r"(?:\s*[:：]\s*|\s+)([^，,。；;\s]{2,})",
        stripped_value,
    ) or re.match(
        r"^(?:请|帮我|请帮我)\s*(?:新增|添加)\s*(?:客户|购买单位)\s*[:：]?\s*([^，,。；;\s]{2,})",
        stripped_value,
    )
    if named_customer_create and not any(
        marker in value for marker in ("产品", "商品", "订单", "报价", "发货", "不要", "别", "取消")
    ):
        return True

    # Keep the legacy customer/product onboarding route for generic “添加/新增”
    # phrases.  Without explicit database wording, only verbs that unambiguously
    # describe record CRUD may enter the guarded business-database write path.
    unambiguous_mutation = any(
        keyword in value for keyword in _UNAMBIGUOUS_BUSINESS_DB_MUTATION_KEYWORDS
    )
    return business_entity and unambiguous_mutation


def looks_like_explicit_workflow_tool_intent(text: str) -> bool:
    """Return whether the user explicitly asked for an executable workflow tool."""
    value = str(text or "").strip()
    if not value:
        return False
    lower = value.lower()
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
