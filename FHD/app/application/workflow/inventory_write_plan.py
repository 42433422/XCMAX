"""Plan explicit counted stock-in requests without inventing a warehouse."""

import re
from typing import Any

from app.application.workflow.types import WorkflowNode


def stock_in_node(message: str, registry: dict[str, Any]) -> WorkflowNode | None:
    if "inventory" not in registry:
        return None
    match = re.fullmatch(
        r"(?:请|帮我)?产品\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*入库\s*(\d+(?:\.\d+)?)\s*(?:件|个)(?:[，,]\s*仓库\s*[:：]?\s*(.+?))?[。！!]?",
        message.strip(),
    )
    if not match:
        return None
    model, quantity, warehouse = match.groups()
    params: dict[str, Any] = {"model_number": model, "quantity": float(quantity)}
    if warehouse:
        params["warehouse_name"] = warehouse.strip()
    return WorkflowNode(
        node_id="stock_in",
        tool_id="inventory",
        action="stock_in",
        params=params,
        risk="high",
        idempotent=False,
        description=f"产品 {model} 入库 {quantity} 件",
    )
