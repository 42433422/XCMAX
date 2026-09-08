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


# Leading tokens that, when they open the message, mean the user is refusing an
# action rather than requesting it. Only a *leading* refusal counts — "发货单不要
# 超过10桶" or "打印不要彩色" still want the write, so a mid-sentence 不要 must not
# block it.
_REFUSAL_PREFIXES = (
    "不要",
    "不用",
    "不需要",
    "不必",
    "不想",
    "别",
    "算了",
    "停止",
    "don't",
    "dont",
    "do not",
    "no need",
    "never",
)

# Politeness / filler that may precede the refusal word ("帮我不要…", "请别…").
_REFUSAL_LEADING_FILLERS = (
    "帮我",
    "给我",
    "请",
    "麻烦",
    "我",
    "你",
    "那",
    "这样",
    "先",
)

# Verbs that mark a write / mutating request. A refusal only matters when it
# targets one of these; refusing a bare read query is handled by other paths.
_WRITE_VERB_MARKERS = (
    "发货单",
    "送货单",
    "出货单",
    "开单",
    "打单",
    "打印",
    "生成",
    "删除",
    "移除",
    "删掉",
    "删了",
    "新增",
    "新建",
    "添加",
    "创建",
    "写入",
    "入库",
    "导入",
    "上传",
    "修改",
    "更新",
    "改为",
    "改成",
    "发微信",
    "发送微信",
    "微信通知",
    "通知",
    "请假",
    "休假",
    "事假",
    "病假",
    "年假",
    "调休",
    "婚假",
    "产假",
    "丧假",
    "导出",
)

# English write verbs need word boundaries ("add" must not match "address").
_WRITE_VERB_EN_RE = re.compile(
    r"\b(generate|shipment|invoice|delete|remove|create|add|upload|import|print|send)\b",
    re.IGNORECASE,
)

# 考勤域销假表达：「不用请假了」「假不请了」是合法的取消写入，不是拒绝生成计划。
_LEAVE_CANCEL_AS_WRITE_RE = re.compile(
    r"(?:不用|不需要|不想)?(?:请假|休假|事假|病假|年假|调休)了|假不请了|取消(?:请假|休假|事假|病假|年假|调休)"
)


def _strip_refusal_fillers(text: str) -> str:
    value = text.lstrip()
    changed = True
    while changed:
        changed = False
        for filler in _REFUSAL_LEADING_FILLERS:
            if value.startswith(filler):
                value = value[len(filler) :].lstrip()
                changed = True
    return value


def looks_like_refused_write(message: str) -> bool:
    """Detect "不要/别/不用 … 开发货单/删除/入库 …" style refusals of a write action.

    Returns True only when the message *opens* with a refusal word (after
    stripping politeness fillers) AND names a write verb somewhere. This blocks
    refusal-type requests from being routed into a write plan, while leaving
    mid-sentence negations ("发货单不要超过10桶") and read queries untouched.
    """
    value = str(message or "").strip()
    if not value:
        return False
    # 考勤域销假（「不用请假了」）是合法的取消写入请求，不是拒绝生成计划。
    if _LEAVE_CANCEL_AS_WRITE_RE.search(value):
        return False
    head = _strip_refusal_fillers(value).lower()
    if not head:
        return False
    # "别的…" is a comparison, not a refusal ("别的客户开发货单" still wants the write).
    if head.startswith("别的") or head.startswith("别个"):
        return False
    if not any(head.startswith(prefix) for prefix in _REFUSAL_PREFIXES):
        return False
    return any(marker in value for marker in _WRITE_VERB_MARKERS) or bool(
        _WRITE_VERB_EN_RE.search(value)
    )


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
