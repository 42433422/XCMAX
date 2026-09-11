"""Use the existing shipment parser for explicit document requests."""

import re
from typing import Any

from app.application.workflow.types import WorkflowNode


def shipment_document_node(message: str, registry: dict[str, Any]) -> WorkflowNode | None:
    if "shipment_orders" not in registry or not re.search(r"发货单|送货单|出货单", message):
        return None
    if not re.match(r"^(?:请|帮我)?\s*(?:打印|打个|打一张|开一张|生成)", message.strip()):
        return None
    from app.services.tools_execution.order_parser import _parse_order_text

    # Bare requests have no extractable slots; avoid the parser's LLM fallback.
    bare = re.fullmatch(
        r"(?:请|帮我)?\s*(?:打印|打个|打一张|开一张|生成)\s*(?:发货单|送货单|出货单)[。！!]?",
        message.strip(),
    )
    parsed = {} if bare else _parse_order_text(message)
    params = {}
    if parsed.get("success"):
        params = {"unit_name": parsed["unit_name"], "products": parsed["products"]}
    return WorkflowNode(
        node_id="generate_shipment",
        tool_id="shipment_orders",
        action="generate",
        params=params,
        risk="medium",
        idempotent=False,
        description="生成发货单文件",
    )
