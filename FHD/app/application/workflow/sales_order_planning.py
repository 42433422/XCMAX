"""Build an ordered quote-and-confirm plan for explicit sales order requests."""

import math
import re

from app.db.session import get_db

from .sales_entities import sales_entity_candidates
from .types import WorkflowNode


def sales_order_nodes(message: str) -> list[WorkflowNode]:
    match = re.fullmatch(
        r"给客户([^，,；;]+)下订单[，,]\s*产品([^，,；;]+)[，,]\s*数量([0-9]+(?:\.[0-9]+)?)[。\s]*",
        message.strip(),
    )
    if match is None:
        return []
    customer, product_name, raw_quantity = match.groups()
    quantity = float(raw_quantity)
    if not math.isfinite(quantity) or quantity <= 0:
        return []
    with get_db() as db:
        candidates = sales_entity_candidates(db, customer_name=customer, product_name=product_name)
    params = {}
    if candidates["customer_unique"]:
        params["customer_id"] = candidates["customer_candidates"][0]["id"]
    if candidates["product_unique"]:
        product = candidates["product_candidates"][0]
        item = {"product_id": product["id"], "unit": product["unit"], "quantity": quantity}
        price = float(product["price"]) if product["price"] is not None else None
        if price is not None and math.isfinite(price) and price >= 0:
            params["items"] = [{**item, "unit_price": price}]
        else:
            params["_quote_product"] = item
    quote = WorkflowNode(
        node_id="order_quote",
        tool_id="sales",
        action="quote",
        params=params,
        risk="medium",
        idempotent=False,
        description="按产品当前价格拟定订单，待审批后创建",
    )
    confirm = WorkflowNode(
        node_id="order_confirm",
        tool_id="sales",
        action="confirm_from_result",
        params={"order_node_id": quote.node_id},
        depends_on=[quote.node_id],
        risk="medium",
        idempotent=True,
        description="确认本次生成的销售订单",
    )
    return [quote, confirm]
