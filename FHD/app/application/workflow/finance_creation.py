"""Plan explicit single financial entries without dropping supplied text."""

from __future__ import annotations

import re

from .clarification_options import field_options
from .types import WorkflowNode


def direct_finance_create_node(message: str) -> WorkflowNode | None:
    options = field_options("finance", "create_transaction", "transaction_type")
    kinds = "|".join(re.escape(k) for k in options)
    match = re.fullmatch(
        rf"(?:请帮我|帮我|请)?\s*记(?:录)?一笔\s*({kinds})\s*"
        r"(\d+(?:\.\d+)?)\s*元(?:[，,]\s*来自\s*([^，,；;。\n]+))?[。\s]*",
        str(message or "").strip(),
    )
    if match is None:
        return None
    params = {"transaction_type": options[match.group(1)], "amount": float(match.group(2))}
    if match.group(3):
        params["counterparty_name"] = match.group(3).strip()
    return WorkflowNode(
        node_id="create_finance_transaction",
        tool_id="finance",
        action="create_transaction",
        params=params,
        risk="medium",
        idempotent=False,
        description="记录财务交易",
    )
