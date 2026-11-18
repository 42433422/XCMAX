"""无进展看门狗：回收僵尸运行并释放租约。"""

from __future__ import annotations

import sqlite3

from sqlalchemy import create_engine

from app.application.elt import stale_watchdog


def _prepare(tmp_path, rows: list[tuple]) -> str:
    path = tmp_path / "elt.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE elt_runs (id TEXT PRIMARY KEY, status TEXT, stage TEXT, "
        "error_code TEXT, error_message TEXT, operation_kind TEXT, operation_token TEXT, "
        "operation_lease_until TIMESTAMP, updated_at TIMESTAMP, target_type TEXT)"
    )
    conn.executemany(
        "INSERT INTO elt_runs VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
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
