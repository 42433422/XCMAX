"""Period reconciliation over the local model-payment order store."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.services import reconciliation_scheduler as scheduler
from app.services.fhd_payment_reconciliation import _parse_dt, compute_fhd_period_snapshot

NOW = datetime.now(UTC)


def _order(no: str, status: str, created: datetime, **extra) -> dict:
    return {
        "out_trade_no": no,
        "status": status,
        "amount_cents": 990,
        "created_at": created.isoformat(),
        **extra,
    }


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "model_payment_orders.json"
    monkeypatch.setenv("MODEL_PAYMENT_ORDER_STORE_PATH", str(path))
    orders = [
        _order("ok", "paid", NOW - timedelta(hours=2), trade_no="T1", paid_at=NOW.isoformat()),
        _order("no-trade", "paid", NOW - timedelta(hours=3)),
        _order("stale", "pending_payment", NOW - timedelta(hours=30)),
        _order("fresh", "pending_payment", NOW - timedelta(minutes=5)),
        _order("old", "paid", NOW - timedelta(days=9), trade_no="T0", paid_at=NOW.isoformat()),
    ]
    path.write_text(
        json.dumps({"orders": {o["out_trade_no"]: o for o in orders}}), encoding="utf-8"
    )
    return path


def test_parse_dt_accepts_utc_suffix_and_rejects_garbage() -> None:
    assert _parse_dt("2026-01-15T10:30:00Z") == datetime(2026, 1, 15, 10, 30, tzinfo=UTC)
    assert _parse_dt("not-a-date") is None and _parse_dt(None) is None


def test_snapshot_totals_period_orders_and_flags_anomalies(store) -> None:
    snap = compute_fhd_period_snapshot(NOW - timedelta(days=2), NOW)
    assert {o["out_trade_no"] for o in snap["orders"]} == {"ok", "no-trade", "stale", "fresh"}
    assert snap["totals"] == {
        "paid": {"count": 2, "amount_cents": 1980},
        "pending_payment": {"count": 2, "amount_cents": 1980},
    }
    assert {a["out_trade_no"] for a in snap["anomalies"]} == {"no-trade", "stale"}


def test_full_cycle_persists_last_run_and_next_cycle_starts_from_it(store) -> None:
    assert scheduler.get_reconciliation_status()["last_run"] is None
    preview = scheduler.run_reconciliation_preview_cycle()
    assert preview["preview"] and preview["dry_run"] and preview["order_count"] == 3
    assert scheduler.get_reconciliation_status()["last_run"] is None

    first = scheduler.run_reconciliation_full_cycle()
    assert first["dry_run"] is False and first["order_count"] == 3
    assert scheduler.get_reconciliation_status()["last_run"]["period_end"] == first["period_end"]
    second = scheduler.run_reconciliation_full_cycle()
    assert second["period_start"] == first["period_end"] and second["order_count"] == 0
