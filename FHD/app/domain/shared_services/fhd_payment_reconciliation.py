"""FHD 支付订单对账区间快照（MODstore reconciliation 合并用）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

STALE_PENDING = timedelta(hours=24)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _anomaly(order: dict[str, Any], end: datetime) -> str | None:
    status = order.get("status")
    if status == "paid" and not (order.get("trade_no") and order.get("paid_at")):
        return "已标记支付但缺少支付宝交易号或支付时间"
    created = _parse_dt(order.get("created_at"))
    if status == "pending_payment" and created and end - _aware(created) > STALE_PENDING:
        return "待支付超过 24 小时仍未关闭"
    return None


def compute_fhd_period_snapshot(start: datetime, end: datetime) -> dict[str, Any]:
    """汇总创建时间落在 [start, end) 的本地订单：按状态计数与金额，并列出需人工核对的异常单。"""
    from app.infrastructure.payment.order_store import list_orders

    start, end = _aware(start), _aware(end)
    rows = []
    for order in list_orders():
        created = _parse_dt(order.get("created_at"))
        if created and start <= _aware(created) < end:
            rows.append(order)
    totals: dict[str, dict[str, int]] = {}
    anomalies = []
    for order in rows:
        bucket = totals.setdefault(
            str(order.get("status") or "unknown"), {"count": 0, "amount_cents": 0}
        )
        bucket["count"] += 1
        bucket["amount_cents"] += int(order.get("amount_cents") or 0)
        if issue := _anomaly(order, end):
            anomalies.append({"out_trade_no": order.get("out_trade_no"), "issue": issue})
    keys = (
        "out_trade_no",
        "plan_id",
        "status",
        "amount_cents",
        "trade_no",
        "created_at",
        "paid_at",
    )
    return {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "orders": [{k: order.get(k) for k in keys} for order in rows],
        "totals": totals,
        "anomalies": anomalies,
    }
