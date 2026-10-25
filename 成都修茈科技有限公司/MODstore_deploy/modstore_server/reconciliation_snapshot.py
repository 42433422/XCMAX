# mypy: disable-error-code="union-attr"
"""Period aggregation and skill payloads for reconciliation APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from modstore_server.models import AuthorEarning, Transaction
from modstore_server.operational_errors import RECOVERABLE_ERRORS


def compute_period_snapshot(
    session: Any,
    period_start: datetime,
    period_end: datetime,
) -> dict[str, Any]:
    """Aggregate payment, wallet, earning and host data without writes."""
    from modstore_server import reconciliation as facade

    all_orders, _ = facade._po.list_orders(status="paid", limit=100_000)
    paid_in_range = []
    refunded_in_range = []
    for order in all_orders:
        raw_ts = order.get("paid_at") or order.get("created_at") or ""
        try:
            ts = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00")).replace(tzinfo=None)
        except RECOVERABLE_ERRORS:
            continue
        if period_start <= ts < period_end:
            paid_in_range.append(order)
        if order.get("refunded"):
            refund_ts_raw = order.get("refunded_at") or order.get("updated_at") or ""
            try:
                refund_ts = datetime.fromisoformat(
                    str(refund_ts_raw).replace("Z", "+00:00")
                ).replace(tzinfo=None)
            except RECOVERABLE_ERRORS:
                refund_ts = ts
            if period_start <= refund_ts < period_end:
                refunded_in_range.append(order)

    trade_numbers = {
        str(order.get("out_trade_no") or "") for order in paid_in_range if order.get("out_trade_no")
    }
    modstore_orders = len(paid_in_range)
    modstore_gmv = sum(float(order.get("total_amount") or 0) for order in paid_in_range)

    fhd_host = facade._fetch_fhd_host_snapshot(period_start, period_end)
    fhd_extra_orders = 0
    fhd_extra_gmv = 0.0
    if fhd_host.get("included"):
        fhd_extra_orders = int(fhd_host.get("total_orders") or 0)
        fhd_extra_gmv = float(fhd_host.get("total_gmv") or 0)
        for sample in fhd_host.get("orders_sample") or []:
            if not isinstance(sample, dict):
                continue
            trade_number = str(sample.get("out_trade_no") or "")
            if trade_number and trade_number in trade_numbers:
                fhd_extra_orders = max(0, fhd_extra_orders - 1)
                try:
                    fhd_extra_gmv = max(
                        0.0,
                        fhd_extra_gmv - float(sample.get("amount_yuan") or 0),
                    )
                except (TypeError, ValueError):
                    pass

    total_orders = modstore_orders + fhd_extra_orders
    total_gmv = modstore_gmv + fhd_extra_gmv
    refunds_count = len(refunded_in_range)
    refunds_amount = sum(float(order.get("total_amount") or 0) for order in refunded_in_range)
    wallet_txns = (
        session.query(Transaction)
        .filter(
            Transaction.txn_type.in_({"alipay_wallet", "alipay_recharge", "wallet"}),
            Transaction.created_at >= period_start,
            Transaction.created_at < period_end,
            Transaction.status == "completed",
        )
        .all()
    )
    wallet_top_ups = sum(
        float(transaction.amount or 0)
        for transaction in wallet_txns
        if (transaction.amount or 0) > 0
    )
    earnings = (
        session.query(AuthorEarning)
        .filter(
            AuthorEarning.created_at >= period_start,
            AuthorEarning.created_at < period_end,
        )
        .all()
    )
    author_payable = sum(float(earning.net or 0) for earning in earnings)
    platform_revenue = sum(
        float(earning.gross or 0) - float(earning.net or 0) for earning in earnings
    )
    return {
        "total_orders": total_orders,
        "total_gmv": round(total_gmv, 2),
        "platform_revenue": round(platform_revenue, 2),
        "author_payable": round(author_payable, 2),
        "refunds_count": refunds_count,
        "refunds_amount": round(refunds_amount, 2),
        "wallet_top_ups": round(wallet_top_ups, 2),
        "alipay_income": round(total_gmv, 2),
        "modstore_payment_orders": {
            "total_orders": modstore_orders,
            "total_gmv": round(modstore_gmv, 2),
        },
        "fhd_host_orders": fhd_host,
    }


def build_skill_payload(
    snap: dict[str, Any],
    *,
    alipay_statement_total_cny: Optional[float],
    previous: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Build the payment-reconcile skill contract and Markdown summary."""
    total_orders = int(snap["total_orders"])
    local_book_total = round(float(snap["alipay_income"]) + float(snap["wallet_top_ups"]), 2)
    diff_amount = 0.0
    diff_count = 0
    matched = total_orders
    status = "ok"
    if alipay_statement_total_cny is not None:
        diff_amount = round(local_book_total - float(alipay_statement_total_cny), 2)
        if abs(diff_amount) > 0.01:
            status = "warning"
            diff_count = 1
            matched = max(total_orders - 1, 0)

    history: Optional[dict[str, Any]] = None
    if previous:
        previous_gmv = float(previous.get("total_gmv") or 0)
        current_gmv = float(snap["total_gmv"])
        delta = round(current_gmv - previous_gmv, 2)
        history = {
            "previous_report_id": previous.get("id"),
            "previous_period_end": previous.get("period_end"),
            "total_gmv_delta_cny": delta,
            "total_gmv_delta_pct": (
                round(100.0 * delta / previous_gmv, 2) if previous_gmv > 0 else None
            ),
        }

    fhd = snap.get("fhd_host_orders") if isinstance(snap.get("fhd_host_orders"), dict) else {}
    modstore = (
        snap.get("modstore_payment_orders")
        if isinstance(snap.get("modstore_payment_orders"), dict)
        else {}
    )
    lines = [
        "## 支付对账预览（只读）",
        "",
        f"- 区间订单数（已支付，含 FHD 宿主）: {total_orders}",
        f"- MODstore payment_orders: {modstore.get('total_orders', '—')} 笔 / {modstore.get('total_gmv', '—')} CNY",
    ]
    if fhd.get("included"):
        lines.append(
            f"- FHD 宿主（PG/JSON）: {fhd.get('total_orders', 0)} 笔 / "
            f"{float(fhd.get('total_gmv') or 0):.2f} CNY"
        )
    else:
        lines.append(f"- FHD 宿主: 未并入（{fhd.get('reason', 'n/a')}）")
    lines.extend(
        [
            f"- 合并 GMV: {snap['total_gmv']:.2f} CNY",
            f"- 钱包充值（Transaction 汇总）: {snap['wallet_top_ups']:.2f} CNY",
            f"- 本地账面收入粗算（GMV+钱包充值）: {local_book_total:.2f} CNY",
            f"- 平台收益 / 作者应付: {snap['platform_revenue']:.2f} / {snap['author_payable']:.2f} CNY",
        ]
    )
    if alipay_statement_total_cny is not None:
        lines.extend(
            [
                f"- RPA 传入支付宝账单汇总: {alipay_statement_total_cny:.2f} CNY",
                f"- 差额（本地粗算 − 账单）: {diff_amount:.2f} CNY",
            ]
        )
    else:
        lines.append("- 未提供 `alipay_statement_total_cny`：未与支付宝侧总额对碰。")
    if history:
        percent = history.get("total_gmv_delta_pct")
        lines.extend(
            [
                "",
                "### 相对上一段已确认报告",
                f"- 上一报告 ID: {history.get('previous_report_id')}",
                f"- GMV 变动: {history.get('total_gmv_delta_cny')} CNY"
                + (f" ({percent}%)" if percent is not None else ""),
            ]
        )
    lines.extend(
        [
            "",
            "### 趋势与归因（LLM）",
            "> 由 `payment-billing-reconciler` 动态阶段基于差异明细生成；本接口仅预留章节。",
        ]
    )
    return {
        "status": status,
        "total_orders": total_orders,
        "matched": matched,
        "diff_count": diff_count,
        "diff_amount_cny": diff_amount,
        "report_md": "\n".join(lines),
        "platform_snapshot": snap,
        "local_book_total_cny": local_book_total,
        "history_vs_previous_period": history,
        "llm_narrative": None,
        "doc_archive_hint": "提交 `doc-knowledge-curator`：将定稿 `report_md` 归档至 MODstore docs/runbooks/ 或内部知识库（勿含密钥）。",
    }
