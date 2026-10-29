"""A02: synthetic funds, real SQL transactions, no payment-provider requests."""

from __future__ import annotations

import multiprocessing as mp
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from modstore_server import models, payment_orders
from modstore_server.payment_fulfilment import fulfill_order_atomic


def paid_order(**changes):
    return dict(
        {
            "out_trade_no": "AUDIT-ATOMIC",
            "status": "paid",
            "user_id": 991,
            "total_amount": "5.00",
            "order_kind": "wallet",
            "fulfilled": False,
        },
        **changes,
    )


@pytest.fixture
def database(tmp_path):
    url = "sqlite:///" + str(tmp_path / "payment.sqlite")
    engine = create_engine(url, connect_args={"timeout": 30})
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as session:
        session.add(
            models.User(
                id=991,
                username="synthetic-audit",
                email="audit@example.invalid",
                password_hash="unused",
            )
        )
        session.add(models.Wallet(user_id=991, balance=Decimal("8.00")))
    yield url, engine, factory
    engine.dispose()


def values(factory):
    with factory() as session:
        return (
            session.query(models.Wallet).filter_by(user_id=991).one().balance,
            session.query(models.Transaction).count(),
            session.query(models.PaymentFulfilmentReceipt).count(),
        )


def test_sql_commit_failure_rolls_back_effects_and_receipt(database):
    _, engine, factory = database

    class FailBeforeCommit(Session):
        def commit(self):
            raise RuntimeError("synthetic commit failure")

    with pytest.raises(RuntimeError):
        fulfill_order_atomic(
            "AUDIT-ATOMIC",
            paid_order(),
            sessionmaker(bind=engine, class_=FailBeforeCommit),
        )
    assert values(factory) == (Decimal("8.00"), 0, 0)
    fulfill_order_atomic("AUDIT-ATOMIC", paid_order(), factory)
    assert values(factory) == (Decimal("13.00"), 1, 1)


def test_commit_ack_lost_replay_uses_committed_receipt(database):
    _, engine, factory = database

    class FailAfterCommit(Session):
        def commit(self):
            super().commit()
            raise RuntimeError("synthetic lost commit acknowledgement")

    with pytest.raises(RuntimeError):
        fulfill_order_atomic(
            "AUDIT-ATOMIC",
            paid_order(),
            sessionmaker(bind=engine, class_=FailAfterCommit),
        )
    fulfill_order_atomic("AUDIT-ATOMIC", paid_order(), factory)
    assert values(factory) == (Decimal("13.00"), 1, 1)


@pytest.mark.parametrize("failure", [False, OSError("synthetic projection failure")])
def test_actual_route_projection_failure_cannot_credit_twice(
    database, monkeypatch, tmp_path, failure
):
    from modstore_server import cache

    with patch.object(models, "init_db"), patch.object(cache, "delete"):
        from modstore_server.api import payment_routes
    monkeypatch.setenv("PAYMENT_BACKEND", "python")
    monkeypatch.setenv("MODSTORE_PAYMENT_ORDERS_DIR", str(tmp_path / "orders"))
    payment_orders.create(
        out_trade_no="AUDIT-ATOMIC",
        subject="synthetic",
        total_amount="5.00",
        user_id=991,
        order_kind="wallet",
    )
    assert payment_orders.update_status(out_trade_no="AUDIT-ATOMIC", status="paid")
    monkeypatch.setattr(models, "get_session_factory", lambda: database[2])
    with patch.object(
        payment_orders,
        "merge_fields",
        **(
            {"side_effect": failure}
            if isinstance(failure, Exception)
            else {"return_value": failure}
        ),
    ):
        if isinstance(failure, Exception):
            with pytest.raises(OSError):
                payment_routes._fulfill_paid_order("AUDIT-ATOMIC")
        else:
            payment_routes._fulfill_paid_order("AUDIT-ATOMIC")
    assert payment_orders.find("AUDIT-ATOMIC")["fulfilled"] is False
    payment_routes._fulfill_paid_order("AUDIT-ATOMIC")
    assert payment_orders.find("AUDIT-ATOMIC")["fulfilled"] is True
    assert values(database[2]) == (Decimal("13.00"), 1, 1)


def _repeat_worker(url, barrier, results):
    engine = create_engine(url, connect_args={"timeout": 30})
    factory = sessionmaker(bind=engine)
    barrier.wait(timeout=15)
    for _ in range(20):
        fulfill_order_atomic("AUDIT-ATOMIC", paid_order(), factory)
    results.put("done")
    engine.dispose()


def test_two_independent_workers_forty_replays_credit_once(database):
    context = mp.get_context("spawn")
    barrier, results = context.Barrier(2), context.Queue()
    workers = [
        context.Process(target=_repeat_worker, args=(database[0], barrier, results))
        for _ in range(2)
    ]
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(25)
            assert worker.exitcode == 0
        assert [results.get(timeout=2) for _ in workers] == ["done", "done"]
        assert values(database[2]) == (Decimal("13.00"), 1, 1)
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(5)
        results.close()


def test_reused_order_with_different_payload_is_rejected(database):
    factory = database[2]
    fulfill_order_atomic("AUDIT-ATOMIC", paid_order(), factory)
    with pytest.raises(ValueError, match="different payload"):
        fulfill_order_atomic("AUDIT-ATOMIC", paid_order(total_amount="50.00"), factory)
    assert values(factory) == (Decimal("13.00"), 1, 1)


def test_legacy_json_success_without_ledger_is_not_silently_passed(database):
    with pytest.raises(ValueError, match="reconciliation"):
        fulfill_order_atomic("AUDIT-ATOMIC", paid_order(fulfilled=True), database[2])
    assert values(database[2]) == (Decimal("8.00"), 0, 0)


def test_legacy_wallet_marker_is_adopted_without_second_credit(database):
    factory = database[2]
    with factory.begin() as session:
        session.add(
            models.Transaction(
                user_id=991,
                amount=Decimal("5.00"),
                txn_type="alipay_wallet",
                status="completed",
                description="钱包充值 (订单 AUDIT-ATOMIC)",
            )
        )
    fulfill_order_atomic("AUDIT-ATOMIC", paid_order(fulfilled=True), factory)
    assert values(factory) == (Decimal("8.00"), 1, 1)


@pytest.mark.parametrize(
    "change",
    [
        {"status": "pending"},
        {"total_amount": "NaN"},
        {"total_amount": "Infinity"},
        {"total_amount": "-1"},
        {"total_amount": "0.001"},
        {"user_id": 992},
        {"item_id": 1234},
        {"plan_id": "nonexistent", "order_kind": "plan"},
    ],
)
def test_invalid_or_missing_business_input_never_leaves_a_receipt(database, change):
    with pytest.raises(ValueError):
        fulfill_order_atomic("AUDIT-ATOMIC", paid_order(**change), database[2])
    assert values(database[2]) == (Decimal("8.00"), 0, 0)
