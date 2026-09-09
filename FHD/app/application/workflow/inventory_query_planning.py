"""Route explicit current-stock queries to a product-filtered inventory snapshot."""

import re

from .types import WorkflowNode

_ID_RE = re.compile(r"[A-Za-z0-9]")
_NEGATION_WORDS = ("不要", "别", "不用", "取消", "删除", "清空", "然后", "并且")


_PRODUCT_STOCK_RE = re.compile(
    r"^(?:产品|商品)?\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*"
    r"(?:的)?(?:还有多少库存|还剩多少库存|库存还有多少|库存还剩多少|库存是多少|还有库存|库存)\s*"
    r"(?:件|个|箱|桶|支|包|瓶|台|套)?[。？?\s]*$"
)
# 低库存/缺货预警口径：优先于全量库存概览，落到 inventory.low_stock_alert。
_LOW_STOCK_RE = re.compile(
    r"快没货|没货|缺货|断货|库存不足|存货不足|低于安全|安全库存|库存预警|缺货预警"
)


def low_stock_alert_node(message: str) -> WorkflowNode | None:
    """「哪些产品快没货了 / 库存低于安全线的有哪些」→ inventory.low_stock_alert。"""
    text = str(message or "").strip()
    if not text or not _LOW_STOCK_RE.search(text):
        return None
    if any(word in text for word in _NEGATION_WORDS):
        return None
    if any(word in text for word in ("采购", "购买", "补充", "备货", "进货", "安排")):
        # 「库存不足就安排采购」属于库存-采购条件分支，交由既有 inventory_purchase 处理。
        return None
    return WorkflowNode(
        node_id="low_stock_alert",
        tool_id="inventory",
        action="low_stock_alert",
        params={},
        risk="low",
        idempotent=True,
        description="查询低于安全库存的产品",
    )


def inventory_query_node(message: str) -> WorkflowNode | None:
    text = message.strip().rstrip("。？?")
    if text.startswith("请"):
        text = text[1:]
    for prefix in ("查一下", "查询", "查看", "看看", "看下"):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    if not text.endswith("的库存"):
        # 「A100 还有多少库存 / 产品 A100 库存是多少」：带产品标识的余量问法。
        product_match = _PRODUCT_STOCK_RE.match(text)
        if product_match is None:
            return None
        keyword = product_match.group(1).strip()
        if keyword.startswith("产品") or keyword.startswith("商品"):
            keyword = keyword[2:].strip()
        if any(word in text for word in ("然后", "并且", "删除", "不要", "入库", "出库")):
            return None
        if not keyword:
            return None
        return WorkflowNode(
            node_id="inventory_snapshot",
            tool_id="reports",
            action="inventory_summary",
            params={"product_keyword": keyword},
            risk="low",
            idempotent=True,
            description="查询指定产品的当前库存",
        )
    keyword = text[:-3].strip()
    if keyword.startswith("产品"):
        keyword = keyword[2:].strip()
    if any(char in keyword for char in "，,；;。？！?\n"):
        return None
    if not keyword or any(
        word in keyword for word in ("然后", "并且", "删除", "不要", "入库", "出库")
    ):
        return None
    return WorkflowNode(
        node_id="inventory_snapshot",
        tool_id="reports",
        action="inventory_summary",
        params={"product_keyword": keyword},
        risk="low",
        idempotent=True,
        description="查询指定产品的当前库存",
    )


def general_inventory_query_node(message: str) -> WorkflowNode | None:
    """「库存有多少 / 看下库存 / 仓库里还有多少货」→ 全量库存概览。

    仅处理不带任何产品标识的纯概览问法；一旦消息含字母数字型号（如「查库存5003」）
    就交回精确口径或通用兜底，避免丢失关键词。复合指令、否定句与库存采购建议
    （由既有 inventory_purchase 分支处理）不在这里拦截。
    """
    text = str(message or "").strip()
    if not text or any(word in text for word in _NEGATION_WORDS):
        return None
    if any(word in text for word in ("采购", "购买", "补充", "备货", "进货")):
        return None
    if not re.search(r"库存|存货|仓库里|还有多少货", text):
        return None
    if _ID_RE.search(text):
        # 含产品标识（型号/编号）时不吞关键词，留给精确口径或通用兜底。
        return None
    return WorkflowNode(
        node_id="inventory_overview",
        tool_id="reports",
        action="inventory_summary",
        params={},
        risk="low",
        idempotent=True,
        description="查询当前库存概览",
    )


def inventory_route(
    message: str, tool_registry: dict[str, object]
) -> tuple[str, list[str], WorkflowNode] | None:
    """库存域统一入口：低库存预警优先，其次精确/概览查询。"""
    if "inventory" in tool_registry and (low := low_stock_alert_node(message)):
        return ("inventory_low_stock", ["查询低于安全库存的产品", "返回缺货清单"], low)
    if "reports" not in tool_registry:
        return None
    node = inventory_query_node(message) or general_inventory_query_node(message)
    if node is None:
        return None
    return ("inventory_query", ["查询库存", "返回库存结果"], node)
