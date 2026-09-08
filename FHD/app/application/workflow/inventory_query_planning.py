"""Route explicit current-stock queries to a product-filtered inventory snapshot."""

from .types import WorkflowNode


def inventory_query_node(message: str) -> WorkflowNode | None:
    text = message.strip().rstrip("。？?")
    if text.startswith("请"):
        text = text[1:]
    for prefix in ("查一下", "查询", "查看", "看看", "看下"):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    else:
        return None
    if not text.endswith("的库存"):
        return None
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
