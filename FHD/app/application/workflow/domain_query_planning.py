"""Route supplier / purchase / shipment-record / finance-report / materials /
settings phrasings.

These everyday queries previously fell through to the terminal ``products.query``
catch-all — a cross-domain misroute. ``domain_query_nodes`` keeps each phrasing
inside its own domain and returns the (intent, todo, nodes) triple so the
fallback planner stays within its size budget.
"""

from __future__ import annotations

import calendar
import re
import uuid
from datetime import date, timedelta
from typing import Any

from .types import WorkflowNode

_NEGATION_WORDS = ("不要", "别", "不用", "取消", "删除", "清空", "然后", "并且")

# 物料/原材料目录查询：「物料列表 / 原材料有哪些 / 查一下物料 树脂」。
_MATERIALS_RE = re.compile(
    r"^(?:请|帮我)?(?:查询|查看|查一下|看下|看看|列出)?\s*"
    r"(?:物料|原材料|材料)(?:列表|清单|目录)?(?:有哪些|都有哪些|有什么)?(?:\s+\S+)?[。？?\s]*$"
)
# 系统设置：「系统设置 / 查看公司信息」。
_SETTINGS_RE = re.compile(
    r"^(?:请|帮我)?(?:打开|进入|查看|查询|看下|看看)?\s*"
    r"(?:系统设置|设置|公司信息|公司资料)(?:页面)?[。？?\s]*$"
)
# 采购汇总报表：「采购汇总 / 采购报表 / 采购统计」。
_PURCHASE_SUMMARY_RE = re.compile(
    r"^(?:请|帮我)?(?:查询|查看|生成|看下|看看)?\s*"
    r"(?:采购汇总|采购报表|采购统计|采购明细表)(?:报表)?[。？?\s]*$"
)
# 销售排行口径：「销量排行 / 卖得最好的产品 / 哪个产品卖得最多」。
_SALES_RANKING_RE = re.compile(r"销量排行|销量排名|卖得最好|卖得最多|销售排行|销售排名")
# 销售状态过滤：「未发货的订单 / 已完成的订单 / 订单状态」。
_ORDER_STATUS_RE = re.compile(
    r"^(?:请|帮我)?(?:查询|查看|查一下|看下|看看)?\s*"
    r"(?:未发货|没发货|待发货|已发货|已出库|未出库|已完成|已出库|已签收|已取消|已作废|待确认|草稿|已确认|已开票|已收款)?"
    r"(?:的)?(?:销售)?订单(?:状态)?(?:列表|清单)?(?:有哪些|都有哪些|有什么)?[。？?\s]*$"
)
_ORDER_STATUS_MAP: tuple[tuple[str, str], ...] = (
    ("未发货", "confirmed"),
    ("没发货", "confirmed"),
    ("待发货", "confirmed"),
    ("已发货", "delivered"),
    ("已出库", "delivered"),
    ("未出库", "confirmed"),
    ("已签收", "delivered"),
    ("已完成", "delivered"),
    ("已取消", "cancelled"),
    ("已作废", "cancelled"),
    ("待确认", "quote"),
    ("草稿", "quote"),
    ("已确认", "confirmed"),
    ("已开票", "invoiced"),
    ("已收款", "paid"),
)
# 时间限定销售汇总：「今天营业额 / 昨日销售 / 本周销量」。
_PERIOD_SALES_RE = re.compile(
    r"^(?:今天|今日|昨天|昨日|本周|这周|上周|本季度|今年|本年)(?:的)?(?:营业额|营收|销售额|销售|销量|收入)"
)
# 应收/应付裸词：「应收账款明细 / 应付账款」。
_BARE_RECEIVABLE_RE = re.compile(
    r"^(?:请|帮我)?(?:查询|查看|查一下|看下|看看)?\s*(?:的)?(?:应收账款?|应收款|客户欠款)(?:明细|列表|清单)?[。？?\s]*$"
)
_BARE_PAYABLE_RE = re.compile(
    r"^(?:请|帮我)?(?:查询|查看|查一下|看下|看看)?\s*(?:的)?(?:应付账款?|应付款|欠供应商(?:的)?(?:款|钱)?)(?:明细|列表|清单)?[。？?\s]*$"
)
# 收支问句兜底：「这个月收入 / 花了多少钱 / 本月支出多少」。
_MONEY_Q_RE = re.compile(
    r"(?:收入|支出|花了|赚了|营业额|营收|回款|开销|花钱)[^，,。？?]{0,6}(?:多少|几多)|(?:这个月|本月|上个月|上月|今年|本年|今天|本周)(?:的)?(?:收入|支出|花了|营业额|营收|开销)"
)
# 生产工单：「工单列表 / 生产计划有哪些」。
_MRP_ORDER_RE = re.compile(
    r"^(?:请|帮我)?(?:查询|查看|查一下|看下|看看|列出)?\s*"
    r"(?:(?:生产|制造)(?:工单|订单|计划)|工单)(?:列表|清单)?(?:有哪些|都有哪些|有什么)?[。？?\s]*$"
)
# 缺槽写入：「新建客户 / 添加供应商 / 开发票 / 回款登记」→ 反问补齐，不猜测写入。
_CUSTOMER_CREATE_RE = re.compile(
    r"(?:新建|新增|添加|创建|开立)\s*(?:一个|一位|一名)?\s*(?:客户|单位)"
)
_SUPPLIER_CREATE_RE = re.compile(r"(?:新建|新增|添加|创建)\s*(?:一个|一家)?\s*供应商")
_INVOICE_RE = re.compile(r"(?:开|申请|补开|开具)\s*(?:一张|一下)?\s*(?:发票|增值税发票)")
_PAYMENT_RE = re.compile(
    r"(?:登记|录入|记录|确认)\s*(?:一笔|一下)?\s*(?:回款|收款|付款)|(?:回款|收款|付款)\s*(?:登记|录入|记录)"
)


def domain_query_nodes(
    message: str, tool_registry: dict[str, Any]
) -> tuple[str, list[str], list[WorkflowNode]] | None:
    """First matching domain route for the message, or None to fall through."""
    text = str(message or "")
    if "finance" in tool_registry:
        from .finance_report_planning import finance_aging_node, finance_profit_node

        aging_node = finance_aging_node(text)
        if aging_node is None:
            aging_node = _aging_bare_node(text)
        if aging_node is not None:
            return (
                "finance_aging_report",
                ["查询应收/应付账龄", "返回欠款明细", "输出账龄分布"],
                [aging_node],
            )
        profit_node = finance_profit_node(text)
        if profit_node is not None:
            return (
                "finance_profit_report",
                ["查询本月收支流水", "汇总利润/毛利概览", "返回结果"],
                [profit_node],
            )
    if "suppliers" in tool_registry:
        from .supplier_purchase_planning import supplier_query_node

        supplier_node = supplier_query_node(text)
        if supplier_node is not None:
            return ("suppliers_query", ["查询供应商列表", "返回供应商信息"], [supplier_node])
    if "purchase" in tool_registry:
        from .supplier_purchase_planning import (
            purchase_order_create_nodes,
            purchase_order_query_node,
        )

        purchase_query = purchase_order_query_node(text)
        if purchase_query is not None:
            return (
                "purchase_order_query",
                ["查询采购订单列表", "返回采购订单"],
                [purchase_query],
            )
        purchase_create = purchase_order_create_nodes(text)
        if purchase_create:
            return (
                "purchase_order_create",
                ["核对供应商与采购明细", "确认后创建采购订单", "返回创建结果"],
                purchase_create,
            )
    if "shipment_records" in tool_registry:
        from .shipment_records_planning import shipment_records_query_node

        records_node = shipment_records_query_node(text)
        if records_node is not None:
            return ("shipment_records_query", ["查询发货记录", "返回发货明细"], [records_node])
    if "materials" in tool_registry:
        materials_node = _materials_query_node(text)
        if materials_node is not None:
            return ("materials_query", ["查询物料列表", "返回物料信息"], [materials_node])
    if "settings" in tool_registry:
        settings_node = _settings_query_node(text)
        if settings_node is not None:
            return ("settings_query", ["查看系统设置", "返回设置信息"], [settings_node])
    if "reports" in tool_registry:
        purchase_summary = _purchase_summary_node(text)
        if purchase_summary is not None:
            return ("purchase_summary", ["生成采购汇总报表", "返回汇总结果"], [purchase_summary])
    if "reports" in tool_registry:
        ranking = _sales_ranking_node(text)
        if ranking is not None:
            return ("sales_ranking", ["按销量汇总销售报表", "返回排行结果"], [ranking])
        period = _period_sales_node(text)
        if period is not None:
            return ("sales_report", ["按时间范围汇总销售", "返回销售结果"], [period])
    if "sales" in tool_registry:
        status_node = _order_status_node(text)
        if status_node is not None:
            return ("sales_order_query", ["按状态查询销售订单", "返回订单列表"], [status_node])
    if "finance" in tool_registry:
        money_node = _money_question_node(text)
        if money_node is not None:
            return (
                "finance_ledger_query",
                ["查询收支流水", "汇总收支金额", "返回结果"],
                [money_node],
            )
    if "mrp" in tool_registry:
        mrp_node = _mrp_order_node(text)
        if mrp_node is not None:
            return ("mrp_order_query", ["查询生产工单", "返回工单列表"], [mrp_node])
    clarify = _missing_slot_clarify(text, tool_registry)
    if clarify is not None:
        return ("clarify_missing_slots", ["向用户确认缺失信息", "收到答复后再执行"], [clarify])
    return None


def _has_negation(text: str) -> bool:
    return any(word in text for word in _NEGATION_WORDS)


def _materials_query_node(text: str) -> WorkflowNode | None:
    stripped = text.strip()
    if not stripped or _has_negation(stripped) or not _MATERIALS_RE.match(stripped):
        return None
    keyword_match = re.search(
        r"(?:物料|原材料|材料)(?:列表|清单|目录)?(?:有哪些|都有哪些|有什么)?\s+(\S+)", stripped
    )
    params: dict[str, Any] = {"page": 1, "per_page": 50}
    if keyword_match:
        params["keyword"] = keyword_match.group(1)
    return WorkflowNode(
        node_id="materials_query",
        tool_id="materials",
        action="list" if not keyword_match else "query",
        params=params,
        risk="low",
        idempotent=True,
        description="查询物料/原材料目录",
    )


def _settings_query_node(text: str) -> WorkflowNode | None:
    stripped = text.strip()
    if not stripped or _has_negation(stripped) or not _SETTINGS_RE.match(stripped):
        return None
    return WorkflowNode(
        node_id="settings_query",
        tool_id="settings",
        action="query",
        params={},
        risk="low",
        idempotent=True,
        description="查看系统设置/公司信息",
    )


def _purchase_summary_node(text: str) -> WorkflowNode | None:
    stripped = text.strip()
    if not stripped or _has_negation(stripped) or not _PURCHASE_SUMMARY_RE.match(stripped):
        return None
    return WorkflowNode(
        node_id="purchase_summary",
        tool_id="reports",
        action="purchase_summary",
        params={},
        risk="low",
        idempotent=True,
        description="生成采购汇总报表",
    )


def _aging_bare_node(text: str) -> WorkflowNode | None:
    """「应收账款明细 / 应付账款」裸词：finance_aging_node 要求查询动词，这里补齐口径。"""
    stripped = text.strip()
    if not stripped or _has_negation(stripped):
        return None
    if _BARE_PAYABLE_RE.match(stripped):
        account_type, description = "payable", "查询应付账款账龄"
    elif _BARE_RECEIVABLE_RE.match(stripped):
        account_type, description = "receivable", "查询应收账款账龄"
    else:
        return None
    return WorkflowNode(
        node_id="finance_aging_report",
        tool_id="finance",
        action="aging_report",
        params={"account_type": account_type, "days": 90},
        risk="low",
        idempotent=True,
        description=description,
    )


def _money_question_node(text: str) -> WorkflowNode | None:
    """「这个月收入 / 花了多少钱」：无动词的收支问句兜底到本月账本。"""
    stripped = text.strip()
    if not stripped or _has_negation(stripped) or not _MONEY_Q_RE.search(stripped):
        return None
    current = date.today()
    first = current.replace(day=1)
    last = current.replace(day=calendar.monthrange(current.year, current.month)[1])
    return WorkflowNode(
        node_id="query_monthly_ledger",
        tool_id="finance",
        action="ledger_query",
        params={
            "start_date": first.isoformat(),
            "end_date": last.isoformat(),
            "page": 1,
            "per_page": 100,
        },
        risk="low",
        idempotent=True,
        description="查询本月收支流水",
    )


def _sales_ranking_node(text: str) -> WorkflowNode | None:
    stripped = text.strip()
    if not stripped or _has_negation(stripped) or not _SALES_RANKING_RE.search(stripped):
        return None
    return WorkflowNode(
        node_id="sales_ranking",
        tool_id="reports",
        action="sales_summary",
        params={"group_by": "product"},
        risk="low",
        idempotent=True,
        description="按产品汇总销售，用于销量排行",
    )


def _period_bounds(token: str, current: date) -> tuple[str, str]:
    if token in ("今天", "今日"):
        return current.isoformat(), current.isoformat() + " 23:59:59.999999"
    if token in ("昨天", "昨日"):
        day = current - timedelta(days=1)
        return day.isoformat(), day.isoformat() + " 23:59:59.999999"
    if token in ("本周", "这周"):
        start = current - timedelta(days=current.weekday())
        end = start + timedelta(days=6)
        return start.isoformat(), end.isoformat() + " 23:59:59.999999"
    if token == "上周":
        start = current - timedelta(days=current.weekday() + 7)
        end = start + timedelta(days=6)
        return start.isoformat(), end.isoformat() + " 23:59:59.999999"
    # 今年/本年/本季度：按年起算。
    return current.replace(month=1, day=1).isoformat(), current.isoformat()


def _period_sales_node(text: str) -> WorkflowNode | None:
    stripped = text.strip()
    if not stripped or _has_negation(stripped):
        return None
    match = _PERIOD_SALES_RE.match(stripped)
    if match is None:
        return None
    first, last = _period_bounds(stripped[:2], date.today())
    return WorkflowNode(
        node_id="period_sales_report",
        tool_id="reports",
        action="sales_summary",
        params={"start_date": first, "end_date": last, "group_by": "product"},
        risk="low",
        idempotent=True,
        description=f"查询{stripped[:2]}销售汇总",
    )


def _order_status_node(text: str) -> WorkflowNode | None:
    stripped = text.strip()
    if not stripped or _has_negation(stripped) or not _ORDER_STATUS_RE.match(stripped):
        return None
    params: dict[str, Any] = {"page": 1, "per_page": 20}
    for token, status in _ORDER_STATUS_MAP:
        if token in stripped:
            params["status"] = status
            break
    return WorkflowNode(
        node_id="query_sales_orders",
        tool_id="sales",
        action="query",
        params=params,
        risk="low",
        idempotent=True,
        description="查询销售订单列表",
    )


def _mrp_order_node(text: str) -> WorkflowNode | None:
    stripped = text.strip()
    if not stripped or _has_negation(stripped) or not _MRP_ORDER_RE.match(stripped):
        return None
    return WorkflowNode(
        node_id="query_mrp_orders",
        tool_id="mrp",
        action="query_orders",
        params={"page": 1, "per_page": 20},
        risk="low",
        idempotent=True,
        description="查询生产工单列表",
    )


def _clarify_node(question: str) -> WorkflowNode:
    return WorkflowNode(
        node_id=f"clarify_{uuid.uuid4().hex[:8]}",
        tool_id="clarify",
        action="ask",
        params={"question": question, "answer_key": "confirmed", "target_node_id": ""},
        risk="low",
        idempotent=True,
        description="反问澄清：操作信息不足，待用户补充后再继续",
    )


def _missing_slot_clarify(text: str, tool_registry: dict[str, Any]) -> WorkflowNode | None:
    """缺槽位的写入类指令：反问补齐，不猜测执行，也不落到产品搜索。"""
    stripped = text.strip()
    if not stripped or _has_negation(stripped):
        return None
    if "customers" in tool_registry:
        named = re.search(
            r"(?:新建|新增|添加|创建|开立)\s*(?:一个|一位|一名)?\s*(?:客户|单位)\s*[:：]?\s*(\S+)",
            stripped,
        )
        if named:
            return None  # 带名称的建客户交给既有 business_db/customers 路径处理。
        if _CUSTOMER_CREATE_RE.search(stripped):
            return _clarify_node("请告诉我新客户的名称（单位名），我确认后再创建客户档案。")
    if "suppliers" in tool_registry and _SUPPLIER_CREATE_RE.search(stripped):
        if not re.search(r"供应商\s*[:：]?\s*\S+", stripped):
            return _clarify_node("请告诉我供应商的名称和联系方式，我再添加供应商。")
    if "sales" in tool_registry:
        if _INVOICE_RE.search(stripped) and not re.search(r"发票\s*(?:给|对)\s*\S+", stripped):
            return _clarify_node("请告诉我要给哪张销售订单开票（订单号），我再开发票。")
        if _PAYMENT_RE.search(stripped):
            return _clarify_node("请告诉我是哪张订单的回款以及金额，我再登记。")
    return None
