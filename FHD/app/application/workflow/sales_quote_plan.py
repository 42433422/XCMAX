"""Preserve named quotation inputs and leave absent commercial terms unanswered."""

import re
from typing import Any

from app.application.workflow.types import WorkflowNode
from app.domain.services.conversation.chat_tool_intent import is_negated_action_request


def sales_quote_node(message: str, registry: dict[str, Any]) -> WorkflowNode | None:
    if "sales" not in registry or is_negated_action_request(message):
        return None
    if re.search(r"(?:创建|新建|新增)\s*(?:一[张个]\s*)?销售订单(?=[:：，,\s]|$)", message):

        def slot(label: str) -> str | None:
            found = re.search(
                rf"(?:^|[:：，,；;。\n])\s*(?:{label})\s*[:：]?\s*([^，,；;。\n]+)", message
            )
            return found.group(1).strip().strip("「」“”\"'") if found else None

        item: dict[str, Any] = {}
        for key, label in (
            ("model_number", "型号"),
            ("product_name", "产品名称|产品|商品名称|商品"),
        ):
            value = slot(label)
            if value:
                item[key] = value
        for key, label in (("quantity", "数量"), ("unit_price", "单价")):
            value = slot(label)
            number = re.fullmatch(r"(\d+(?:\.\d+)?)(?:件|个|元)?", value or "")
            if number:
                item[key] = float(number.group(1))
        customer = slot("客户名称|客户|购买单位")
        return WorkflowNode(
            node_id="sales_create_order",
            tool_id="sales",
            action="create_order",
            params={"customer_name": customer or "", "items": [item] if item else []},
            risk="medium",
            idempotent=False,
            description="创建并确认销售订单",
        )
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
