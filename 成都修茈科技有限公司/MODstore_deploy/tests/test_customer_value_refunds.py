"""Native refund HTTP reads, original reconciliation and append-only order evidence."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from modstore_server import customer_value_payment_source as source
from modstore_server import customer_value_reconciler as reconciler
from modstore_server.customer_value_evidence import append_customer_value_receipt
from modstore_server.customer_value_refunds import REFUND_SOURCE, WalletRefundEvidence
from modstore_server.db.customer_value import CustomerValueReceipt


def native_refund_row(*, identity=11, user_id=7, order_no="customer-order-10", now=None):
    at = now or datetime.now(UTC)
    return {
        "verified": True,
        "refund_id": identity,
        "refund_no": f"RF{identity}",
        "order_no": order_no,
        "user_id": user_id,
        "wallet_transaction_id": identity + 10,
        "amount_cents": 2990,
        "currency": "CNY",
        "order_total_amount_cents": 2990,
        "refunded_at": (at - timedelta(minutes=1)).isoformat(),
        "credited_at": (at - timedelta(minutes=2)).isoformat(),
        "paid_at": (at - timedelta(days=1)).isoformat(),
        "order_status": "refunded",
        "payment_provider": "alipay",
        "provider_trade_no": f"alipay-{identity}",
        "payment_environment": "production",
        "provider_test_mode": False,
        "verification": "java_wallet_credit_confirmed",
        "order_subject": "Original purchased service",
        "order_kind": "item",
    }


def install_refund_gateway(monkeypatch, rows, *, at=None):
    """Reusable actual-loader fixture; no test may manufacture the sealed capability."""
    at = at or datetime.now(UTC)
    state = SimpleNamespace(rows=rows, calls=[], mutate=None)
    monkeypatch.setenv("PAYMENT_BACKEND", "java")
    monkeypatch.setenv("MODSTORE_INTERNAL_API_KEY", "isolated-refund-reader")
    monkeypatch.setenv("JAVA_PAYMENT_SERVICE_URL", "http://native-payment")
    monkeypatch.setattr(source, "_JAVA_PAGE_SIZE", 2)
    monkeypatch.setattr(source, "datetime", SimpleNamespace(now=lambda _tz: at))

    def handle(request):
        assert request.url.path == "/api/internal/payment/refund-evidence"
        assert request.headers["X-Internal-Api-Key"] == "isolated-refund-reader"
        state.calls.append(request)
        after, limit = int(request.url.params["after"]), int(request.url.params["limit"])
        ordered = sorted(deepcopy(state.rows), key=lambda item: item["refund_id"])
        page = [row for row in ordered if row["refund_id"] > after][:limit]
        through = ordered[-1]["refund_id"] if ordered else 0
        payload = {
            "ok": True,
            "source": REFUND_SOURCE,
            "as_of": at.isoformat(),
            "through_id": through,
            "total": len(ordered),
            "refunds": page,
            "next_after": (
                page[-1]["refund_id"] if page and page[-1]["refund_id"] < through else None
            ),
        }
        if state.mutate:
            state.mutate(payload, after)
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(
        source,
        "httpx",
        SimpleNamespace(
            Client=lambda **kwargs: httpx.Client(transport=httpx.MockTransport(handle), **kwargs),
            Timeout=httpx.Timeout,
            HTTPError=httpx.HTTPError,
        ),
    )
    monkeypatch.setattr(
        reconciler,
        "load_authoritative_payment_orders",
        lambda *_: {
            "orders": [],
            "source_owner": "java_postgresql_internal_api",
            "source_available": True,
            "source_authoritative": True,
        },
    )
    return state


@pytest.fixture
def ledger(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'native-refunds.sqlite'}")
    CustomerValueReceipt.__table__.create(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


def test_original_reconciler_reads_complete_native_snapshot_and_records_one_order_refund(
    monkeypatch, ledger
):
    at = datetime.now(UTC)
    rows = [native_refund_row(identity=identity, now=at) for identity in (11, 15, 20)]
    gateway = install_refund_gateway(monkeypatch, rows, at=at)
    first = reconciler.reconcile_paid_customer_value(session_factory=ledger, now=at)
    again = reconciler.reconcile_paid_customer_value(
        session_factory=ledger, now=at + timedelta(seconds=1)
    )
    assert first["refunds"]["created"] == 3 and again["refunds"]["existing"] == 3
    assert [int(request.url.params["after"]) for request in gateway.calls] == [0, 15, 0, 15]
    assert gateway.calls[1].url.params["as_of"] == at.isoformat()
    assert gateway.calls[1].url.params["through_id"] == "20"
    with ledger() as db:
        stored = list(db.scalars(select(CustomerValueReceipt)))
        assert len(stored) == 3 and sum(row.amount_cents for row in stored) == 8970
        assert all(
            row.customer_ref == "paid-user:7" and row.customer_goal_id == "" for row in stored
        )
        assert {row.source_event_id for row in stored} == {
            "java-wallet-refund:RF11",
            "java-wallet-refund:RF15",
            "java-wallet-refund:RF20",
        }
        assert all(row.recorded_at == at.replace(tzinfo=None) for row in stored)


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "currency",
        "negative",
        "bool_amount",
        "excess",
        "future",
        "no_timezone",
        "provider",
        "production",
        "pending",
        "owner",
    ],
)
def test_incomplete_or_unrelated_source_never_creates_verified_refund(monkeypatch, ledger, fault):
    at = datetime.now(UTC)
    row = native_refund_row(now=at)
    changes = {
        "currency": ("currency", "USD"),
        "negative": ("amount_cents", -1),
        "bool_amount": ("amount_cents", True),
        "excess": ("amount_cents", 3000),
        "future": ("refunded_at", (at + timedelta(seconds=1)).isoformat()),
        "no_timezone": ("credited_at", at.replace(tzinfo=None).isoformat()),
        "provider": ("payment_provider", "wallet"),
        "production": ("payment_environment", "sandbox"),
        "pending": ("verification", "refund_approved_only"),
        "owner": ("user_id", 0),
    }
    if fault == "missing":
        row.pop("wallet_transaction_id")
    else:
        key, value = changes[fault]
        row[key] = value
    install_refund_gateway(monkeypatch, [row], at=at)
    result = reconciler.reconcile_paid_customer_value(session_factory=ledger, now=at)
    assert result["refunds"]["source_ready"] is False
    with ledger() as db:
        assert db.scalar(select(CustomerValueReceipt.id)) is None


@pytest.mark.parametrize(
    "fault",
    ["partial", "count", "snapshot", "cursor", "duplicate_credit", "future_snapshot", "untrusted"],
)
def test_no_partial_prefix_is_appended_when_native_pagination_is_unverified(
    monkeypatch, ledger, fault
):
    at = datetime.now(UTC)
    rows = [native_refund_row(identity=identity, now=at) for identity in (11, 15, 20)]
    if fault == "duplicate_credit":
        rows[-1]["wallet_transaction_id"] = rows[0]["wallet_transaction_id"]
    gateway = install_refund_gateway(monkeypatch, rows, at=at)

    def mutate(payload, after):
        if fault == "cursor" and after == 0:
            payload["next_after"] = 0
        if not after:
            return
        if fault == "partial":
            payload["refunds"] = []
        elif fault == "count":
            payload["total"] = 4
        elif fault == "snapshot":
            payload["through_id"] = 21
        elif fault == "future_snapshot":
            payload["as_of"] = (at + timedelta(days=1)).isoformat()
        elif fault == "untrusted":
            payload["source"] = "worker_payload"

    gateway.mutate = mutate
    result = reconciler.reconcile_paid_customer_value(session_factory=ledger, now=at)
    assert result["refunds"]["source_ready"] is False
    with ledger() as db:
        assert db.scalar(select(CustomerValueReceipt.id)) is None


@pytest.mark.parametrize(
    "identity,subject",
    [
        ("pytest-order", "Service"),
        ("internal-order", "Service"),
        ("renew_order", "Service"),
        ("customer-order", "测试订单"),
    ],
)
def test_original_test_and_internal_exclusions_remain_per_order(
    monkeypatch, ledger, identity, subject
):
    at = datetime.now(UTC)
    rejected = native_refund_row(now=at, order_no=identity)
    rejected["order_subject"] = subject
    install_refund_gateway(monkeypatch, [rejected, native_refund_row(identity=20, now=at)], at=at)
    result = reconciler.reconcile_paid_customer_value(session_factory=ledger, now=at)
    assert result["refunds"]["source_ready"] is True
    assert result["refunds"]["created"] == result["refunds"]["excluded"] == 1
    with ledger() as db:
        assert len(list(db.scalars(select(CustomerValueReceipt)))) == 1


def test_external_trusted_dictionary_cannot_bypass_original_paid_gate(monkeypatch, ledger):
    at = datetime.now(UTC)
    row = native_refund_row(now=at)
    install_refund_gateway(monkeypatch, [row], at=at)
    proof = source.load_authoritative_wallet_refunds(90)["refunds"][0]
    payload = proof.receipt_payload()
    for forged in (row, {"trusted": True, **row}, SimpleNamespace(receipt_payload=lambda: payload)):
        with pytest.raises(ValueError, match="authenticated ledger reader"):
            append_customer_value_receipt(payload, refund_evidence=forged, session_factory=ledger)
    with pytest.raises(ValueError, match="authenticated ledger reader"):
        WalletRefundEvidence("{}", object())
    changed = {**payload, "customer_ref": "paid-user:99"}
    with pytest.raises(ValueError, match="differs"):
        append_customer_value_receipt(changed, refund_evidence=proof, session_factory=ledger)
    with pytest.raises(ValueError, match="order is not verified"):
        append_customer_value_receipt(
            {**payload, "customer_goal_id": "original-goal"},
            payment_order={"status": "refunded"},
            session_factory=ledger,
        )


def test_concurrent_reconciliation_and_changed_native_credit_cannot_double_count(
    monkeypatch, ledger
):
    at = datetime.now(UTC)
    row = native_refund_row(now=at)
    gateway = install_refund_gateway(monkeypatch, [row], at=at)
    proof = source.load_authoritative_wallet_refunds(90)["refunds"][0]

    def append(_):
        return append_customer_value_receipt(
            proof.receipt_payload(), refund_evidence=proof, session_factory=ledger, now=at
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(append, range(2)))
    assert sum(result["created"] for result in results) == 1
    gateway.rows[0]["amount_cents"] = 1000
    changed = source.load_authoritative_wallet_refunds(90)["refunds"][0]
    with pytest.raises(ValueError, match="conflicts"):
        append_customer_value_receipt(
            changed.receipt_payload(), refund_evidence=changed, session_factory=ledger, now=at
        )
    with ledger() as db:
        stored = list(db.scalars(select(CustomerValueReceipt)))
        assert len(stored) == 1 and stored[0].amount_cents == 2990


def test_unknown_native_row_does_not_become_a_zero_refund_or_hide_other_credit(monkeypatch, ledger):
    at = datetime.now(UTC)
    install_refund_gateway(
        monkeypatch,
        [
            {"refund_id": 11, "verified": False, "reason": "incomplete"},
            native_refund_row(identity=20, now=at),
        ],
        at=at,
    )
    result = reconciler.reconcile_paid_customer_value(session_factory=ledger, now=at)
    assert result["refunds"]["created"] == result["refunds"]["unknown"] == 1
