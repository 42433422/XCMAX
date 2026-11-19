"""无进展看门狗：回收僵尸运行并释放租约。"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine

from app.application.elt import stale_watchdog


def _prepare(tmp_path, rows: list[tuple]) -> str:
    path = tmp_path / "elt.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE elt_runs (id TEXT PRIMARY KEY, status TEXT, stage TEXT, "
        "error_code TEXT, error_message TEXT, operation_kind TEXT, operation_token TEXT, "
        "operation_lease_until TIMESTAMP, updated_at TIMESTAMP, target_type TEXT, executed_rows INTEGER DEFAULT 0, "
        "progress INTEGER DEFAULT 0, receipt_json TEXT DEFAULT '{}', rollback_status TEXT)"
    )
    conn.executemany(
        "INSERT INTO elt_runs (id,status,stage,error_code,error_message,operation_kind,operation_token, "
        "operation_lease_until,updated_at,target_type) VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.execute("CREATE TABLE elt_run_rows (run_id TEXT, execution_status TEXT, after_json TEXT)")
    conn.commit()
    conn.close()
    return f"sqlite:///{path}"


def _row(run_id: str, status: str, target: str, updated_at: str, kind: str = "preview") -> tuple:
    return (
        run_id,
        status,
        status,
        None,
        None,
        kind,
        "tok",
        "2026-01-01 00:00:00",
        updated_at,
        target,
    )


def test_stale_preview_is_interrupted(monkeypatch, tmp_path):
    url = _prepare(
        tmp_path,
        [
            _row("stale", "previewing", "customers", "2000-01-01 00:00:00"),
            _row("fresh", "previewing", "customers", "2999-01-01 00:00:00"),
        ],
    )
    engine = create_engine(url)
    monkeypatch.setattr("app.db.get_engine", lambda: engine)
    # 活跃执行会在每次写入时续租，因此“fresh”用未到期的租约表示。
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE elt_runs SET operation_lease_until='2999-01-01 00:00:00' WHERE id='fresh'"
        )

    assert stale_watchdog.sweep_stale_runs() == 1

    with engine.connect() as conn:
        rows = dict(conn.exec_driver_sql("SELECT id, status FROM elt_runs").fetchall())
        lease = conn.exec_driver_sql(
            "SELECT operation_token, operation_lease_until FROM elt_runs WHERE id='stale'"
        ).fetchone()
    assert rows == {"stale": "interrupted", "fresh": "previewing"}
    assert lease == (None, None)


def test_stale_external_batch_is_outcome_unknown(monkeypatch, tmp_path):
    url = _prepare(
        tmp_path,
        [_row("batch", "executing", "shipment_records", "2000-01-01 00:00:00", "batch_execute")],
    )
    engine = create_engine(url)
    monkeypatch.setattr("app.db.get_engine", lambda: engine)

    assert stale_watchdog.sweep_stale_runs() == 1

    with engine.connect() as conn:
        status = conn.exec_driver_sql("SELECT status FROM elt_runs").scalar()
    assert status == "outcome_unknown"


def test_abnormal_batch_is_retryable(monkeypatch, tmp_path):
    url = _prepare(
        tmp_path,
        [_row("abn", "executing", "abnormal", "2000-01-01 00:00:00", "batch_execute")],
    )
    engine = create_engine(url)
    monkeypatch.setattr("app.db.get_engine", lambda: engine)

    assert stale_watchdog.sweep_stale_runs() == 1

    with engine.connect() as conn:
        status = conn.exec_driver_sql("SELECT status FROM elt_runs").scalar()
    assert status == "interrupted"


@pytest.mark.parametrize(
    "overrides,row_status,after,expected",
    [
        ({}, None, "{}", "interrupted"),
        ({"executed_rows": 2}, None, "{}", "outcome_unknown"),
        ({"receipt_json": '{"executed":1}'}, None, "{}", "outcome_unknown"),
        ({"receipt_json": "invalid"}, None, "{}", "outcome_unknown"),
        ({"receipt_json": None}, None, "{}", "outcome_unknown"),
        ({}, "success", "{}", "outcome_unknown"),
        ({}, "outcome_unknown", "{}", "outcome_unknown"),
        ({}, None, '{"id":1}', "outcome_unknown"),
        ({}, None, None, "outcome_unknown"),
        ({"operation_kind": "batch_rollback"}, None, "{}", "outcome_unknown"),
        (
            {"operation_kind": "batch_rollback", "status": "completed"},
            None,
            "{}",
            "outcome_unknown",
        ),
        ({"target_type": "knowledge"}, None, "{}", "outcome_unknown"),
        ({"operation_lease_until": "2999-01-01"}, None, "{}", "executing"),
        ({"operation_lease_until": None}, None, "{}", "executing"),
    ],
)
def test_stale_batch_preserves_uncertain_evidence(
    monkeypatch, tmp_path, overrides, row_status, after, expected
):
    engine = create_engine(
        _prepare(tmp_path, [_row("run", "executing", "abnormal", "2000-01-01", "batch_execute")])
    )
    monkeypatch.setattr("app.db.get_engine", lambda: engine)
    with engine.begin() as conn:
        for key, value in overrides.items():
            conn.exec_driver_sql(f"UPDATE elt_runs SET {key} = ?", (value,))
        conn.exec_driver_sql("INSERT INTO elt_run_rows VALUES ('run', ?, ?)", (row_status, after))
    assert stale_watchdog.sweep_stale_runs() == (0 if expected == "executing" else 1)
    with engine.connect() as conn:
        row = conn.exec_driver_sql("SELECT * FROM elt_runs").mappings().one()
        assert row["status"] == expected
        assert row["operation_token"] == (None if expected == "interrupted" else "tok")
        if expected != "interrupted":
            assert "未写入" not in (row["error_message"] or "")
        if overrides.get("operation_kind") == "batch_rollback":
            assert row["rollback_status"] == "outcome_unknown"
    assert stale_watchdog.sweep_stale_runs() == 0
    engine.dispose()


@pytest.mark.parametrize(
    "kind,status", [("preview", "previewing"), ("batch_rollback", "completed")]
)
def test_stale_live_lease_is_not_reclaimed(monkeypatch, tmp_path, kind, status):
    engine = create_engine(
        _prepare(tmp_path, [_row("live", status, "abnormal", "2000-01-01", kind)])
    )
    monkeypatch.setattr("app.db.get_engine", lambda: engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("UPDATE elt_runs SET operation_lease_until='2999-01-01'")
    assert stale_watchdog.sweep_stale_runs() == 0
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT status, operation_token FROM elt_runs").one() == (
            status,
            "tok",
        )
    engine.dispose()


def _hung_run(engine, run_id: str, kind: str, *, progress: int = 0, executed_rows: int = 0) -> None:
    lease = (datetime.now(UTC) - timedelta(seconds=200)).strftime("%Y-%m-%d %H:%M:%S")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO elt_runs (id,status,stage,operation_kind,operation_token,"
            "operation_lease_until,updated_at,target_type,executed_rows,progress,receipt_json) "
            "VALUES (?,?,?,?,?,?,'9999-01-01 00:00:00','customers',?,?,'{}')",
            (run_id, "executing", "executing", kind, "tok", lease, executed_rows, progress),
        )


def test_claimed_lease_without_progress_is_reclaimed_without_waiting(monkeypatch, tmp_path):
    engine = create_engine(_prepare(tmp_path, []))
    monkeypatch.setattr("app.db.get_engine", lambda: engine)
    _hung_run(engine, "hung", "execute")

    assert stale_watchdog.sweep_stale_runs() == 1

    with engine.connect() as conn:
        row = conn.exec_driver_sql(
            "SELECT status, error_code, operation_token, operation_lease_until FROM elt_runs"
        ).one()
    assert row[0] == "interrupted"
    assert row[1] == "ELT_EXECUTION_INTERRUPTED"
    assert row[2:] == (None, None)
    assert stale_watchdog.sweep_stale_runs() == 0
    engine.dispose()


def test_claimed_lease_without_progress_batch_is_settled_quickly(monkeypatch, tmp_path):
    engine = create_engine(_prepare(tmp_path, []))
    monkeypatch.setattr("app.db.get_engine", lambda: engine)
    _hung_run(engine, "hung-batch", "batch_execute")

    assert stale_watchdog.sweep_stale_runs() == 1

    with engine.connect() as conn:
        row = conn.exec_driver_sql("SELECT status, error_code, operation_token FROM elt_runs").one()
    assert row == ("outcome_unknown", "ELT_OUTCOME_UNKNOWN", "tok")
    engine.dispose()


def test_claimed_lease_with_progress_is_not_reclaimed(monkeypatch, tmp_path):
    engine = create_engine(_prepare(tmp_path, []))
    monkeypatch.setattr("app.db.get_engine", lambda: engine)
    _hung_run(engine, "slow", "execute", progress=40)

    assert stale_watchdog.sweep_stale_runs() == 0
    engine.dispose()


def test_watchdog_stops_its_real_thread_and_can_restart(monkeypatch):
    scanned = threading.Event()
    monkeypatch.setattr(stale_watchdog, "sweep_stale_runs", scanned.set)
    monkeypatch.setattr(stale_watchdog, "_INTERVAL_SECONDS", 60.0)
    try:
        for _ in range(2):
            scanned.clear()
            assert stale_watchdog.start_stale_watchdog()
            worker = stale_watchdog._THREAD
            assert scanned.wait(2.0)
            assert not stale_watchdog.start_stale_watchdog()
            stale_watchdog.stop_stale_watchdog()
            assert worker is not None and not worker.is_alive()
    finally:
        stale_watchdog.stop_stale_watchdog()
