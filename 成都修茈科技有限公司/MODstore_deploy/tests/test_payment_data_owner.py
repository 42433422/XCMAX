"""Single source of truth guards for the Python payment JSON store.

Java/PostgreSQL is the authoritative store when ``PAYMENT_BACKEND=java``. The
guards in ``modstore_server/payment_orders.py`` make sure that:

- The periodic order-expiry scheduler does not write to the local JSON store.
- Stray local writes log a warning so we catch silent data bifurcation early.
"""

from __future__ import annotations

import logging

from modstore_server import payment_orders


def test_is_local_source_of_truth_default_python(monkeypatch):
    monkeypatch.delenv("PAYMENT_BACKEND", raising=False)
    assert payment_orders.is_local_source_of_truth() is True


def test_is_local_source_of_truth_false_when_java(monkeypatch):
    monkeypatch.setenv("PAYMENT_BACKEND", "java")
    assert payment_orders.is_local_source_of_truth() is False


def test_is_local_source_of_truth_truthy_for_unknown_backend(monkeypatch):
    monkeypatch.setenv("PAYMENT_BACKEND", "python")
    assert payment_orders.is_local_source_of_truth() is True
    monkeypatch.setenv("PAYMENT_BACKEND", "")
    assert payment_orders.is_local_source_of_truth() is True


def test_close_pending_older_than_short_circuits_in_java_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_PAYMENT_ORDERS_DIR", str(tmp_path / "orders"))
    monkeypatch.delenv("PAYMENT_BACKEND", raising=False)

    payment_orders.create(
        out_trade_no="MOD-PYTEST-EXPIRE-1",
        subject="pytest",
        total_amount="9.90",
        user_id=1,
        order_kind="plan",
        plan_id="plan_basic",
    )

    monkeypatch.setenv("PAYMENT_BACKEND", "java")
    closed = payment_orders.close_pending_older_than(minutes=0)
    assert closed == 0, "Java owns orders; Python must not touch the JSON store"

    order = payment_orders.find("MOD-PYTEST-EXPIRE-1")
    assert order is not None
    assert order["status"] == "pending", "Order status must remain unchanged in Java mode"


def test_close_pending_older_than_runs_in_python_mode(tmp_path, monkeypatch):
    import time

    monkeypatch.setenv("MODSTORE_PAYMENT_ORDERS_DIR", str(tmp_path / "orders"))
    monkeypatch.delenv("PAYMENT_BACKEND", raising=False)

    payment_orders.create(
        out_trade_no="MOD-PYTEST-EXPIRE-2",
        subject="pytest",
        total_amount="9.90",
        user_id=1,
        order_kind="plan",
        plan_id="plan_basic",
    )

    time.sleep(0.01)
    closed = payment_orders.close_pending_older_than(minutes=0)
    assert closed == 1
    order = payment_orders.find("MOD-PYTEST-EXPIRE-2")
    assert order is not None
    assert order["status"] == "closed"


def test_local_write_in_java_mode_is_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_PAYMENT_ORDERS_DIR", str(tmp_path / "orders"))
    monkeypatch.setenv("PAYMENT_BACKEND", "java")

    res = payment_orders.create(
        out_trade_no="MOD-PYTEST-BLOCK",
        subject="pytest",
        total_amount="1.00",
        user_id=1,
        order_kind="wallet",
    )
    assert res["ok"] is False
    assert res.get("code") == "java_sot_readonly"
    assert payment_orders.find("MOD-PYTEST-BLOCK") is None


def test_merge_and_update_blocked_in_java_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_PAYMENT_ORDERS_DIR", str(tmp_path / "orders"))
    monkeypatch.delenv("PAYMENT_BACKEND", raising=False)
    payment_orders.create(
        out_trade_no="MOD-PYTEST-MU",
        subject="pytest",
        total_amount="1.00",
        user_id=1,
        order_kind="wallet",
    )
    monkeypatch.setenv("PAYMENT_BACKEND", "java")
    assert payment_orders.merge_fields("MOD-PYTEST-MU", fulfilled=True) is False
    assert payment_orders.update_status(out_trade_no="MOD-PYTEST-MU", status="paid") is False
    assert payment_orders.find("MOD-PYTEST-MU")["status"] == "pending"


def test_local_write_in_python_mode_does_not_warn(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("MODSTORE_PAYMENT_ORDERS_DIR", str(tmp_path / "orders"))
    monkeypatch.delenv("PAYMENT_BACKEND", raising=False)

    with caplog.at_level(logging.WARNING, logger="modstore_server.payment_orders"):
        payment_orders.create(
            out_trade_no="MOD-PYTEST-OK",
            subject="pytest",
            total_amount="1.00",
            user_id=1,
            order_kind="wallet",
        )

    drift_warnings = [r for r in caplog.records if "PAYMENT_BACKEND=java" in r.message]
    assert drift_warnings == []
