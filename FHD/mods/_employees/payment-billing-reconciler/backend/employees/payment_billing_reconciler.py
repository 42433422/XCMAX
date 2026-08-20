"""Deterministic, read-only anonymized billing ledger reconciler."""

from __future__ import annotations

from typing import Any


def run(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    ledger = dict(payload or {}).get("ledger")
    if not isinstance(ledger, dict):
        return _failed("ledger object is required", "missing_ledger")
    orders = ledger.get("orders") if isinstance(ledger.get("orders"), list) else []
    payments = ledger.get("payments") if isinstance(ledger.get("payments"), list) else []
    refunds = ledger.get("refunds") if isinstance(ledger.get("refunds"), list) else []
    if not orders and not payments and not refunds:
        return {
            "ok": True,
            "status": "no_data",
            "summary": "已只读查询订单与支付账本，当前没有可对账记录；未访问支付渠道或改账。",
            "totals": {
                "orders_cents": 0,
                "payments_cents": 0,
                "refunds_cents": 0,
                "difference_cents": 0,
            },
            "issues": [],
            "reconciled": False,
            "evidence": ["input.ledger", "authoritative_empty_observation"],
            "read_only": True,
            "side_effects": [],
            "no_effect": True,
        }
    issues: list[dict[str, str]] = []

    def total(rows: list[Any], group: str) -> int:
        amount = 0
        for index, raw in enumerate(rows[:1000]):
            row = raw if isinstance(raw, dict) else {}
            cents = row.get("amount_cents")
            if not str(row.get("id") or "").strip() or not isinstance(cents, int) or cents < 0:
                issues.append({"code": "invalid_ledger_row", "path": f"ledger.{group}[{index}]"})
            else:
                amount += cents
        return amount

    order_total = total(orders, "orders")
    payment_total = total(payments, "payments")
    refund_total = total(refunds, "refunds")
    difference = order_total - (payment_total - refund_total)
    if difference:
        issues.append({"code": "ledger_difference", "path": "ledger"})
    return {
        "ok": True,
        "status": "approved" if not issues else "rejected",
        "summary": f"匿名账本已只读核对：订单、支付减退款差额 {difference} 分，{len(issues)} 个阻塞项；未访问支付渠道或改账。",
        "totals": {
            "orders_cents": order_total,
            "payments_cents": payment_total,
            "refunds_cents": refund_total,
            "difference_cents": difference,
        },
        "issues": issues,
        "reconciled": not issues,
        "evidence": [
            "input.ledger.orders",
            "input.ledger.payments",
            "input.ledger.refunds",
        ],
        "read_only": True,
        "side_effects": [],
    }


def _failed(message: str, code: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "failed",
        "summary": message,
        "error_code": code,
        "evidence": [],
        "read_only": True,
        "side_effects": [],
    }
