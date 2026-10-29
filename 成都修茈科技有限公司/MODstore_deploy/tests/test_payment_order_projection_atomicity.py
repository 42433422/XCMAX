"""A02: real file-store concurrency and interrupted replacement, synthetic orders."""

import multiprocessing as mp
import os
from pathlib import Path

import pytest

from modstore_server import payment_orders as orders


@pytest.fixture(autouse=True)
def local_store(monkeypatch, tmp_path):
    monkeypatch.setenv("PAYMENT_BACKEND", "python")
    monkeypatch.setenv("MODSTORE_PAYMENT_ORDERS_DIR", str(tmp_path / "orders"))


def create():
    return orders.create(
        out_trade_no="AUDIT-LOCAL", subject="synthetic", total_amount="5.00", user_id=1
    )


@pytest.mark.parametrize("operation", ["create", "merge_fields", "update_status"])
@pytest.mark.parametrize("boundary", ["lock", "filesystem"])
def test_java_mode_rejects_before_local_storage_access(monkeypatch, tmp_path, operation, boundary):
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("retained local file", encoding="utf-8")
    monkeypatch.setenv("MODSTORE_PAYMENT_ORDERS_DIR", str(blocked / "orders"))
    monkeypatch.setenv("PAYMENT_BACKEND", "java")
    if boundary == "lock":

        def forbidden_lock(_order_no):
            raise AssertionError("Java-owned orders must not acquire a local file lock")

        monkeypatch.setattr(orders, "_order_lock", forbidden_lock)
    if operation == "create":
        result = create()
        assert result["ok"] is False
        assert result["code"] == "java_sot_readonly"
    elif operation == "merge_fields":
        assert orders.merge_fields("AUDIT-LOCAL", fulfilled=True) is False
    else:
        assert orders.update_status(out_trade_no="AUDIT-LOCAL", status="paid") is False
    assert blocked.read_text(encoding="utf-8") == "retained local file"


def _mutate_worker(root, barrier, operation):
    os.environ["MODSTORE_PAYMENT_ORDERS_DIR"] = root
    os.environ["PAYMENT_BACKEND"] = "python"
    barrier.wait(timeout=10)
    for _ in range(20):
        if operation == "status":
            assert orders.update_status(out_trade_no="AUDIT-LOCAL", status="paid")
        else:
            assert orders.merge_fields("AUDIT-LOCAL", fulfilled=True)


def test_concurrent_projection_writes_preserve_payment_status_and_receipt():
    create()
    context = mp.get_context("spawn")
    barrier = context.Barrier(2)
    workers = [
        context.Process(
            target=_mutate_worker,
            args=(os.environ["MODSTORE_PAYMENT_ORDERS_DIR"], barrier, operation),
        )
        for operation in ("status", "fulfilled")
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(15)
        assert worker.exitcode == 0
    doc = orders.find("AUDIT-LOCAL")
    assert doc["status"] == "paid" and doc["fulfilled"] is True
    assert doc["notify_count"] == 20


def test_failed_replace_keeps_previous_document_and_removes_temp(monkeypatch):
    create()
    before = orders.find("AUDIT-LOCAL")

    def fail(*args):
        raise OSError("synthetic rename failure")

    monkeypatch.setattr(orders.os, "replace", fail)
    assert not orders.merge_fields("AUDIT-LOCAL", fulfilled=True)
    assert orders.find("AUDIT-LOCAL") == before
    assert not list(Path(os.environ["MODSTORE_PAYMENT_ORDERS_DIR"]).glob("*.tmp"))


def test_scheduler_does_not_close_confirmed_payment():
    create()
    orders.update_status(out_trade_no="AUDIT-LOCAL", status="paid")
    assert orders.close_pending_older_than(minutes=0) == 0
    assert orders.find("AUDIT-LOCAL")["status"] == "paid"
