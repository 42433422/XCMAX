"""Real XLSX coordinates must not turn small read pages into enormous dense frames."""

import logging
import struct
import warnings
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

import openpyxl
import pytest

from app.application.tools.workflow_tools import excel_analysis
from app.application.tools.workflow_tools.contracts import ExcelIO

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _analysis():
    return excel_analysis.ExcelAnalysis(
        ExcelIO(
            lambda _root, path: Path(path),
            excel_analysis.read_excel_dataframe,
            lambda args: args.get("header_row"),
        ),
        lambda frame, _query: frame,
        lambda _path, _sheet: "",
        logging.getLogger(__name__),
    )


def _dense(path):
    workbook = openpyxl.Workbook()
    workbook.active.append(["id", "amount"])
    workbook.active.append([1, 7])
    workbook.save(path)
    workbook.close()


def _sparse(path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Sparse"
    for address, value in {
        "A1": "origin",
        "C3": "=1+1",
        "XFD1000000": 0,
        "A1048576": False,
        "XFD1048576": "last",
    }.items():
        sheet[address] = value
    hidden = workbook.create_sheet("Hidden")
    hidden.sheet_state = "veryHidden"
    hidden["B5"] = "retained"
    workbook.save(path)
    workbook.close()


def _rewrite_sheet(path, *, dimension, rows=None):
    output = BytesIO()
    with ZipFile(path) as archive, ZipFile(output, "w", ZIP_DEFLATED) as rewritten:
        for name in archive.namelist():
            body = archive.read(name)
            if name == "xl/worksheets/sheet1.xml":
                root = ET.fromstring(body)
                root.find(_NS + "dimension").set("ref", dimension)
                if rows is not None:
                    original = root.find(_NS + "sheetData")
                    position = list(root).index(original)
                    root.remove(original)
                    root.insert(
                        position,
                        ET.fromstring(f'<sheetData xmlns="{_NS[1:-1]}">{rows}</sheetData>'),
                    )
                body = ET.tostring(root)
            rewritten.writestr(name, body)
    path.write_bytes(output.getvalue())


@pytest.mark.parametrize("action", ["read", "structure", "statistics", "query", "aggregate"])
def test_real_sparse_workbook_rejected_before_header_or_pandas(tmp_path, monkeypatch, action):
    path = tmp_path / "sparse.xlsx"
    _sparse(path)
    original = path.read_bytes()
    pandas = Mock(side_effect=AssertionError("unsafe rectangle reached pandas"))
    header = Mock(side_effect=AssertionError("unsafe rectangle reached header inference"))
    native = Mock(wraps=openpyxl.load_workbook)
    monkeypatch.setattr(excel_analysis.pd, "read_excel", pandas)
    monkeypatch.setattr(excel_analysis, "auto_header_row", header)
    monkeypatch.setattr(openpyxl, "load_workbook", native)
    result = _analysis().analyze(
        {
            "file_path": str(path),
            "action": action,
            "sheet_name": "Sparse",
            "max_rows": 1,
            "question": "统计金额",
            "metrics": [{"column": "A", "op": "sum"}],
        }
    )
    assert result["success"] is False
    assert result["error"] == "excel_dense_materialization_budget_exceeded"
    assert result["minimum_rectangular_cells"] > result["max_rectangular_cells"] == 500_000
    assert result["readback"] == {"action": "read", "view": "cells", "sheet_name": "Sparse"}
    pandas.assert_not_called()
    header.assert_not_called()
    assert native.call_args.kwargs["read_only"] is True
    assert native.call_args.kwargs["keep_links"] is False
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "rows",
    [
        '<row r="1048576"><c r="XFD1048576"><v>7</v></c></row>',
        '<row r="1048576"><c><v>7</v></c></row>',
        '<row><c r="XFD1048576"><v>7</v></c></row>',
        '<row r="1048576"><c r="XFD1"><v>7</v></c></row>',
        '<row r="1"><c r="A1"><v>7</v></c></row><row r="1048576"/>',
    ],
    ids=["explicit", "implicit-cell", "implicit-row", "different-row", "empty-far-row"],
)
def test_shared_reader_uses_real_parser_positions_not_dimension(tmp_path, monkeypatch, rows):
    path = tmp_path / "disguised.xlsx"
    _dense(path)
    _rewrite_sheet(path, dimension="A1", rows=rows)
    pandas = Mock(side_effect=AssertionError("unsafe rectangle reached pandas"))
    monkeypatch.setattr(excel_analysis.pd, "read_excel", pandas)
    with pytest.raises(excel_analysis._DenseWorkbookBudgetExceeded) as raised:
        excel_analysis.read_excel_dataframe(path, sheet_name=None, header_row_1based=1)
    assert raised.value.details["observed_rows"] == 1048576
    assert raised.value.details["minimum_rectangular_cells"] > 500_000
    pandas.assert_not_called()


def test_false_large_dimension_does_not_block_small_real_values(tmp_path):
    path = tmp_path / "overstated.xlsx"
    _dense(path)
    _rewrite_sheet(path, dimension="A1:XFD1048576")
    result = _analysis().analyze({"file_path": str(path), "header_row": 1})
    assert result["success"] is True and result["records"] == [{"id": 1, "amount": 7}]


@pytest.mark.parametrize("suffix", [".xls", ".payload", ".zip"])
def test_ooxml_bytes_under_other_suffix_cannot_bypass_budget(tmp_path, monkeypatch, suffix):
    path = tmp_path / ("disguised" + suffix)
    _sparse(path)
    pandas = Mock(side_effect=AssertionError("disguised OOXML reached pandas"))
    monkeypatch.setattr(excel_analysis.pd, "read_excel", pandas)
    result = _analysis().analyze({"file_path": str(path), "header_row": 0, "max_rows": 1})
    assert result["error"] == "excel_dense_materialization_budget_exceeded"
    pandas.assert_not_called()


def test_non_ooxml_zip_does_not_reach_pandas_or_claim_success(tmp_path, monkeypatch):
    path = tmp_path / "opaque.payload"
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("plain.txt", "not a workbook")
    pandas = Mock(side_effect=AssertionError("non-OOXML ZIP reached pandas"))
    monkeypatch.setattr(excel_analysis.pd, "read_excel", pandas)
    result = _analysis().analyze({"file_path": str(path), "header_row": 0})
    assert result["success"] is False and result["error"] == "read_excel_failed"
    with pytest.raises(ValueError, match="invalid_ooxml_package"):
        excel_analysis.read_excel_dataframe(path, sheet_name=None, header_row_1based=0)
    pandas.assert_not_called()


def test_small_implicit_coordinates_still_use_native_parser_values(tmp_path):
    path = tmp_path / "implicit.xlsx"
    _dense(path)
    _rewrite_sheet(
        path,
        dimension="A1",
        rows=(
            '<row><c t="inlineStr"><is><t>id</t></is></c>'
            '<c t="inlineStr"><is><t>amount</t></is></c></row>'
            "<row><c><v>1</v></c><c><v>7</v></c></row>"
        ),
    )
    result = _analysis().analyze({"file_path": str(path), "header_row": 1})
    assert result["success"] is True and result["records"] == [{"id": 1, "amount": 7}]


def test_native_views_keep_six_far_sparse_cells_readable(tmp_path, monkeypatch):
    path = tmp_path / "sparse.xlsx"
    _sparse(path)
    monkeypatch.setattr(
        excel_analysis.pd, "read_excel", Mock(side_effect=AssertionError("native read used pandas"))
    )
    tool = _analysis()
    listing = tool.analyze({"file_path": str(path), "view": "sheets"})
    assert listing["success"] is True
    assert [sheet["cell_count"] for sheet in listing["sheets"]] == [5, 1]
    values = {}
    for name in ("Sparse", "Hidden"):
        result = tool.analyze({"file_path": str(path), "view": "cells", "sheet_name": name})
        assert result["success"] is True and result["source_status"] == "complete"
        values.update({(name, cell["address"]): cell for cell in result["cells"]})
    assert len(values) == 6
    assert values[("Sparse", "XFD1000000")]["value"] == 0
    assert values[("Sparse", "A1048576")]["value"] is False
    assert values[("Sparse", "XFD1048576")]["value"] == "last"
    assert values[("Sparse", "C3")]["cache_state"] == "missing"
    assert values[("Hidden", "B5")]["value"] == "retained"


def _biff2():
    """Minimal real binary XLS: two labels and two integers, read by installed xlrd."""

    def record(code, data=b""):
        return struct.pack("<HH", code, len(data)) + data

    body = record(0x0009, struct.pack("<HH", 7, 0x10))  # BIFF2 worksheet BOF
    body += record(0x0042, struct.pack("<H", 1252))  # CODEPAGE
    for column, label in enumerate((b"id", b"amount")):
        body += record(0x0004, struct.pack("<HH3sB", 0, column, b"\0" * 3, len(label)) + label)
    for column, value in enumerate((1, 7)):
        body += record(0x0002, struct.pack("<HH3sH", 1, column, b"\0" * 3, value))
    return body + record(0x000A)  # EOF


@pytest.mark.parametrize("suffix", [".csv", ".xls", ".xlsx"])
def test_normal_csv_binary_xls_and_dense_xlsx_routes(tmp_path, suffix):
    path = tmp_path / ("normal" + suffix)
    if suffix == ".csv":
        path.write_text("id,amount\n1,7\n", encoding="utf-8")
    elif suffix == ".xls":
        path.write_bytes(_biff2())
    else:
        _dense(path)
    with warnings.catch_warnings():
        warning_type = getattr(excel_analysis.pd.errors, "Pandas4Warning", None)
        if suffix == ".xls" and warning_type is not None:
            # pandas 3.1 deprecates xlrd; still exercise its real BIFF reader.
            warnings.filterwarnings(
                "always",
                message=(
                    r"^The xlrd engine is deprecated and will be removed in a future version\. "
                    r"Use the calamine engine instead, by setting engine='calamine'\.$"
                ),
                category=warning_type,
            )
        result = _analysis().analyze({"file_path": str(path), "header_row": 1})
    assert result["success"] is True and result["records"] == [{"id": 1, "amount": 7}]


def test_dense_budget_checks_only_the_selected_sheet(tmp_path):
    path = tmp_path / "mixed.xlsx"
    _dense(path)
    workbook = openpyxl.load_workbook(path)
    workbook.create_sheet("Far")["XFD1048576"] = "far"
    workbook.save(path)
    workbook.close()
    result = _analysis().analyze({"file_path": str(path), "header_row": 1})
    assert result["success"] is True and result["records"] == [{"id": 1, "amount": 7}]
    result = _analysis().analyze({"file_path": str(path), "sheet_name": "Far", "header_row": 1})
    assert result["error"] == "excel_dense_materialization_budget_exceeded"
