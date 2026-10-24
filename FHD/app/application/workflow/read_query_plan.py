"""Deterministic customer reads shared by the workflow fallback.

Only explicit read requests qualify. Customer mentions in orders and writes must
remain with their own planner instead of being downgraded to a customer lookup.
"""

from __future__ import annotations

from typing import Any

from app.application.workflow.types import WorkflowNode

_MAX_PLANNER_TEXT_CHARS = 4096

_READ_VERBS = ("查询", "查一下", "查看", "看看", "看下", "搜索", "查下", "找下")


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _read_remainder(text: str, entities: tuple[str, ...]) -> str | None:
    value = text
    for polite in ("请", "帮我"):
        if value.startswith(polite):
            value = value[len(polite) :].lstrip()
            break
    verb = next((item for item in _READ_VERBS if value.startswith(item)), None)
    if verb is None:
        return None
    value = value[len(verb) :].lstrip()
    entity = next((item for item in entities if value.startswith(item)), None)
    if entity is None:
        return None
    value = value[len(entity) :].lstrip()
    if value.startswith(("：", ":")):
        value = value[1:].lstrip()
    for suffix in ("的信息", "的资料", "的详情", "信息", "资料", "详情"):
        if value.endswith(suffix):
            value = value[: -len(suffix)].rstrip()
            break
    return value.strip().strip('「」“”"')


def customer_read_node(
    message: str, route: dict[str, Any], registry: dict[str, Any]
) -> WorkflowNode | None:
    if len(message) > _MAX_PLANNER_TEXT_CHARS:
        return None
    if route.get("intent") != "customers_query" or "customers" not in registry:
        return None
    if _has_any(
        message,
        (
            "新增",
            "添加",
            "新建",
            "创建",
            "修改",
            "更新",
            "删除",
            "移除",
            "写入",
            "订单",
            "报价",
            "发货",
            "收款",
            "开票",
            "库存",
            "产品",
            "商品",
        ),
    ):
        return None
    text = message.strip().rstrip("。？！?!")
    listing = False
    value = text
    for polite in ("请", "帮我"):
        if value.startswith(polite):
            value = value[len(polite) :].lstrip()
            break
    verb = next((item for item in _READ_VERBS[:5] if value.startswith(item)), None)
    if verb:
        value = value[len(verb) :].lstrip()
    if value.startswith(("全部", "所有")):
        value = value[2:] if value.startswith("全部") else value[2:]
    entity = next((item for item in ("客户", "购买单位", "买家") if value.startswith(item)), None)
    if entity and value[len(entity) :] in ("列表", "清单", "有哪些", "都有谁"):
        listing = True
    if listing:
        keyword = ""
    else:
        remainder = _read_remainder(text, ("客户", "购买单位", "买家"))
        if not remainder:
            return None
        keyword = remainder
    return WorkflowNode(
        node_id="query_customers",
        tool_id="customers",
        action="query",
        params={"keyword": keyword},
        risk="low",
        idempotent=True,
        description="查询客户信息",
    )


def report_read_node(message: str, registry: dict[str, Any], *, today=None) -> WorkflowNode | None:
    if len(message) > _MAX_PLANNER_TEXT_CHARS:
        return None
    from calendar import monthrange
    from datetime import date

    if _has_any(message, ("新增", "添加", "删除", "修改", "更新", "写入", "导出", "记一笔")):
        return None
    tool, action = "", ""
    if _has_any(message, ("运营看板", "经营看板", "数据看板")):
        tool, action = "reports", "dashboard"
    elif _has_any(message, ("销售汇总", "销售报表", "销售统计")):
        tool, action = "reports", "sales_summary"
    elif any(
        message.find(verb) >= 0 and message.find(term, message.find(verb) + len(verb)) >= 0
        for verb in ("查询", "查看", "查一下", "看下")
        for term in ("账本", "总账")
    ):
        tool, action = "finance", "ledger_query"
    inventory_model = None
    for verb in ("查询", "查一下", "查看", "查下"):
        if not message.startswith(verb):
            continue
        product = message[len(verb) :].lstrip()
        if product.startswith("产品"):
            product = product[len("产品") :].lstrip()
        marker = product.find("库存")
        if marker < 1:
            continue
        model = product[:marker].rstrip()
        if model.endswith("的"):
            model = model[:-1].rstrip()
        if (
            model
            and (model[0].isascii() and model[0].isalnum())
            and all(c.isascii() and (c.isalnum() or c in "._-") for c in model)
        ):
            inventory_model = model
            break
    if inventory_model and not _has_any(message, ("入库", "出库", "盘点", "调整", "转移")):
        tool, action = "reports", "inventory_summary"
    if not tool or tool not in registry:
        return None
    params: dict[str, Any] = {}
    if action in {"sales_summary", "ledger_query"} and _has_any(message, ("本月", "这个月")):
        current = today or date.today()
        first = current.replace(day=1).isoformat()
        last = current.replace(day=monthrange(current.year, current.month)[1]).isoformat()
        params = {
            "start_date": first,
            "end_date": last if tool == "finance" else last + " 23:59:59.999999",
        }
    if action == "inventory_summary" and inventory_model:
        params["model_number"] = inventory_model.upper()
    if action == "sales_summary":
        params["group_by"] = "product"
    return WorkflowNode(
        node_id=f"{tool}_{action}",
        tool_id=tool,
        action=action,
        params=params,
        risk="low",
        idempotent=True,
        description="查询业务报表",
    )


def sales_export_node(message: str, registry: dict[str, Any], *, today=None) -> WorkflowNode | None:
    """Export explicit sales requests; an omitted period means all recorded sales."""
    if len(message) > _MAX_PLANNER_TEXT_CHARS:
        return None
    from calendar import monthrange
    from datetime import date

    text = message.strip()
    for polite in ("请", "帮我"):
        if text.startswith(polite):
            text = text[len(polite) :].lstrip()
            break
    if not text.startswith("导出") or "reports" not in registry:
        return None
    text = text[len("导出") :].lstrip()
    period = None
    for candidate in ("本月", "这个月", "全部", "所有"):
        if text.startswith(candidate):
            period, text = candidate, text[len(candidate) :].lstrip()
            break
    if text.endswith(("。", "！", "!")):
        text = text[:-1]
    if text != "销售报表":
        return None
    params: dict[str, Any] = {"report_type": "sales", "group_by": "product", "filename": "销售报表"}
    current_month = period in {"本月", "这个月"}
    if current_month:
        current = today or date.today()
        params["start_date"] = current.replace(day=1).isoformat()
        params["end_date"] = (
            current.replace(day=monthrange(current.year, current.month)[1]).isoformat()
            + " 23:59:59.999999"
        )
    return WorkflowNode(
        node_id="export_sales",
        tool_id="reports",
        action="export",
        params=params,
        risk="low",
        idempotent=True,
        description="按产品导出本月销售报表" if current_month else "按产品导出全部已记录销售报表",
    )
