"""Plan explicitly priced quotations using read-only entity resolution."""

import math
import re

from app.db.session import get_db

from .sales_entities import sales_entity_candidates
from .types import WorkflowNode


def explicit_sales_quote_node(message: str) -> WorkflowNode | None:
    match = re.fullmatch(
        r"(?:请|帮我)?给(?:客户)?([^，,；;]+?)报价[，,]\s*产品([^，,；;]+)"
        r"[，,]\s*数量([0-9]+(?:\.[0-9]+)?)[，,]\s*单价([0-9]+(?:\.[0-9]+)?)[。\s]*",
        message.strip(),
    )
    if match is None:
        return _unpriced_quote_node(message)
    customer_name, product_name, quantity, price = match.groups()
    quantity_value, price_value = float(quantity), float(price)
    if not math.isfinite(quantity_value) or quantity_value <= 0:
        return None
    if not math.isfinite(price_value):
        return None
    with get_db() as db:
        candidates = sales_entity_candidates(
            db, customer_name=customer_name, product_name=product_name
        )
    params = {}
    if candidates["customer_unique"]:
        params["customer_id"] = candidates["customer_candidates"][0]["id"]
    if candidates["product_unique"]:
        product = candidates["product_candidates"][0]
        params["items"] = [
            {
                "product_id": product["id"],
                "quantity": quantity_value,
                "unit_price": price_value,
                "unit": product["unit"],
            }
        ]
    return WorkflowNode(
        node_id="sales_quote",
        tool_id="sales",
        action="quote",
        params=params,
        risk="medium",
        idempotent=False,
        description="创建报价单",
    )


def _unpriced_quote_node(message: str) -> WorkflowNode | None:
    text = message.strip().rstrip("。")
    if not text.startswith("给") or not text.endswith("报个价"):
        return None
    body = text[1:-3]
    if body.count("的产品") != 1:
        return None
    customer_name, product_name = (part.strip() for part in body.split("的产品"))
    if not customer_name or not product_name or any(char in body for char in "，,；;。？！?\n"):
        return None
    if any(word in body for word in ("不要", "然后", "删除", "并且")):
        return None
    with get_db() as db:
        candidates = sales_entity_candidates(
            db, customer_name=customer_name, product_name=product_name
        )
    params = {}
    if candidates["customer_unique"]:
        params["customer_id"] = candidates["customer_candidates"][0]["id"]
    if candidates["product_unique"]:
        product = candidates["product_candidates"][0]
        params["_quote_product"] = {"product_id": product["id"], "unit": product["unit"]}
    return WorkflowNode(
        node_id="sales_quote",
        tool_id="sales",
        action="quote",
        params=params,
        risk="medium",
        idempotent=False,
        description=f"为{customer_name}的产品{product_name}报价；需补齐报价明细、数量和单价",
    )
