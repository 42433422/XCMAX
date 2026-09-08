"""Route shipment-document requests to the shipment tool instead of product search.

「打印 X 的发货单，编号…，规格…，一共 N 桶」 carries full slots and must hit
``shipment_orders.generate``; 「打个发货单」 lacks the purchase unit and must ask
first. Without this layer both fall through to the terminal ``products.query``
fallback — the cross-domain misrouting this module exists to fix.
"""

from __future__ import annotations

import re
import uuid

from .types import WorkflowNode

_TRIGGER_RE = re.compile(r"发货单|送货单|出货单")
_VERB_RE = re.compile(r"打印|生成|创建|开|打|做|出")
_NAME_RE = re.compile(r"([^\s，,。；]{2,})\s*的\s*(?:发货单|送货单|出货单)")
_MODEL_RE = re.compile(r"(?:编号|型号|货号)\s*[:：]?\s*([A-Za-z0-9._-]+)")
_SPEC_RE = re.compile(r"规格\s*[:：]?\s*(\d+(?:\.\d+)?)")
_QTY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:桶|箱|件|个|支|提)")


def _shipment_slots(text: str) -> dict[str, object]:
    """Parse unit/model/spec/quantity; empty values mean "not provided"."""
    unit = ""
    named = _NAME_RE.search(text)
    if named:
        unit = re.sub(r"^(?:打印|生成|开|打|做|一下)", "", named.group(1).strip()).strip()
    model = _MODEL_RE.search(text)
    spec = _SPEC_RE.search(text)
    qty = _QTY_RE.search(text)
    return {
        "unit_name": unit,
        "model": (model.group(1).upper() if model else ""),
        "spec": (float(spec.group(1)) if spec else None),
        "quantity": (int(float(qty.group(1))) if qty else None),
    }


def _standalone_clarify_node(question: str) -> WorkflowNode:
    """Clarification without a downstream target: resume re-plans from the answer."""
    return WorkflowNode(
        node_id=f"clarify_{uuid.uuid4().hex[:8]}",
        tool_id="clarify",
        action="ask",
        params={"question": question, "answer_key": "confirmed", "target_node_id": ""},
        risk="low",
        idempotent=True,
        description="反问澄清：发货单信息不足，待用户补充后再继续",
    )


def shipment_plan_nodes(message: str) -> list[WorkflowNode]:
    """Full slots → generate; trigger without slots → a single clarify node."""
    text = str(message or "").strip()
    if not text or not _TRIGGER_RE.search(text) or not _VERB_RE.search(text):
        return []
    if any(word in text for word in ("不要", "别", "不用", "取消", "删除", "清空")):
        return []
    slots = _shipment_slots(text)
    unit_name = str(slots["unit_name"] or "")
    has_detail = bool(slots["model"] or slots["spec"] or slots["quantity"])
    if not unit_name or not has_detail:
        return [
            _standalone_clarify_node(
                "请告诉我要给哪个客户（单位）开发货单，以及产品编号（型号）、规格和数量。"
            )
        ]
    product: dict[str, object] = {}
    if slots["model"]:
        product["name"] = slots["model"]
        product["model_number"] = slots["model"]
    if slots["spec"] is not None:
        product["specification"] = slots["spec"]
        product["tin_spec"] = slots["spec"]
    if slots["quantity"] is not None:
        product["quantity_tins"] = slots["quantity"]
        product["quantity"] = slots["quantity"]
    return [
        WorkflowNode(
            node_id="generate_shipment",
            tool_id="shipment_orders",
            action="generate",
            params={"unit_name": unit_name, "products": [product]},
            risk="high",
            idempotent=False,
            description=f"为 {unit_name} 生成发货单",
        )
    ]
