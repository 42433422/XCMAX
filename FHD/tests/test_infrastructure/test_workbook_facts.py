from __future__ import annotations

import hashlib
import importlib.util
import json
import posixpath
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from defusedxml import ElementTree as SafeET
from openpyxl import Workbook, load_workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles import PatternFill
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet._read_only import ReadOnlyWorksheet
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.formula import ArrayFormula
from openpyxl.worksheet.table import Table
from openpyxl.worksheet.worksheet import Worksheet

from app.application.tabular_workbook import WORKBOOK_SNAPSHOT_LIMIT_BYTES, read_workbook_facts
from app.infrastructure.document_parsing.archive_safety import OfficeArchiveError

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _body(workbook):
    result = BytesIO()
    workbook.save(result)
    workbook.close()
    return result.getvalue()


def _rewrite_sheet(body, edit):
    result = BytesIO()
    with ZipFile(BytesIO(body)) as source, ZipFile(result, "w") as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                root = SafeET.fromstring(data)
                edit(root)
                data = SafeET.tostring(root, encoding="utf-8")
            target.writestr(item, data)
    return result.getvalue()


def _facts(document, sheet=0):
    return {cell["address"]: cell for cell in document["sheets"][sheet]["cells"]}


@pytest.mark.parametrize(
    ("workbook_part", "relative_targets"),
    [("xl/renamed-book.payload", False), ("documents/nested/book.payload", True)],
)
def test_native_reader_resolves_the_real_workbook_part(tmp_path, workbook_part, relative_targets):
    from app.application.reviewed_excel_formula_cells import formula_facts
    from app.application.tools.workflow import handle_excel_analysis

    book = Workbook()
    book.active.append([0, False, "=A1+3"])

    def formula_cache(root):
        cell = next(cell for cell in root.iter(_NS + "c") if cell.attrib["r"] == "C1")
        cell.find(_NS + "v").text = "3"

    renamed = BytesIO()
    relationships = posixpath.join(
        posixpath.dirname(workbook_part), "_rels", posixpath.basename(workbook_part) + ".rels"
    )
    with (
        ZipFile(BytesIO(_rewrite_sheet(_body(book), formula_cache))) as original,
        ZipFile(renamed, "w") as target,
    ):
        for item in original.infolist():
            data, name = original.read(item.filename), item.filename
            if name in {"[Content_Types].xml", "_rels/.rels"}:
                data = data.replace(b"xl/workbook.xml", workbook_part.encode())
            elif name == "xl/workbook.xml":
                name = workbook_part
            elif name == "xl/_rels/workbook.xml.rels":
                name = relationships
                if relative_targets:
                    root = SafeET.fromstring(data)
                    for relation in root:
                        value = relation.attrib["Target"]
                        absolute = value.lstrip("/") if value.startswith("/") else "xl/" + value
                        relation.set(
                            "Target", posixpath.relpath(absolute, posixpath.dirname(workbook_part))
                        )
                    data = SafeET.tostring(root, encoding="utf-8")
            target.writestr(name, data)
    body = renamed.getvalue()
    native = load_workbook(BytesIO(body))
    assert native.active["A1"].value == 0 and native.active["B1"].value is False
    assert native.active["C1"].value == "=A1+3"
    native.close()
    assert formula_facts(body)[("Sheet", "C1")] == {
        "formula": "=A1+3",
        "cached": "3",
        "cache_missing": False,
    }

    digest = hashlib.sha256(body).hexdigest()
    document = read_workbook_facts(
        body, authorization_scope="tenant-a:user-1", expected_sha256=digest
    )
    assert document["status"] == "complete"
    assert document["archive_audit"]["worksheet_cell_elements"] == 3
    assert document["resource_budget"]["materialized_cells_upper_bound"] == 3
    assert document["source_ref"]["authorization_scope"] == "tenant-a:user-1"
    assert document["source_ref"]["source_sha256"] == digest
    assert document["sheets"][0]["native_part"] == "xl/worksheets/sheet1.xml"
    assert _facts(document)["A1"]["value"] == 0 and _facts(document)["B1"]["value"] is False
    formula = _facts(document)["C1"]
    assert formula["formula"] == "=A1+3" and formula["cached_value"] == 3
    assert formula["cache_state"] == "present_validity_unknown"
    assert formula["source_ref"] == {
        "document_id": document["document_id"],
        "sheet": "Sheet",
        "address": "C1",
    }

    source = tmp_path / "renamed.xlsx"
    source.write_bytes(body)
    result = handle_excel_analysis(
        {"file_path": source.name, "action": "read", "view": "cells", "sheet_name": "Sheet"},
        workspace_root=str(tmp_path),
    )
    assert result["success"] is True and result["source_status"] == "complete"
    assert [cell["value"] for cell in result["cells"]] == [0, False, "=A1+3"]
    assert result["cells"][2]["cached_value"] == 3
    assert result["source_sha256"] == digest


def test_native_cells_match_original_xml_and_preserve_values_without_dense_scan(monkeypatch):
    book = Workbook()
    sheet = book.active
    sheet["A1"], sheet["A2"], sheet["A3"], sheet["A4"] = "header", 0, False, ""
    sheet["B4"].fill = PatternFill("solid", fgColor="FF102030")
    sheet["C4"] = datetime(2026, 11, 27, 12, 30)
    sheet["D4"] = "#DIV/0!"
    sheet["E4"] = CellRichText("prefix ", TextBlock(InlineFont(b=True), "bold"))
    sheet["XFD1000000"] = "far"
    hidden = book.create_sheet("Hidden")
    hidden.sheet_state = "hidden"
    hidden["C9"] = "retained"
    book.create_sheet("Empty")
    secret = book.create_sheet("VeryHidden")
    secret.sheet_state = "veryHidden"
    secret["Z5"] = False
    body = _body(book)

    def forbidden(*args, **kwargs):
        raise AssertionError("native reading must not scan the worksheet rectangle")

    monkeypatch.setattr(Worksheet, "iter_rows", forbidden)
    document = read_workbook_facts(body, authorization_scope="tenant-a:user-1")
    facts = _facts(document)
    with ZipFile(BytesIO(body)) as source:
        expected = {
            node.attrib["r"]
            for node in SafeET.fromstring(source.read("xl/worksheets/sheet1.xml")).iter(_NS + "c")
        }
    assert set(facts) == expected
    assert document["status"] == "complete"
    assert facts["A2"]["value"] == 0 and type(facts["A2"]["value"]) is int
    assert facts["A3"]["value"] is False
    assert facts["A4"]["value"] == "" and facts["A4"]["value_state"] == "empty_string"
    assert facts["B4"]["value_state"] == "blank" and "B3" not in facts
    assert facts["C4"]["value_type"] == "datetime" and facts["C4"]["native_value"]
    assert facts["D4"]["value_type"] == "error"
    assert (
        facts["E4"]["value_type"] == "rich_text" and facts["E4"]["rich_text"][1]["text"] == "bold"
    )
    assert facts["XFD1000000"]["row"] == 1000000
    assert document["sheets"][1]["sheet_state"] == "hidden"
    assert document["sheets"][2]["cells"] == []
    assert document["sheets"][3]["sheet_state"] == "veryHidden"
    assert _facts(document, 3)["Z5"]["value"] is False
    assert document["native_objects"]["date_epoch"].startswith("1899-12-30")
    assert document["capabilities"]["formula_recalculation"] == "not_performed"


def test_formula_cache_is_original_evidence_and_not_recalculation(monkeypatch):
    book = Workbook()
    sheet = book.active
    sheet["A1"], sheet["A2"], sheet["A3"], sheet["A4"] = "=1+2", "=A1*2", '=""', "=1=1"

    def caches(root):
        for cell in root.iter(_NS + "c"):
            address = cell.attrib["r"]
            cached = cell.find(_NS + "v")
            if address == "A1":
                cached.text = "3"
            elif address == "A3":
                cell.attrib["t"] = "str"
                cached.text = ""
            elif address == "A4":
                cell.attrib["t"] = "b"
                cached.text = "1"

    monkeypatch.setattr(
        ReadOnlyWorksheet,
        "_get_row",
        lambda *a, **k: pytest.fail("cache must not materialize missing columns"),
    )
    facts = _facts(read_workbook_facts(_rewrite_sheet(_body(book), caches)))
    assert facts["A1"]["formula"] == "=1+2"
    assert facts["A1"]["cached_value"] == 3
    assert facts["A1"]["cache_state"] == "present_validity_unknown"
    assert facts["A2"]["cache_state"] == "missing"
    assert (
        facts["A3"]["cached_value"] == ""
        and facts["A3"]["cache_state"] == "present_validity_unknown"
    )
    assert facts["A4"]["cached_value"] is True


def test_native_objects_and_scope_identity_are_bound_to_exact_source():
    book = Workbook()
    sheet = book.active
    sheet.append(["name", "qty"])
    sheet.append(["item", 2])
    sheet.add_table(Table(displayName="Items", ref="A1:B2"))
    sheet.add_data_validation(
        DataValidation(type="whole", operator="between", formula1="1", formula2="9", sqref="B2:B8")
    )
    sheet.auto_filter.ref = "A1:B2"
    sheet.print_area = "A1:B8"
    sheet.freeze_panes = "B2"
    sheet.row_dimensions[2].hidden = True
    sheet.column_dimensions["B"].hidden = True
    book.defined_names.add(DefinedName("Inventory", attr_text="'Sheet'!$A$1:$B$2"))
    body = _body(book)
    first = read_workbook_facts(
        body, authorization_scope="a", expected_sha256=hashlib.sha256(body).hexdigest()
    )
    same = read_workbook_facts(body, authorization_scope="a")
    other = read_workbook_facts(body, authorization_scope="b")
    assert first["document_id"] == same["document_id"] != other["document_id"]
    assert _facts(first)["A1"]["cell_id"] == _facts(same)["A1"]["cell_id"]
    assert _facts(first)["A1"]["cell_id"] != _facts(other)["A1"]["cell_id"]
    native = first["sheets"][0]["native_objects"]
    assert native["tables"][0]["range"] == "A1:B2"
    assert 'sqref="B2:B8"' in native["data_validations_xml"]
    assert native["freeze_panes"] == "B2"
    assert first["native_objects"]["defined_names"][0]["name"] == "Inventory"
    assert first["sheets"][0]["dimensions"]["rows"][0]["hidden"] is True
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        read_workbook_facts(body, expected_sha256="0" * 64)


def test_shared_and_array_formula_native_attributes_survive():
    book = Workbook()
    sheet = book.active
    sheet["A1"], sheet["A2"] = "=B1+1", "=B2+1"
    sheet["B1"], sheet["B2"] = 3, 4
    sheet["C1"] = ArrayFormula(ref="C1:C2", text="=B1:B2*2")

    def shared(root):
        for cell in root.iter(_NS + "c"):
            if cell.attrib["r"] not in {"A1", "A2"}:
                continue
            formula = cell.find(_NS + "f")
            formula.attrib.update(t="shared", si="0")
            if cell.attrib["r"] == "A1":
                formula.attrib["ref"] = "A1:A2"
            else:
                formula.text = None

    facts = _facts(read_workbook_facts(_rewrite_sheet(_body(book), shared)))
    assert facts["A2"]["formula"] == "=B2+1"
    assert facts["A2"]["formula_attributes"] == {"t": "shared", "si": "0"}
    assert facts["C1"]["formula"] == "=B1:B2*2"
    assert facts["C1"]["formula_attributes"] == {"t": "array", "ref": "C1:C2"}
    assert facts["C1"]["cache_state"] == "missing"


def test_library_normalized_merge_content_is_retained_and_marked_partial():
    book = Workbook()
    sheet = book.active
    sheet["A1"] = "anchor"
    sheet.merge_cells("A1:B1")

    def add_native_value(root):
        row = next(root.iter(_NS + "row"))
        node = SafeET.fromstring(f'<c xmlns="{_NS[1:-1]}" r="B1" t="n"><v>42</v></c>')
        row.append(node)

    document = read_workbook_facts(_rewrite_sheet(_body(book), add_native_value))
    fact = _facts(document)["B1"]
    assert document["status"] == "partial"
    assert fact["native_value"] == "42" and fact["value_state"] == "unknown"
    assert "42" in fact["native_xml"]


def test_reader_legacy_caps_do_not_truncate_canonical_facts(tmp_path, monkeypatch):
    path = (
        Path(__file__).resolve().parents[2]
        / "mods/_employees/excel-full-read-employee/backend/vendor/excel_full_read/convert.py"
    )
    spec = importlib.util.spec_from_file_location("native_reader_compat", path)
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    book = Workbook()
    book.active["A1"] = "name"
    book.active["A2"] = "item"
    book.active["B2"] = datetime(2026, 11, 27, 12, 30)
    book.active["XFD1000000"] = 7
    source = tmp_path / "source.xlsx"
    source.write_bytes(_body(book))
    monkeypatch.setattr(Worksheet, "iter_rows", lambda *a, **k: pytest.fail("dense scan"))
    target = tmp_path / "workbook.json"
    reader.convert_file(
        source,
        target,
        payload={"max_row_cap": 2, "max_col_cap": 2, "header_row": 1},
        ctx={"user_id": 1, "tenant_id": "a"},
        rule_spec={},
    )
    result = json.loads(target.read_text())
    assert result["sheets"][0]["truncated"] is True
    assert result["sheets"][0]["rows"] == [{"name": "item", "col_2": "2026-11-27 12:30:00"}]
    assert _facts(result["document"])["XFD1000000"]["value"] == 7
    assert result["document"]["capabilities"]["authorization"] == "bound"


def test_reader_serialization_failure_preserves_previous_artifact(tmp_path, monkeypatch):
    path = (
        Path(__file__).resolve().parents[2]
        / "mods/_employees/excel-full-read-employee/backend/vendor/excel_full_read/convert.py"
    )
    spec = importlib.util.spec_from_file_location("native_reader_atomic", path)
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    book = Workbook()
    book.active["A1"] = "data"
    source = tmp_path / "source.xlsx"
    source.write_bytes(_body(book))
    target = tmp_path / "workbook.json"
    target.write_text('{"previous":"verified"}')

    def failed_dump(handle, payload, encoder):
        handle.write('{"partial":')
        raise OSError("injected disk write failure")

    monkeypatch.setattr(reader, "_write_json", failed_dump)
    with pytest.raises(OSError, match="injected"):
        reader.convert_file(source, target, payload={}, ctx={}, rule_spec={})
    assert json.loads(target.read_text()) == {"previous": "verified"}
    assert sorted(item.name for item in tmp_path.iterdir()) == ["source.xlsx", "workbook.json"]


def test_oversized_snapshot_is_rejected_before_unbounded_read(tmp_path, monkeypatch):
    source = tmp_path / "large.xlsx"
    with source.open("wb") as handle:
        handle.truncate(WORKBOOK_SNAPSHOT_LIMIT_BYTES + 1024 * 1024)
    original_open = Path.open
    sizes = []

    class GuardedReader:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def read(self, size=-1):
            sizes.append(size)
            assert size == WORKBOOK_SNAPSHOT_LIMIT_BYTES + 1
            return self.handle.read(size)

    def guarded_open(path, mode="r", *args, **kwargs):
        handle = original_open(path, mode, *args, **kwargs)
        return GuardedReader(handle) if path == source and mode == "rb" else handle

    monkeypatch.setattr(Path, "open", guarded_open)
    with pytest.raises(OfficeArchiveError, match="office_compressed_budget_exceeded"):
        read_workbook_facts(source)
    assert sizes == [WORKBOOK_SNAPSHOT_LIMIT_BYTES + 1]


def test_duplicate_header_keys_preserve_every_original_column(tmp_path):
    path = (
        Path(__file__).resolve().parents[2]
        / "mods/_employees/excel-full-read-employee/backend/vendor/excel_full_read/convert.py"
    )
    spec = importlib.util.spec_from_file_location("native_reader_duplicate_columns", path)
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    book = Workbook()
    book.active.append(["A", "A", "A_2"])
    book.active.append([10, 20, 30])
    source = tmp_path / "source.xlsx"
    source.write_bytes(_body(book))
    target = tmp_path / "workbook.json"
    reader.convert_file(source, target, payload={"header_row": 1}, ctx={}, rule_spec={})
    result = json.loads(target.read_text())
    assert result["sheets"][0]["columns"] == ["A", "A_3", "A_2"]
    assert result["sheets"][0]["rows"] == [{"A": 10, "A_3": 20, "A_2": 30}]
    assert _facts(result["document"])["B1"]["value"] == "A"


def test_native_materialization_budget_rejects_real_large_archive_before_load(
    tmp_path, monkeypatch
):
    from app.application import tabular_workbook

    # Actual 500005 native c elements: the ZIP/XML resource audit runs normally;
    # expensive formula and openpyxl loading must not begin.
    source = tmp_path / "over-materialization-budget.xlsx"
    with (
        ZipFile(BytesIO(_body(Workbook()))) as template,
        ZipFile(source, "w", compression=ZIP_DEFLATED) as output,
    ):
        for item in template.infolist():
            if item.filename != "xl/worksheets/sheet1.xml":
                output.writestr(item, template.read(item.filename))
        with output.open("xl/worksheets/sheet1.xml", "w") as stream:
            stream.write(f'<worksheet xmlns="{_NS[1:-1]}"><sheetData>'.encode())
            for row in range(1, 100002):
                cells = "".join(f'<c r="{column}{row}" t="n"><v>0</v></c>' for column in "ABCDE")
                stream.write(f'<row r="{row}">{cells}</row>'.encode())
            stream.write(b"</sheetData></worksheet>")

    def forbidden(*args, **kwargs):
        pytest.fail("native objects must not be loaded over the declared budget")

    monkeypatch.setattr(tabular_workbook, "build_workbook_facts", forbidden)
    with pytest.raises(OfficeArchiveError, match="tabular_native_materialization_budget_exceeded"):
        read_workbook_facts(source)


@pytest.mark.parametrize("mac_epoch", [False, True])
def test_formula_cache_decoding_reuses_native_nodes_and_one_workbook_load(monkeypatch, mac_epoch):
    from datetime import date, time, timedelta

    from openpyxl.utils.datetime import CALENDAR_MAC_1904

    from app.domain.tabular_facts import location_id
    from app.infrastructure.excel import workbook_facts
    from app.infrastructure.excel.sparse_rows import iter_present_cells

    book = Workbook()
    if mac_epoch:
        book.epoch = CALENDAR_MAC_1904
    sheet = book.active
    specifications = {
        "A1": ("=1+2", "n", "3", "General"),
        "A2": ("=1/2", "n", "0.5", "General"),
        "A3": ("=DATE(2026,11,27)", "n", "46353", "yyyy-mm-dd"),
        "A4": ("=1/24", "n", "0.04166666666666666", "[h]:mm:ss"),
        "A5": ("=TRUE()", "b", "1", "General"),
        "A6": ("=NA()", "e", "#N/A", "General"),
        "A7": ('="汉字"', "str", "汉字", "General"),
        "A8": ('=""', "str", "", "General"),
        "A9": ("=0", "n", None, "General"),
        "A10": ('="共享文本"', "s", "0", "General"),
        "A11": ("=NOW()", "d", "2026-11-27T12:34:56", "General"),
        "F1": ("=A1+1", "n", "4", "General"),
        "F2": ("=A2+1", "n", "1.5", "General"),
    }
    for address, (formula, _, _, number_format) in specifications.items():
        sheet[address] = formula
        sheet[address].number_format = number_format
    sheet["D1"] = "anchor"
    sheet.merge_cells("D1:E1")
    sheet["G1"] = ArrayFormula(ref="G1:G2", text="=A1:A2*2")

    def caches(root):
        for cell in root.iter(_NS + "c"):
            address = cell.attrib["r"]
            if address not in specifications:
                continue
            _, kind, value, _ = specifications[address]
            cell.set("t", kind)
            cell.find(_NS + "v").text = value
            if address in {"F1", "F2"}:
                formula = cell.find(_NS + "f")
                formula.set("t", "shared")
                formula.set("si", "0")
                if address == "F1":
                    formula.set("ref", "F1:F2")
                else:
                    formula.text = None
        next(root.iter(_NS + "row")).append(
            SafeET.fromstring(f'<c xmlns="{_NS[1:-1]}" r="E1"><f> 20+22 </f><v>42</v></c>')
        )

    edited = BytesIO()
    with (
        ZipFile(BytesIO(_rewrite_sheet(_body(book), caches))) as original,
        ZipFile(edited, "w") as target,
    ):
        for item in original.infolist():
            data = original.read(item.filename)
            if item.filename == "[Content_Types].xml":
                root = SafeET.fromstring(data)
                root.append(
                    SafeET.fromstring(
                        '<Override xmlns="http://schemas.openxmlformats.org/package/2006/content-types" '
                        'PartName="/xl/sharedStrings.xml" '
                        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
                    )
                )
                data = SafeET.tostring(root)
            elif item.filename == "xl/_rels/workbook.xml.rels":
                root = SafeET.fromstring(data)
                root.append(
                    SafeET.fromstring(
                        '<Relationship xmlns="http://schemas.openxmlformats.org/package/2006/relationships" '
                        'Id="rIdSharedStrings" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" '
                        'Target="sharedStrings.xml"/>'
                    )
                )
                data = SafeET.tostring(root)
            target.writestr(item, data)
        target.writestr(
            "xl/sharedStrings.xml", f'<sst xmlns="{_NS[1:-1]}"><si><t>共享文本</t></si></sst>'
        )
    body = edited.getvalue()
    reference = load_workbook(BytesIO(body), read_only=True, data_only=True)
    expected = {
        cell.coordinate: (cell.value, cell.data_type)
        for cell in iter_present_cells(reference.active)
    }
    reference.close()
    reads = []
    native_read = workbook_facts.ExcelReader.read

    def counted_read(reader):
        reads.append(reader.data_only)
        return native_read(reader)

    monkeypatch.setattr(workbook_facts.ExcelReader, "read", counted_read)
    document = workbook_facts.build_workbook_facts(
        body, source_name="cache.xlsx", authorization_scope="tenant-a"
    )
    facts = _facts(document)
    for address in [*specifications, "E1"]:
        value, data_type = expected[address]
        if isinstance(value, (datetime, date, time)):
            value = value.isoformat()
        elif isinstance(value, timedelta):
            value = value.total_seconds()
        if address == "A8":
            value = ""
        assert facts[address]["cached_value"] == value
        assert facts[address]["cached_data_type"] == data_type
        assert facts[address]["cell_id"] == location_id(
            document["document_id"], "cell", "Sheet", address
        )
    assert facts["A5"]["cached_value"] is True
    assert facts["A8"]["cache_state"] == "present_validity_unknown"
    assert facts["A9"]["cache_state"] == "missing"
    assert facts["A10"]["cached_value"] == "共享文本"
    assert (
        facts["E1"]["formula"] == "=20+22" and facts["E1"]["normalization_state"] == "source_only"
    )
    assert facts["F2"]["formula"] == "=A2+1"
    assert facts["G1"]["formula"] == "=A1:A2*2"
    assert reads == [False]
