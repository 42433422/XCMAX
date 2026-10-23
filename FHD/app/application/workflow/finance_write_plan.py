"""Parse explicit cash transaction instructions into approval-gated tool inputs."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.application.workflow.types import WorkflowNode

_MAX_PLANNER_TEXT_CHARS = 4096


def finance_transaction_node(message: str, registry: dict[str, Any]) -> WorkflowNode | None:
    if len(message) > _MAX_PLANNER_TEXT_CHARS:
        return None
    if "finance" not in registry:
        return None
    text = message.strip()
    if text.endswith("。"):
        text = text[:-1].rstrip()
    if text.startswith("请"):
        text = text[1:].lstrip()
    if text.startswith("记录一笔"):
        text = text[len("记录一笔") :].lstrip()
    elif text.startswith("记一笔"):
        text = text[len("记一笔") :].lstrip()
    else:
        return None
    if text.startswith("收入"):
        transaction_kind = "收入"
        text = text[len("收入") :].lstrip()
    elif text.startswith("支出"):
        transaction_kind = "支出"
        text = text[len("支出") :].lstrip()
    else:
        return None
    amount_text = ""
    while text and ("0" <= text[0] <= "9" or (text[0] == "." and "." not in amount_text)):
        amount_text += text[0]
        text = text[1:]
    if not amount_text or amount_text.startswith(".") or amount_text.endswith("."):
        return None
    if "." in amount_text and len(amount_text.split(".", 1)[1]) not in (1, 2):
        return None
    text = text.lstrip()
    if not text.startswith("元"):
        return None
    text = text[len("元") :].lstrip()
    counterparty = None
    if text:
        if text[0] not in ("，", ","):
            return None
        text = text[1:].lstrip()
        marker = "来自" if text.startswith("来自") else "付给" if text.startswith("付给") else None
        if marker is None:
            return None
        text = text[len(marker) :].strip()
        if not text or any(char in text for char in "，,。"):
            return None
        counterparty = text
    amount = Decimal(amount_text)
    if amount <= 0 or amount >= Decimal("10000000000"):
        return None
    params: dict[str, Any] = {
        "transaction_type": "revenue" if transaction_kind == "收入" else "expense",
        "amount": float(amount),
        "currency": "CNY",
    }
    if counterparty:
        params["counterparty_name"] = counterparty
    return WorkflowNode(
        node_id="create_financial_transaction",
        tool_id="finance",
        action="create_transaction",
        params=params,
        risk="medium",
        idempotent=False,
        description="登记收支流水",
    )
