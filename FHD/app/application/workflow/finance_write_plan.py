"""Parse explicit cash transaction instructions into approval-gated tool inputs."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from app.application.workflow.types import WorkflowNode


def finance_transaction_node(message: str, registry: dict[str, Any]) -> WorkflowNode | None:
    if "finance" not in registry:
        return None
    match = re.fullmatch(
        r"(?:请)?\s*(?:记|记录)一笔\s*(收入|支出)\s*(\d+(?:\.\d{1,2})?)\s*元(?:[，,]\s*(?:来自|付给)\s*([^，,。]+))?[。]?",
        message.strip(),
    )
    if match is None:
        return None
    amount = Decimal(match.group(2))
    if amount <= 0 or amount >= Decimal("10000000000"):
        return None
    params: dict[str, Any] = {
        "transaction_type": "revenue" if match.group(1) == "收入" else "expense",
        "amount": float(amount),
        "currency": "CNY",
    }
    if match.group(3):
        params["counterparty_name"] = match.group(3).strip()
    return WorkflowNode(
        node_id="create_financial_transaction",
        tool_id="finance",
        action="create_transaction",
        params=params,
        risk="medium",
        idempotent=False,
        description="登记收支流水",
    )
