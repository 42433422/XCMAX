"""Plan explicitly priced quotations using read-only entity resolution."""

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
        return None
    customer_name, product_name, quantity, price = match.groups()
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
                "quantity": float(quantity),
                "unit_price": float(price),
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
