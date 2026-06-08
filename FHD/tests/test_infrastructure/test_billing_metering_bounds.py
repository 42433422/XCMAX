"""Tests for app.infrastructure.billing.metering — coverage ramp C3.3-b.

Covers:
* ``MeteringRecord.as_dict`` serialization.
* ``record_usage`` happy / dedup / negative amount / huge amount.
* ``reconcile`` aggregation by backend/mode/currency.
* ``_route_to_backend`` for postgres / modstore / json.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from app.infrastructure.billing.metering import (
    MeteringRecord,
    _route_to_backend,
    reconcile,
    record_usage,
)


def _rec(amount="1.00", **kw) -> MeteringRecord:
    defaults = {
        "tenant_id": "t1",
        "sku": "plan-pro",
        "mode": "subscription",
        "amount": Decimal(amount),
        "currency": "CNY",
    }
    defaults.update(kw)
    return MeteringRecord(**defaults)


class TestAsDict:
    def test_basic_fields(self) -> None:
        r = _rec()
        d = r.as_dict()
        assert d["tenant_id"] == "t1"
        assert d["sku"] == "plan-pro"
        assert d["mode"] == "subscription"
        assert d["amount"] == 1.0
        assert d["currency"] == "CNY"
        assert "ts" in d
        assert d["meta"] == {}

    def test_amount_is_float(self) -> None:
        r = _rec("3.14")
        assert r.as_dict()["amount"] == 3.14


class TestRecordUsage:
    def test_basic_record(self) -> None:
        r = _rec()
        with patch(
            "app.infrastructure.billing.metering._route_to_backend",
            return_value={"routed": "json_legacy"},
        ):
            out = record_usage(r)
        assert out["success"] is True
        assert out["deduped"] is False

    def test_idempotent_dedup(self) -> None:
        r = _rec(idempotency_key="k1")
        with patch(
            "app.infrastructure.billing.metering._route_to_backend",
            return_value={"routed": "json_legacy"},
        ):
            out1 = record_usage(r)
            out2 = record_usage(r)
        assert out1["deduped"] is False
        assert out2["deduped"] is True

    def test_huge_amount_serialized(self) -> None:
        r = _rec("1E+15")
        with patch(
            "app.infrastructure.billing.metering._route_to_backend",
            return_value={"routed": "json_legacy"},
        ):
            out = record_usage(r)
        assert out["success"] is True
        assert r.as_dict()["amount"] == 1e15

    def test_negative_amount_passes(self) -> None:
        # Negative is allowed for refund / adjustment records
        r = _rec("-5.00", mode="refund")
        with patch(
            "app.infrastructure.billing.metering._route_to_backend",
            return_value={"routed": "json_legacy"},
        ):
            out = record_usage(r)
        assert out["success"] is True


class TestRouteToBackend:
    def test_postgres_routes(self) -> None:
        out = _route_to_backend("postgres", _rec())
        assert out["routed"] == "fhd_postgres"

    def test_modstore_routes(self) -> None:
        with patch(
            "app.infrastructure.payment.modstore_payment_proxy.record_market_metering"
        ) as rm:
            out = _route_to_backend("modstore", _rec())
        rm.assert_called_once()
        assert out["routed"] == "modstore_wallet"

    def test_modstore_proxy_failure_defers(self) -> None:
        with patch(
            "app.infrastructure.payment.modstore_payment_proxy.record_market_metering",
            side_effect=Exception("proxy down"),
        ):
            out = _route_to_backend("modstore", _rec())
        assert out["routed"] == "modstore_wallet"
        assert out["deferred"] is True

    def test_json_legacy(self) -> None:
        out = _route_to_backend("json", _rec())
        assert out["routed"] == "json_legacy"


class TestReconcile:
    def test_aggregates_by_key(self) -> None:
        records = [
            _rec("10.00", mode="subscription"),
            _rec("20.00", mode="subscription"),
            _rec("5.00", mode="usage", sku="api-call"),
        ]
        with patch("app.infrastructure.billing.metering._resolve_backend", return_value="json"):
            out = reconcile(records)
        assert out["success"] is True
        assert out["total_records"] == 3
        assert "json|subscription|CNY" in out["buckets"]
        assert "json|usage|CNY" in out["buckets"]
        sub_bucket = out["buckets"]["json|subscription|CNY"]
        assert sub_bucket["count"] == 2
        assert sub_bucket["amount"] == 30.0

    def test_empty_records(self) -> None:
        out = reconcile([])
        assert out["total_records"] == 0
        assert out["buckets"] == {}
