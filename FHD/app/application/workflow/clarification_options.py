"""Explicit business-language aliases for enumerated clarification fields."""

from __future__ import annotations

_OPTIONS = {
    ("finance", "create_transaction", "transaction_type"): {
        "收入": "revenue",
        "费用": "expense",
        "应收": "receivable",
        "应付": "payable",
        "收款": "receipt",
        "付款": "payment",
        "调整": "adjustment",
    },
}


def field_options(tool_id: str, action: str, field: str) -> dict[str, str]:
    return dict(_OPTIONS.get((tool_id, action, field), {}))
