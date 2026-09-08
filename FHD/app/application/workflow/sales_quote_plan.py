"""Preserve named quotation inputs and leave absent commercial terms unanswered."""

import re
from typing import Any

from app.application.workflow.types import WorkflowNode


def sales_quote_node(message: str, registry: dict[str, Any]) -> WorkflowNode | None:
    if "sales" not in registry:
        return None
    match = re.fullmatch(
        r"(?:请|帮我)?给\s*(.+?)\s*的产品\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*报(?:个)?价"
        r"(?:[，,]\s*数量\s*(\d+(?:\.\d+)?))?"
        r"(?:[，,]\s*单价\s*(\d+(?:\.\d+)?)(?:元)?)?[。！!]?",
        message.strip(),
    )
    action = "quote"
    if not match:
        match = re.fullmatch(
            r"(?:请|帮我)?给客户\s*(.+?)\s*下订单[，,]\s*产品\s*([A-Za-z0-9][A-Za-z0-9._-]*)"
            r"(?:[，,]\s*数量\s*(\d+(?:\.\d+)?))?"
            r"(?:[，,]\s*单价\s*(\d+(?:\.\d+)?)(?:元)?)?[。！!]?",
            message.strip(),
        )
        action = "create_order"
    if not match:
        return None
    customer, model, quantity, price = match.groups()
    item: dict[str, Any] = {"model_number": model}
    if quantity is not None:
        item["quantity"] = float(quantity)
    if price is not None:
        item["unit_price"] = float(price)
    return WorkflowNode(
        node_id=f"sales_{action}",
        tool_id="sales",
        action=action,
        params={"customer_name": customer, "items": [item]},
        risk="medium",
        idempotent=False,
        description=f"为{customer}创建{model}报价单"
        if action == "quote"
        else f"为{customer}创建并确认{model}销售订单",
    )
