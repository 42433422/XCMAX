"""Exercise persisted export values and damaged compressed upload payloads."""

import io
import json
import struct
import zipfile
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from app.application.elt.errors import EltError
from app.application.elt.result_export import _as_number, write_xlsx_result
from app.application.elt.targets import json_safe
from app.application.elt.transforms import apply_transform
from app.application.elt.upload_content_gate import check_stored_content


def test_export_numeric_values_survive_normalized_json(tmp_path):
    values = ["12.50", "0", "-2.25"]
    rows = [{"amount": apply_transform(value, {"op": "number"}, {})} for value in values]
    rows = json.loads(json.dumps(json_safe(rows)))
    assert all(isinstance(row["amount"], str) for row in rows)
    path = tmp_path / "result.xlsx"
    write_xlsx_result(
        path,
        columns=[{"key": "amount", "label": "金额", "type": "money"}],
        rows=rows,
        sheet_name="结果",
        notes=[],
    )
    workbook = load_workbook(path)
    try:
        sheet = workbook.active
        assert [sheet.cell(row, 1).value for row in range(2, 5)] == [12.5, 0, -2.25]
        assert all(sheet.cell(row, 1).data_type == "n" for row in range(2, 5))
        assert all(sheet.cell(row, 1).number_format == "#,##0.00" for row in range(2, 5))
        assert sheet["A5"].value == "=SUM(A2:A4)"
    finally:
        workbook.close()


def test_export_labels_are_literal_and_overlong_values_are_rejected(tmp_path):
    path = tmp_path / "result.xlsx"
    options = {
        "columns": [{"key": "value", "label": "=1+2", "type": "text"}],
        "sheet_name": "结果",
        "notes": [],
    }
    write_xlsx_result(path, rows=[{"value": "kept"}], **options)
    with path.open("rb") as handle:
        workbook = load_workbook(handle)
        try:
            assert workbook.active["A1"].data_type == "s"
        finally:
            workbook.close()
    before = path.read_bytes()
    with pytest.raises(EltError):
        write_xlsx_result(path, rows=[{"value": "a" * 32768}], **options)
    assert path.read_bytes() == before


@pytest.mark.parametrize("damage", ["zip", "cell"])
def test_export_readback_rejects_corruption_before_publishing(tmp_path, monkeypatch, damage):
    from openpyxl import Workbook

    path = tmp_path / "result.xlsx"
    path.write_bytes(b"previous verified artifact")
    save = Workbook.save

    def corrupt_after_save(book, destination):
        if damage == "cell":
            book.active["A2"] = "different value"
        save(book, destination)
        from pathlib import Path

        if damage == "zip":
            Path(destination).write_bytes(b"incomplete zip")

    monkeypatch.setattr(Workbook, "save", corrupt_after_save)
    with pytest.raises(EltError):
        write_xlsx_result(
            path,
            columns=[{"key": "value", "label": "值", "type": "text"}],
            rows=[{"value": "reviewed"}],
            sheet_name="结果",
            notes=[],
        )
    assert path.read_bytes() == b"previous verified artifact"
    assert list(tmp_path.iterdir()) == [path]


def test_csv_export_records_verified_bytes_and_preserves_original_headers(tmp_path, monkeypatch):
    import csv
    import hashlib

    from app.application.elt.targets.batch import ExportCsvAdapter

    monkeypatch.setattr("app.application.elt.targets.batch.get_app_data_dir", lambda: tmp_path)
    header = "=1+2"
    rows = [{header: "=1+3", "note": 'quoted,"line\nnext'}]
    result = ExportCsvAdapter().execute_batch(rows, {"run_id": "csv", "row_count": 1})
    path = tmp_path / "elt" / "exports" / result["receipt"]["file_name"]
    with path.open(encoding="utf-8-sig", newline="") as handle:
        assert list(csv.reader(handle)) == [["'=1+2", "note"], ["'=1+3", 'quoted,"line\nnext']]
    assert result["receipt"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result["receipt"]["headers"] == [header, "note"]
    assert result["receipt"]["readback_verified"] is True
    assert result["executed"] == 1 and rows[0][header] == "=1+3"


@pytest.mark.parametrize("target", ["export_csv", "export_xlsx"])
def test_export_failure_preserves_original_and_cleans_staging(tmp_path, monkeypatch, target):
    from app.application.elt.targets import get_adapter

    monkeypatch.setattr("app.application.elt.targets.batch.get_app_data_dir", lambda: tmp_path)
    adapter = get_adapter(target)
    context = {"run_id": "atomic", "row_count": 1}
    original = adapter.execute_batch([{"a": "before"}], context)
    root = tmp_path / "elt" / "exports"
    path = root / original["receipt"]["file_name"]
    before = path.read_bytes()

    def progress(*_):
        raise RuntimeError("interrupted before publication")

    with pytest.raises(RuntimeError, match="interrupted"):
        adapter.execute_batch([{"a": "after"}], {**context, "progress_callback": progress})
    assert path.read_bytes() == before and list(root.iterdir()) == [path]


@pytest.mark.parametrize(
    "value",
    [
        "=1+2",
        "@SUM(A1)",
        "not a number",
        "NaN",
        "Infinity",
        "1e999",
        True,
        Decimal("NaN"),
        float("inf"),
    ],
)
def test_export_does_not_coerce_unsafe_or_nonfinite_numbers(value):
    assert _as_number(value) is None


def test_upload_rejects_corrupted_deflate_stream(tmp_path):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", "<workbook>" + "abc" * 100 + "</workbook>")
    payload = bytearray(stream.getvalue())
    name_length, extra_length = struct.unpack_from("<HH", payload, 26)
    payload[30 + name_length + extra_length] = 0xFF  # Invalid DEFLATE block, intact ZIP directory.
    path = tmp_path / "damaged.xlsx"
    path.write_bytes(payload)
    with pytest.raises(EltError) as error:
        check_stored_content(path, ".xlsx")
    assert error.value.code == "ELT_FILE_CORRUPTED"
