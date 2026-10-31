"""Whole-workbook attendance writes must never exceed the approved row scope."""

from __future__ import annotations

import hashlib
import sqlite3

import pytest
from openpyxl import Workbook

from app.application.attendance_import_app_service import _ensure_schema
from app.application.elt.errors import EltError
from app.application.elt.preview_confirmation import record_confirmation
from app.application.elt.targets.batch import AttendanceAdapter
from app.db.models.elt import EltRun, EltRunRow
from tests.test_application.test_etl_preview_task_boundaries import (
    preview_store as preview_store,
)
from tests.test_application.test_etl_preview_task_boundaries import snapshot

PARTIAL = "ELT_ATTENDANCE_PARTIAL_SELECTION_UNSUPPORTED"
EMPTY = "ELT_ATTENDANCE_EMPTY_SELECTION"


@pytest.fixture
def attendance_store(preview_store, tmp_path, monkeypatch):
    store = preview_store
    monkeypatch.setenv("FHD_ETL_LLM", "off")
    store.workbook = tmp_path / "synthetic-attendance.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "明细"
    for row in (
        ["合成考勤"],
        [],
        ["部门", "性质", "姓名"],
        ["合成部门", "正班", "SYNTHETIC-KEEP"],
        ["合成部门", "正班", "SYNTHETIC-EXCLUDE"],
    ):
        sheet.append(row)
    workbook.save(store.workbook)
    workbook.close()
    store.attendance_db = tmp_path / "attendance.sqlite"
    with sqlite3.connect(store.attendance_db) as db:
        _ensure_schema(db)
    monkeypatch.setattr(AttendanceAdapter, "_db_path", staticmethod(lambda: store.attendance_db))
    with store.factory() as db, store.workbook.open("rb") as stream:
        upload = store.service.save_upload(
            db,
            owner_user_id=7,
            file_name=store.workbook.name,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            stream=stream,
        )
        db.commit()
        store.run_id = store.service.create_preview(
            db, owner_user_id=7, upload_id=upload["upload_id"], target_type="attendance"
        )["id"]
    store.executor.futures[-1].result(timeout=10)
    reviewed = snapshot(store, store.run_id)
    assert reviewed["status"] == "preview_ready" and reviewed["summary"]["new"] == 2
    return store


def attendance_contents(store):
    with sqlite3.connect(store.attendance_db) as db:
        return tuple(db.iterdump())


def approve(store, revision, *, valid_rows_only=False):
    with store.factory() as db:
        return store.service.execute(
            db,
            run_id=store.run_id,
            owner_user_id=7,
            confirmed=True,
            valid_rows_only=valid_rows_only,
            preview_revision=revision,
        )


@pytest.mark.parametrize("boundary", ["approval", "worker"])
@pytest.mark.parametrize("selection,code", [("skip", PARTIAL), ("error", PARTIAL), ("none", EMPTY)])
def test_excluded_attendance_rows_never_reach_workbook_writer(
    attendance_store, boundary, selection, code
):
    store = attendance_store
    before = attendance_contents(store)
    with store.factory() as db:
        rows = db.query(EltRunRow).filter_by(run_id=store.run_id).order_by(EltRunRow.id).all()
        patch = (
            {
                "field_mappings": [{"source": "姓名", "target": "document_path"}],
                "validation_rules": [
                    {"field": "document_path", "op": "enum", "value": ["SYNTHETIC-KEEP"]}
                ],
            }
            if selection == "error"
            else {
                "row_overrides": {
                    str(row.id): "skip" for row in (rows if selection == "none" else rows[1:])
                }
            }
        )
        store.service.update_draft(db, run_id=store.run_id, owner_user_id=7, patch=patch)
    if selection == "error":
        store.executor.futures[-1].result(timeout=10)
    reviewed = snapshot(store, store.run_id)
    assert reviewed["summary"]["error"] == (1 if selection == "error" else 0)
    only_valid = selection == "error"
    if boundary == "approval":
        with pytest.raises(EltError) as error:
            approve(store, reviewed["preview_revision"], valid_rows_only=only_valid)
        assert error.value.code == code and error.value.status_code == 409
        current = snapshot(store, store.run_id)
        assert current["status"] == "preview_ready"
        assert current["preview_revision"] == reviewed["preview_revision"]
    else:
        # A legacy/internal dispatcher cannot bypass the worker's own scope check.
        with store.factory() as db:
            run = db.get(EltRun, store.run_id)
            record_confirmation(run, reviewed["preview_revision"], valid_rows_only=only_valid)
            run.status = "executing"
            db.commit()
        store.service._execute_worker(store.run_id, 7, only_valid)
        current = snapshot(store, store.run_id)
        assert current["status"] == "failed" and current["error_code"] == code
    assert current["lease"] == (None, None, None)
    assert current["summary"]["executed"] == 0
    assert all(row["execution_status"] != "success" for row in current["persisted_rows"])
    assert attendance_contents(store) == before


def test_complete_attendance_approval_writes_real_workbook(attendance_store):
    store = attendance_store
    reviewed = snapshot(store, store.run_id)
    approve(store, reviewed["preview_revision"])
    store.executor.futures[-1].result(timeout=10)
    current = snapshot(store, store.run_id)
    assert current["status"] == "completed" and current["summary"]["executed"] == 2
    with sqlite3.connect(store.attendance_db) as db:
        assert db.execute(
            "SELECT employee_name FROM attendance_employees ORDER BY employee_name"
        ).fetchmany(3) == [
            ("SYNTHETIC-EXCLUDE",),
            ("SYNTHETIC-KEEP",),
        ]
        assert db.execute("SELECT COUNT(*) FROM attendance_import_batches").fetchone()[0] == 1


@pytest.mark.parametrize(
    "declared,total,actual,code",
    [(1, 2, 1, PARTIAL), (2, 2, 1, PARTIAL), (0, 2, 0, EMPTY), (2, None, 2, PARTIAL)],
)
def test_attendance_adapter_also_rejects_incomplete_scope(
    attendance_store, declared, total, actual, code
):
    store = attendance_store
    before = attendance_contents(store)
    context = {
        "upload_path": str(store.workbook),
        "file_sha256": hashlib.sha256(store.workbook.read_bytes()).hexdigest(),
        "row_count": declared,
        "total_rows": total,
    }
    with pytest.raises(EltError) as error:
        AttendanceAdapter().execute_batch(({} for _ in range(actual)), context)
    assert error.value.code == code
    assert attendance_contents(store) == before
