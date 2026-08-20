from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.application import monthly_report_scheduler


class _AggregateQuery:
    def __init__(self, rows: list[tuple[Any, ...]]):
        self.rows = rows
        self.filter_calls = 0

    def filter(self, *_args: Any) -> _AggregateQuery:
        self.filter_calls += 1
        return self

    def group_by(self, *_args: Any) -> _AggregateQuery:
        return self

    def all(self) -> list[tuple[Any, ...]]:
        return self.rows


class _AggregateDb:
    def __init__(self, queries: list[_AggregateQuery]):
        self.queries = iter(queries)

    def query(self, *_args: Any) -> _AggregateQuery:
        return next(self.queries)


def _db_context(db: Any):
    @contextmanager
    def _manager():
        yield db

    return _manager()


def test_month_range_validates_and_crosses_year_boundary() -> None:
    with pytest.raises(ValueError, match="非法月份"):
        monthly_report_scheduler._month_range(2026, 0)
    with pytest.raises(ValueError, match="非法月份"):
        monthly_report_scheduler._month_range(2026, 13)
    assert monthly_report_scheduler._month_range(2026, 2) == (
        date(2026, 2, 1),
        date(2026, 3, 1),
    )
    assert monthly_report_scheduler._month_range(2026, 12) == (
        date(2026, 12, 1),
        date(2027, 1, 1),
    )


def test_generate_monthly_summary_aggregates_all_dimensions() -> None:
    inbound = _AggregateQuery([("approved", 2, 10), ("rejected", 1, 5), (None, None, None)])
    approvals = _AggregateQuery([("approved", 2), (None, None)])
    transactions = _AggregateQuery([("sale", 3, 7.5), (None, None, None)])
    db = _AggregateDb([inbound, approvals, transactions])

    with patch("app.db.session.get_db", return_value=_db_context(db)):
        result = monthly_report_scheduler.generate_monthly_finance_summary(7, 2026, 2)

    assert result["success"] is True
    assert result["period"]["start_date"] == "2026-02-01"
    assert result["period"]["end_date"] == "2026-02-28"
    assert result["summary"] == {
        "total_inbound_amount": 15.0,
        "total_inbound_count": 3,
        "total_approved_count": 2,
        "total_rejected_count": 1,
        "total_approval_count": 2,
        "total_transaction_amount": 7.5,
        "total_transaction_count": 3,
        "by_inbound_status": {
            "approved": {"count": 2, "amount": 10.0},
            "rejected": {"count": 1, "amount": 5.0},
            "unknown": {"count": 0, "amount": 0.0},
        },
        "by_transaction_type": {
            "sale": {"count": 3, "amount": 7.5},
            "unknown": {"count": 0, "amount": 0.0},
        },
    }
    assert inbound.filter_calls == approvals.filter_calls == transactions.filter_calls == 2


def test_generate_monthly_summary_without_tenant_and_query_failure() -> None:
    queries = [_AggregateQuery([]), _AggregateQuery([]), _AggregateQuery([])]
    with patch("app.db.session.get_db", return_value=_db_context(_AggregateDb(queries))):
        result = monthly_report_scheduler.generate_monthly_finance_summary(None, 2026, 1)
    assert result["success"] is True
    assert all(query.filter_calls == 1 for query in queries)

    @contextmanager
    def _failed_db():
        raise RuntimeError("database down")
        yield

    with patch("app.db.session.get_db", return_value=_failed_db()):
        result = monthly_report_scheduler.generate_monthly_finance_summary(7, 2026, 1)
    assert result["success"] is False
    assert result["error"] == "database down"


def test_monthly_task_publishes_success_failure_and_tolerates_bus_error() -> None:
    bus = MagicMock()
    with (
        patch.object(
            monthly_report_scheduler,
            "generate_monthly_finance_summary",
            return_value={"success": True, "summary": {}},
        ) as generate,
        patch("app.neuro_bus.bus.get_neuro_bus", return_value=bus),
    ):
        result = monthly_report_scheduler._monthly_finance_summary_task.run(7, 2026, 2)
    assert result["success"] is True
    generate.assert_called_once_with(7, 2026, 2)
    event = bus.publish.call_args.args[0]
    assert event.event_type == "report.monthly_summary_generated"

    failed_bus = MagicMock()
    failed_bus.publish.side_effect = RuntimeError("bus down")
    with (
        patch.object(
            monthly_report_scheduler,
            "generate_monthly_finance_summary",
            return_value={"success": False, "error": "x"},
        ),
        patch("app.neuro_bus.bus.get_neuro_bus", return_value=failed_bus),
    ):
        result = monthly_report_scheduler._monthly_finance_summary_task.run(None, None, None)
    assert result["success"] is False
    failed_bus.publish.assert_called_once()


def test_schedule_monthly_job_merges_existing_schedule() -> None:
    app = SimpleNamespace(conf=SimpleNamespace(beat_schedule={"existing": {"task": "x"}}))
    with patch.object(monthly_report_scheduler, "celery_app", app):
        monthly_report_scheduler.schedule_monthly_job(tenant_id=9, hour=1, minute=15)
    assert app.conf.beat_schedule["existing"] == {"task": "x"}
    scheduled = app.conf.beat_schedule["monthly-report-finance-summary"]
    assert scheduled["task"] == "monthly_report.generate_finance_summary"
    assert scheduled["kwargs"] == {"tenant_id": 9}
