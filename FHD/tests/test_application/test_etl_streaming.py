"""Full source evidence stays repeatable and verifiable without full-row RAM residency."""

import csv
import os
import tracemalloc
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from openpyxl import Workbook
from sqlalchemy import event

from app.application.elt import parser_types, service_source
from app.application.elt.errors import EltError
from app.application.elt.parser_types import ParsedDataset, ParsedRow, ParsedRows
from app.application.elt.parsers import parse_file
from app.db.models.elt import EltRun, EltRunRow, EltUpload
from tests.test_application.test_etl_preview_task_boundaries import create_preview
from tests.test_application.test_etl_preview_task_boundaries import preview_store as preview_store


def test_spooled_rows_preserve_values_evidence_access_and_permissions():
    value = {
        "date": date(2026, 1, 2),
        "datetime": datetime(2026, 1, 2, 3, 4),
        "time": time(3, 4),
        "duration": timedelta(days=2, microseconds=5),
        "decimal": Decimal("1.234"),
        "raw": b"bytes",
        "tuple": (1, None, True),
        "dict": {"$etl": "datetime", "value": "this is a source value, not a type tag"},
        "nonstring_keys": {1: "integer key", (2, 3): "tuple key"},
    }
    original = ParsedRow("工作表", 4, value, {"original_fragment": value, "columns": {"date": 2}})
    rows = ParsedRows([original, original])
    try:
        assert rows[0] == rows[-1] == original
        assert rows[:1] == [original]
        iterator = iter(rows)
        assert next(iterator) == rows[1]
        assert next(iterator) == original
        changed = rows[0]
        changed.provenance["ocr"] = True
        rows[0] = changed
        assert rows[0].provenance["ocr"] is True
        assert "ocr" not in rows[1].provenance
        for stream in (rows._data, rows._offsets):
            if os.name == "posix":
                assert os.fstat(stream.fileno()).st_mode & 0o077 == 0
    finally:
        rows.close()
    assert rows.closed
    with pytest.raises(ValueError):
        _ = rows[0]


def test_large_csv_keeps_all_rows_with_bounded_python_memory(tmp_path):
    source = tmp_path / "full.csv"
    with source.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow([f"field_{column}" for column in range(12)])
        for number in range(10_000):
            writer.writerow([f"value-{number}-{column}" for column in range(12)])
    tracemalloc.start()
    try:
        dataset = parse_file(source, target_type="knowledge")
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    try:
        assert len(dataset.rows) == 10_000
        assert sum(1 for _ in dataset.rows) == 10_000
        assert dataset.rows[-1].values["field_11"] == "value-9999-11"
        assert dataset.rows[-1].provenance["original_fragment"]["field_11"] == "value-9999-11"
        assert peak < 4 * 1024 * 1024, peak
    finally:
        dataset.close()


def test_excel_dates_and_all_source_columns_survive_spooling(tmp_path):
    source = tmp_path / "full.xlsx"
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("数据")
    sheet.append(["客户名称", "日期", "金额"])
    stamp = datetime(2026, 1, 2, 3, 4)
    for number in range(1500):
        sheet.append([f"客户{number}", stamp, 12.5])
    workbook.save(source)
    workbook.close()
    dataset = parse_file(source, target_type="knowledge")
    try:
        assert len(dataset.rows) == 1500
        row = dataset.rows[-1]
        assert row.row_number == 1501
        assert row.values == {"客户名称": "客户1499", "日期": stamp, "金额": 12.5}
        assert row.provenance["original_fragment"] == row.values
    finally:
        dataset.close()


def test_snapshot_load_streams_columns_and_verifies_last_row(preview_store, monkeypatch):
    store = preview_store
    dataset = ParsedDataset(
        ["客户名称"],
        ParsedRows(
            ParsedRow("CSV", number + 2, {"客户名称": f"客户{number}"}, {"row": number + 2})
            for number in range(2500)
        ),
        {"kind": "csv"},
    )
    with store.factory() as db:
        db.add(
            EltUpload(
                id="source",
                tenant_id=1,
                owner_user_id=7,
                file_name="synthetic.csv",
                storage_path="synthetic.csv",
                suffix=".csv",
                sha256="hash",
                size_bytes=0,
            )
        )
        db.flush()
        run = EltRun(
            id="streamed",
            tenant_id=1,
            owner_user_id=7,
            upload_id="source",
            file_sha256="hash",
            target_type="customers",
            draft_json="{}",
        )
        db.add(run)
        try:
            store.service._persist_source_snapshot(db, run, dataset)
        finally:
            dataset.close()
        loaded_entities = []
        event.listen(db, "loaded_as_persistent", lambda _db, obj: loaded_entities.append(type(obj)))
        snapshot = store.service._load_source_snapshot(db, run)
        try:
            assert len(snapshot.rows) == 2500
            assert snapshot.rows[-1].values == {"客户名称": "客户2499"}
            assert EltRunRow not in loaded_entities
        finally:
            snapshot.close()
        db.query(EltRunRow).filter_by(run_id=run.id, source_row=2501).update({"source_json": "{}"})
        db.commit()
        created = []

        def rows_factory():
            rows = ParsedRows()
            created.append(rows)
            return rows

        monkeypatch.setattr(service_source, "ParsedRows", rows_factory)
        with pytest.raises(EltError, match="原始数据快照"):
            store.service._load_source_snapshot(db, run)
        assert created and all(rows.closed for rows in created)


@pytest.mark.parametrize("fail", [False, True])
def test_worker_closes_temporary_rows_on_terminal_outcome(preview_store, monkeypatch, fail):
    from app.application.elt import parsers

    store, created = preview_store, []
    monkeypatch.setenv("FHD_ETL_LLM", "off")

    class ObservedRows(parser_types.ParsedRows):
        def __init__(self, *args):
            super().__init__(*args)
            created.append(self)

    monkeypatch.setattr(parsers, "ParsedRows", ObservedRows)
    monkeypatch.setattr(service_source, "ParsedRows", ObservedRows)
    if fail:

        def fail_persist(*_args, **_kwargs):
            raise EltError("ELT_TEST_FAILURE", "测试失败")

        monkeypatch.setattr(store.service, "_persist_source_snapshot", fail_persist)
    run_id = create_preview(store)
    store.executor.futures[-1].result(timeout=10)
    assert created and all(rows.closed for rows in created)
    with store.factory() as db:
        assert db.get(EltRun, run_id).status == ("failed" if fail else "preview_ready")
