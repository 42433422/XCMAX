"""Use the existing shipment parser for explicit document requests."""

from typing import Any

from app.application.workflow.types import WorkflowNode

_MAX_PLANNER_TEXT_CHARS = 4096


def shipment_document_node(message: str, registry: dict[str, Any]) -> WorkflowNode | None:
    if len(message) > _MAX_PLANNER_TEXT_CHARS:
        return None
    documents = ("发货单", "送货单", "出货单")
    if "shipment_orders" not in registry or not any(label in message for label in documents):
        return None
    text = message.strip()
    for polite in ("请", "帮我"):
        if text.startswith(polite):
            text = text[len(polite) :].lstrip()
            break
    verbs = ("打印", "打个", "打一张", "开一张", "生成")
    if not any(text.startswith(verb) for verb in verbs):
        return None
    from app.services.tools_execution.order_parser import _parse_order_text

    # Bare requests have no extractable slots; avoid the parser's LLM fallback.
    bare_text = text
    verb = next((item for item in verbs if bare_text.startswith(item)), None)
    if verb:
        bare_text = bare_text[len(verb) :].lstrip()
    bare = bare_text.removesuffix("。").removesuffix("！").removesuffix("!") in documents
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
