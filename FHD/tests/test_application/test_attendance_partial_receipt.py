"""Real attendance worker, receipt reconciliation and reversible partial writes."""

import sqlite3
from unittest.mock import MagicMock

import pytest

from app.application.elt import auto_ingest_service as ais
from app.application.elt.errors import EltError
from app.application.elt.knowledge_index_meta import is_partial_business_receipt
from app.infrastructure.tenant_scope import tenant_scope
from tests.test_application.test_etl_attendance_confirmation import (
    attendance_store as attendance_store,
)
from tests.test_application.test_etl_attendance_confirmation import (
    preview_store as preview_store,
)
from tests.test_application.test_etl_attendance_confirmation import (
    snapshot,
)
from tests.test_application.test_etl_auto_ingest_service import ledger_root as ledger_root


@pytest.mark.usefixtures("ledger_root")
def test_real_attendance_partial_is_visible_and_reverses_once(attendance_store, monkeypatch):
    store = attendance_store
    with store.factory() as db:
        store.service.update_draft(
            db,
            run_id=store.run_id,
            owner_user_id=7,
            patch={
                "validation_rules": [
                    {"field": "employee_name", "op": "enum", "value": ["SYNTHETIC-KEEP"]}
                ],
            },
        )
    store.executor.futures[-1].result(timeout=10)
    reviewed = snapshot(store, store.run_id)
    assert reviewed["summary"]["error"] == 1
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: store.service)
    monkeypatch.setattr(ais, "get_request_active_mod_id", lambda: "m")
    service = ais.AutoIngestService()
    batch = {
        "batch_id": "b",
        "tenant_id": 1,
        "owner_user_id": 7,
        "mod_id": "m",
        "status": "running",
        "knowledge": {},
        "business": {},
    }
    ais._save_ledger(1, {"batches": {"b": batch}})
    with store.factory() as db:
        receipt = service._ingest_business(
            db,
            owner_user_id=7,
            path=store.workbook,
            file_name="attendance.xlsx",
            target_type="attendance",
            batch_id="b",
            prepared_plan={
                "run_id": store.run_id,
                "upload_id": reviewed["upload_id"],
                "preview_revision": reviewed["preview_revision"],
                "target_type": "attendance",
                "valid_rows_only": True,
            },
        )
    store.executor.futures[-1].result(timeout=10)
    assert receipt["status"] == "partial"
    assert not receipt["failed"] and not receipt["pending_execution"]
    assert is_partial_business_receipt(receipt)
    actual = snapshot(store, store.run_id)
    assert actual["summary"]["executed"] == 1 and actual["summary"]["error"] == 1
    with sqlite3.connect(store.attendance_db) as connection:
        assert connection.execute("select employee_name from attendance_employees").fetchall() == [
            ("SYNTHETIC-KEEP",)
        ]
    viewed = service.get_batch(tenant_id=1, owner_user_id=7, batch_id="b")
    assert viewed["status"] == "partial"
    assert viewed["business_progress"]["stage"] == "partial"
    with store.factory() as db:
        with pytest.raises(EltError):
            store.service.rollback(db, run_id=store.run_id, owner_user_id=8)
    with tenant_scope(2), store.factory() as db:
        with pytest.raises(EltError):
            store.service.rollback(db, run_id=store.run_id, owner_user_id=7)
    original = store.service.rollback
    spy = MagicMock(wraps=original)
    monkeypatch.setattr(store.service, "rollback", spy)
    with store.factory() as db:
        result = service.withdraw(db, tenant_id=1, owner_user_id=7, batch_id="b")
        repeated = service.withdraw(db, tenant_id=1, owner_user_id=7, batch_id="b")
    assert result["status"] == repeated["status"] == "withdrawn"
    spy.assert_called_once()
    with sqlite3.connect(store.attendance_db) as connection:
        assert connection.execute("select count(*) from attendance_employees").fetchone()[0] == 0
    assert snapshot(store, store.run_id)["rollback_status"] == "completed"


@pytest.mark.parametrize("mutation", ["unknown_target", "zero", "no_errors", "bool", "missing"])
def test_unknown_or_unproven_partial_is_not_accepted(mutation):
    receipt = {
        "status": "partial",
        "target_type": "attendance",
        "summary": {"executed": 1, "new": 1, "update": 0, "error": 1},
    }
    if mutation == "unknown_target":
        receipt["target_type"] = "other"
    elif mutation == "zero":
        receipt["summary"]["executed"] = 0
    elif mutation == "no_errors":
        receipt["summary"]["error"] = 0
    elif mutation == "bool":
        receipt["summary"]["executed"] = True
    else:
        receipt["summary"].pop("executed")
    assert not is_partial_business_receipt(receipt)


def test_real_same_source_followup_is_preserved_on_partial_rollback(attendance_store):
    from tests.test_application.test_etl_attendance_confirmation import approve

    store = attendance_store
    with store.factory() as db:
        store.service.update_draft(
            db,
            run_id=store.run_id,
            owner_user_id=7,
            patch={
                "validation_rules": [
                    {"field": "employee_name", "op": "enum", "value": ["SYNTHETIC-KEEP"]}
                ],
            },
        )
    store.executor.futures[-1].result(timeout=10)
    first = snapshot(store, store.run_id)
    approve(store, first["preview_revision"], valid_rows_only=True)
    store.executor.futures[-1].result(timeout=10)
    first = snapshot(store, store.run_id)
    assert first["status"] == "partial" and first["summary"]["executed"] == 1
    with store.factory() as db:
        second_id = store.service.create_preview(
            db, owner_user_id=7, upload_id=first["upload_id"], target_type="attendance"
        )["id"]
    store.executor.futures[-1].result(timeout=10)
    second = snapshot(store, second_id)
    assert second["summary"]["new"] == 2  # Roster rows have no daily/monthly dedup key.
    with store.factory() as db:
        store.service.execute(
            db,
            run_id=second_id,
            owner_user_id=7,
            confirmed=True,
            valid_rows_only=True,
            preview_revision=second["preview_revision"],
        )
    store.executor.futures[-1].result(timeout=10)
    assert snapshot(store, second_id)["summary"]["executed"] == 2
    with sqlite3.connect(store.attendance_db) as connection:
        before = tuple(connection.iterdump())
        assert connection.execute(
            "select employee_name from attendance_employees order by employee_name"
        ).fetchall() == [("SYNTHETIC-EXCLUDE",), ("SYNTHETIC-KEEP",)]
    for run_id in (store.run_id, second_id):
        with store.factory() as db, pytest.raises(EltError):
            store.service.rollback(db, run_id=run_id, owner_user_id=7)
        with sqlite3.connect(store.attendance_db) as connection:
            assert tuple(connection.iterdump()) == before


@pytest.mark.parametrize("overlap", ["employee", "department", "legacy"])
def test_cross_source_shared_metadata_or_legacy_receipt_never_deleted(
    tmp_path, monkeypatch, overlap
):
    from app.application.elt.attendance_pipeline import persist_attendance_rows
    from app.application.elt.targets.batch import AttendanceAdapter

    db_path = tmp_path / "attendance.sqlite"
    monkeypatch.setattr(AttendanceAdapter, "_db_path", staticmethod(lambda: db_path))
    monkeypatch.setattr("app.utils.path_io.path_utils.get_app_data_dir", lambda: str(tmp_path))
    source = "hash:a.xlsx"
    context = {
        "run_id": "a",
        "upload_path": str(tmp_path / "a.xlsx"),
        "file_name": "a.xlsx",
        "file_sha256": "hash",
    }
    receipt = persist_attendance_rows(
        [
            {
                "employee_name": "A",
                "department": "D",
                "business_id": "a",
                "source_row": 1,
                "work_date": "2026-01-01",
            }
        ],
        db_path=db_path,
        source_file=source,
        upload_path=tmp_path / "a.xlsx",
        run_id="a",
    )
    if overlap == "legacy":
        receipt.pop("rollback_scope")
    else:
        persist_attendance_rows(
            [
                {
                    "employee_name": "A" if overlap == "employee" else "B",
                    "department": "E" if overlap == "employee" else "D",
                    "business_id": "b",
                    "source_row": 2,
                    "work_date": "2026-01-02",
                }
            ],
            db_path=db_path,
            source_file="other:b.xlsx",
            upload_path=tmp_path / "b.xlsx",
            run_id="b",
        )
    with sqlite3.connect(db_path) as db:
        before = tuple(db.iterdump())
    with pytest.raises(EltError):
        AttendanceAdapter().rollback_batch(context, receipt)
    with sqlite3.connect(db_path) as db:
        assert tuple(db.iterdump()) == before


@pytest.mark.parametrize("table", ["attendance_daily_records", "attendance_employees"])
def test_attendance_delete_error_rolls_back_entire_database(tmp_path, monkeypatch, table):
    from app.application.elt.attendance_pipeline import persist_attendance_rows
    from app.application.elt.targets.batch import AttendanceAdapter

    db_path = tmp_path / "attendance.sqlite"
    monkeypatch.setattr(AttendanceAdapter, "_db_path", staticmethod(lambda: db_path))
    monkeypatch.setattr("app.utils.path_io.path_utils.get_app_data_dir", lambda: str(tmp_path))
    context = {
        "run_id": "a",
        "file_name": "a.xlsx",
        "file_sha256": "hash",
        "upload_path": str(tmp_path / "a.xlsx"),
    }
    receipt = persist_attendance_rows(
        [{"employee_name": "A", "business_id": "a", "source_row": 1, "work_date": "2026-01-01"}],
        db_path=db_path,
        source_file="hash:a.xlsx",
        upload_path=tmp_path / "a.xlsx",
        run_id="a",
    )
    with sqlite3.connect(db_path) as db:
        # Both an initial failure and a failure after daily deletion must be atomic.
        db.execute(
            f"CREATE TRIGGER broken_delete BEFORE DELETE ON {table} "
            "BEGIN DELETE FROM nonexistent_failure_table; END"
        )
        before = tuple(db.iterdump())
    with pytest.raises(sqlite3.OperationalError, match="nonexistent_failure_table"):
        AttendanceAdapter().rollback_batch(context, receipt)
    with sqlite3.connect(db_path) as db:
        assert tuple(db.iterdump()) == before
        db.execute("DROP TRIGGER broken_delete")
    assert AttendanceAdapter().rollback_batch(context, receipt) > 0
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT count(*) FROM attendance_daily_records").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM attendance_import_batches").fetchone() == (0,)
