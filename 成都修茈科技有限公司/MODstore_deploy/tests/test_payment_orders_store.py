"""Edge case tests for the local payment_orders JSON store.

These complement ``test_payment_data_owner.py`` (which covers the source-of-
truth guards) by exercising read paths and corrupt-input handling so the
critical-modules coverage gate stays above 80%.
"""

from __future__ import annotations

import json
import logging

import pytest

from modstore_server import payment_orders


@pytest.fixture(autouse=True)
def _isolate_orders_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_PAYMENT_ORDERS_DIR", str(tmp_path / "orders"))
    monkeypatch.delenv("PAYMENT_BACKEND", raising=False)
    yield


def test_create_returns_existing_message_on_duplicate():
    res = payment_orders.create(
        out_trade_no="DUP1", subject="x", total_amount="1.00", user_id=1, order_kind="wallet"
    )
    assert res["ok"] is True
    again = payment_orders.create(
        out_trade_no="DUP1", subject="x", total_amount="1.00", user_id=1, order_kind="wallet"
    )
    assert again["ok"] is False
    assert "DUP1" in again["message"]


def test_find_returns_none_for_missing():
    assert payment_orders.find("MISSING") is None


def test_find_returns_none_for_corrupt_json(tmp_path):
    target = payment_orders._path("CORRUPT")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{not-json", encoding="utf-8")
    assert payment_orders.find("CORRUPT") is None


def test_merge_fields_returns_false_for_missing_order():
    assert payment_orders.merge_fields("NO-SUCH", refunded=True) is False


def test_merge_fields_skips_none_values():
    payment_orders.create(
        out_trade_no="MERGE-NONE", subject="x", total_amount="1.00", user_id=1, order_kind="wallet"
    )
    assert payment_orders.merge_fields("MERGE-NONE", refunded=True, qr_code=None) is True
    doc = payment_orders.find("MERGE-NONE")
    assert doc["refunded"] is True
    # qr_code default value preserved (None)
    assert doc["qr_code"] is None


def test_update_status_increments_notify_count_and_writes_metadata():
    payment_orders.create(
        out_trade_no="USTAT-1", subject="x", total_amount="1.00", user_id=1, order_kind="wallet"
    )
    assert (
        payment_orders.update_status(
            out_trade_no="USTAT-1", status="paid", trade_no="T", buyer_id="B", paid_at="2026"
        )
        is True
    )
    doc = payment_orders.find("USTAT-1")
    assert doc["status"] == "paid"
    assert doc["trade_no"] == "T"
    assert doc["buyer_id"] == "B"
    assert doc["paid_at"] == "2026"
    assert doc["notify_count"] == 1


def test_update_status_returns_false_for_missing():
    assert payment_orders.update_status(out_trade_no="GHOST", status="paid") is False


def test_list_orders_filters_by_user_and_status():
    for n in range(3):
        payment_orders.create(
            out_trade_no=f"L-{n}", subject="x", total_amount="1.00", user_id=42, order_kind="wallet"
        )
    payment_orders.create(
        out_trade_no="L-other", subject="x", total_amount="1.00", user_id=99, order_kind="wallet"
    )
    payment_orders.update_status(out_trade_no="L-0", status="paid")

    rows, total = payment_orders.list_orders(user_id=42, limit=10)
    assert total == 3
    assert all(row["user_id"] == 42 for row in rows)

    rows_paid, total_paid = payment_orders.list_orders(user_id=42, status="paid", limit=10)
    assert total_paid == 1
    assert rows_paid[0]["out_trade_no"] == "L-0"


def test_list_orders_skips_corrupt_files(tmp_path):
    payment_orders.create(
        out_trade_no="GOOD", subject="x", total_amount="1.00", user_id=7, order_kind="wallet"
    )
    bad = payment_orders._path("BAD")
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{nope", encoding="utf-8")

    rows, total = payment_orders.list_orders(user_id=7, limit=10)
    assert total == 1
    assert rows[0]["out_trade_no"] == "GOOD"


def test_close_pending_older_than_skips_active_status(tmp_path):
    import time

    payment_orders.create(
        out_trade_no="ACT-PAID", subject="x", total_amount="1.00", user_id=1, order_kind="wallet"
    )
    payment_orders.update_status(out_trade_no="ACT-PAID", status="paid")
    payment_orders.create(
        out_trade_no="ACT-PEND", subject="x", total_amount="1.00", user_id=1, order_kind="wallet"
    )
    time.sleep(0.01)
    closed = payment_orders.close_pending_older_than(minutes=0)
    assert closed == 1
    assert payment_orders.find("ACT-PAID")["status"] == "paid"
    assert payment_orders.find("ACT-PEND")["status"] == "closed"


def test_close_pending_older_than_handles_corrupt_and_missing_timestamp(tmp_path):
    p_corrupt = payment_orders._path("CORRUPT")
    p_corrupt.parent.mkdir(parents=True, exist_ok=True)
    p_corrupt.write_text("{nope", encoding="utf-8")

    no_ts = payment_orders._path("NO-TS")
    no_ts.write_text(
        json.dumps({"out_trade_no": "NO-TS", "status": "pending"}),
        encoding="utf-8",
    )

    bad_ts = payment_orders._path("BAD-TS")
    bad_ts.write_text(
        json.dumps({"out_trade_no": "BAD-TS", "status": "pending", "created_at": "not-a-date"}),
        encoding="utf-8",
    )

    too_recent = payment_orders._path("RECENT")
    too_recent.write_text(
        json.dumps(
            {
                "out_trade_no": "RECENT",
                "status": "pending",
                "created_at": "2999-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    closed = payment_orders.close_pending_older_than(minutes=0)
    assert closed == 0
