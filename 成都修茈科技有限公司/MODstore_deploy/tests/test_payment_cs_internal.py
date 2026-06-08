"""payment_cs_internal · 客服支付核对（Python JSON SoT）。"""

from __future__ import annotations

from modstore_server import payment_orders
from modstore_server.payment_cs_internal import find_matching_paid_order, payment_summary_for_cs


def test_payment_summary_python_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_PAYMENT_ORDERS_DIR", str(tmp_path / "orders"))
    monkeypatch.delenv("PAYMENT_BACKEND", raising=False)
    payment_orders.create(
        out_trade_no="CS-PAID-1",
        subject="定制",
        total_amount="100.00",
        user_id=29,
        order_kind="plan",
    )
    payment_orders.update_status(out_trade_no="CS-PAID-1", status="paid")
    summary = payment_summary_for_cs(29, min_amount_cents=10000)
    assert summary["payment_verified"] is True
    assert summary["matched_order"]["out_trade_no"] == "CS-PAID-1"
    assert summary["source"] == "python_json"


def test_find_by_out_trade_no(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_PAYMENT_ORDERS_DIR", str(tmp_path / "orders"))
    monkeypatch.delenv("PAYMENT_BACKEND", raising=False)
    payment_orders.create(
        out_trade_no="CS-OTN-99",
        subject="x",
        total_amount="50.00",
        user_id=7,
        order_kind="wallet",
    )
    payment_orders.update_status(out_trade_no="CS-OTN-99", status="paid")
    row = find_matching_paid_order(7, expected_out_trade_no="CS-OTN-99")
    assert row is not None
    assert row["out_trade_no"] == "CS-OTN-99"
