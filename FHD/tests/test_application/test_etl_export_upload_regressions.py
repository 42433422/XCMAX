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
