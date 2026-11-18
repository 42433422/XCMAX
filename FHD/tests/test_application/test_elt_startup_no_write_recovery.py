"""Startup recovery must not turn receipts or uncertain batch work into no-write claims."""

import pytest
from sqlalchemy import create_engine, text

from app.application.elt.service import mark_interrupted_runs_on_startup


@pytest.mark.parametrize(
    "overrides,row_status,after,expected",
    [
        ({}, None, "{}", "interrupted"),
        ({"executed_rows": 2}, None, "{}", "outcome_unknown"),
        ({"receipt_json": '{"executed": 1}'}, None, "{}", "outcome_unknown"),
        ({"receipt_json": "invalid"}, None, "{}", "outcome_unknown"),
        ({"receipt_json": None}, None, "{}", "outcome_unknown"),
        ({}, "success", "{}", "outcome_unknown"),
        ({}, "outcome_unknown", "{}", "outcome_unknown"),
        ({}, None, '{"id": 1}', "outcome_unknown"),
        ({}, None, None, "outcome_unknown"),
        (
            {"operation_kind": "batch_rollback", "status": "completed"},
            None,
            "{}",
            "outcome_unknown",
        ),
        ({"operation_kind": "batch_rollback"}, None, "{}", "outcome_unknown"),
        ({"status": "outcome_unknown"}, None, "{}", "outcome_unknown"),
        ({"target_type": "knowledge"}, None, "{}", "outcome_unknown"),
        ({"operation_lease_until": "2999-01-01"}, None, "{}", "executing"),
    ],
)
def test_expired_abnormal_requires_no_write_evidence(overrides, row_status, after, expected):
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE elt_runs (
                id TEXT PRIMARY KEY, status TEXT, stage TEXT, error_code TEXT,
                error_message TEXT, operation_kind TEXT, operation_token TEXT,
                operation_lease_until TEXT, updated_at TEXT, target_type TEXT,
                rollback_status TEXT, executed_rows INTEGER, receipt_json TEXT)
        """)
        )
        conn.execute(
            text("""
            CREATE TABLE elt_run_rows (run_id TEXT, execution_status TEXT, after_json TEXT)
        """)
        )
        data = {
            "id": "run",
            "status": "executing",
            "operation_kind": "batch_execute",
            "operation_token": "owner",
            "operation_lease_until": "2000-01-01",
            "target_type": "abnormal",
            "executed_rows": 0,
            "receipt_json": "{}",
        }
        data.update(overrides)
        conn.execute(
            text(
                f"INSERT INTO elt_runs ({','.join(data)}) VALUES "
                f"({','.join(':' + key for key in data)})"
            ),
            data,
        )
        conn.execute(
            text("INSERT INTO elt_run_rows VALUES ('run', :status, :after)"),
            {"status": row_status, "after": after},
        )
    mark_interrupted_runs_on_startup(engine)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM elt_runs")).mappings().one()
        assert result["status"] == expected
        assert result["operation_token"] == (None if expected == "interrupted" else "owner")
        if expected != "interrupted":
            assert "未写入" not in (result["error_message"] or "")
        if overrides.get("operation_kind") == "batch_rollback":
            assert result["rollback_status"] == "outcome_unknown"
    assert mark_interrupted_runs_on_startup(engine) == 0
    engine.dispose()
