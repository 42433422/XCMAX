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
