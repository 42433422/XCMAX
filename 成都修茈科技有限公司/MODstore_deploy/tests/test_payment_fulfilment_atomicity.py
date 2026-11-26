"""A02: synthetic funds, real SQL transactions, no payment-provider requests."""

from __future__ import annotations

import multiprocessing as mp
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from modstore_server import models, payment_orders
from modstore_server.account_license_plans import account_license_plan_rows
from modstore_server.account_lifecycle import lifecycle_for_user
from modstore_server.payment_common import SignCheckoutBody, _resolve_checkout_fields
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


@pytest.mark.parametrize("preceding_test_root", [None, "FHD"])
def test_two_independent_workers_forty_replays_credit_once(
    database, monkeypatch, preceding_test_root
):
    modstore_root = Path(__file__).resolve().parents[1]
    if preceding_test_root:
        monkeypatch.syspath_prepend(str(modstore_root.parents[1] / preceding_test_root))
    # spawn reimports the worker by module name; use this project's tests package.
    monkeypatch.syspath_prepend(str(modstore_root))
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


def seed_account_plans(factory):
    with factory.begin() as session:
        session.add_all(models.PlanTemplate(**row) for row in account_license_plan_rows())


@pytest.mark.parametrize(
    "plan_id,amount,allowance",
    [
        ("saas-permanent-standard", "3000.00", 0),
        # Existing standard-license orders retain the locked amount after repricing.
        ("saas-permanent-standard", "6800.00", 0),
        # A previously authorized test/adjusted order keeps its recorded price.
        ("saas-permanent-growth", "0.01", 0),
        ("saas-trial-30", "99.00", 100),
    ],
)
def test_license_snapshot_replays_once_without_crediting_software_price(
    database, plan_id, amount, allowance
):
    factory = database[2]
    seed_account_plans(factory)
    order = paid_order(order_kind="plan", plan_id=plan_id, total_amount=amount)
    for _ in range(3):
        fulfill_order_atomic("AUDIT-ATOMIC", order, factory)
    with factory() as session:
        assert session.query(models.PaymentFulfilmentReceipt).count() == 1
        assert session.query(models.Entitlement).count() == 1
        grant = session.query(models.UserPlan).one()
        assert grant.plan_id == plan_id
        assert (grant.expires_at is not None) == (plan_id == "saas-trial-30")
        access = lifecycle_for_user(session, session.get(models.User, 991))
        assert access.active_plan_id == plan_id
        assert (access.active_plan_expires_at is not None) == (plan_id == "saas-trial-30")
        assert session.query(models.Wallet).one().balance == Decimal(8 + allowance)
        assert session.query(models.UserMod).count() == 0
    changed = dict(order, total_amount=str(Decimal(amount) + 1))
    with pytest.raises(ValueError, match="different payload"):
        fulfill_order_atomic("AUDIT-ATOMIC", changed, factory)


@pytest.mark.parametrize("incoming", ["saas-trial-30", "saas-permanent-standard"])
@pytest.mark.parametrize(
    "previous,tier", [("saas-permanent-starter", "normal"), ("saas-permanent-ultra", "ultra")]
)
def test_inflight_lower_license_preserves_permanent_high_tier(database, incoming, previous, tier):
    factory = database[2]
    seed_account_plans(factory)
    with factory.begin() as session:
        session.add(models.UserPlan(user_id=991, plan_id=previous, is_active=True))
    fulfill_order_atomic(
        "AUDIT-ATOMIC",
        paid_order(order_kind="plan", plan_id=incoming, total_amount="99.00"),
        factory,
    )
    with factory() as session:
        access = lifecycle_for_user(session, session.get(models.User, 991))
        assert (access.active_plan_id, access.account_tier) == (previous, tier)
        assert access.active_plan_expires_at is None
        assert session.query(models.UserPlan).filter_by(plan_id=previous).one().is_active
        with pytest.raises(HTTPException, match="无需重复"):
            _resolve_checkout_fields(session, SignCheckoutBody(plan_id=incoming), user_id=991)


@pytest.mark.parametrize("suffix", ["starter", "growth", "max", "ultra"])
def test_retired_license_rejected_for_new_checkout(database, suffix):
    seed_account_plans(database[2])
    with database[2]() as session, pytest.raises(HTTPException, match="历史套餐不再新售"):
        _resolve_checkout_fields(
            session, SignCheckoutBody(plan_id=f"saas-permanent-{suffix}"), user_id=991
        )


@pytest.mark.parametrize(
    "plan_id,price", [("saas-permanent-standard", 3000), ("saas-trial-30", 99)]
)
def test_checkout_uses_server_catalog_price_not_client_test_amount(database, plan_id, price):
    seed_account_plans(database[2])
    with database[2]() as session:
        fields = _resolve_checkout_fields(
            session, SignCheckoutBody(plan_id=plan_id, total_amount=0.01), user_id=991
        )
    assert fields[1] == price
    assert fields[3:5] == (plan_id, "plan")
