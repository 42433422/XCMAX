"""Real native-file regressions; fixtures are synthetic, not customer acceptance."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from docx import Document
from pptx import Presentation
from pptx.util import Inches
from reportlab.pdfgen.canvas import Canvas

from app.infrastructure.document_parsing import native, router
from app.infrastructure.document_parsing.delimited import column_keys, open_delimited


def _employee(kind: str):
    path = (
        Path(__file__).parents[1]
        / "mods"
        / "_employees"
        / f"{kind}-full-read-employee"
        / "backend"
        / "vendor"
        / f"{kind}_full_read"
        / "convert.py"
    )
    spec = importlib.util.spec_from_file_location(f"tabular_test_{kind}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_csv_employee_preserves_duplicate_headers_empty_values_and_quoted_lines(tmp_path):
    source = tmp_path / "source.csv"
    source.write_bytes(b'name,name,,name__2\r\n" a ","line1\r\nline2",,0\r\n')
    output = tmp_path / "out.json"
    _employee("csv").convert_file(source, output, payload={}, ctx={}, rule_spec={})
    result = json.loads(output.read_text())
    assert result["columns"] == ["name", "name", "", "name__2"]
    keys = result["column_keys"]
    assert len(set(keys)) == 4
    assert list(result["rows"][0].values()) == [" a ", "line1\r\nline2", "", "0"]
    facts = result["document_facts"]
    assert facts["source_ref"]["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert facts["tables"][0]["records"][1] == {
        "record": 2,
        "line_start": 2,
        "line_end": 3,
        "width": 4,
    }
    assert facts["tables"][0]["cells"][6]["value_state"] == "empty_string"


def test_shared_csv_reader_preserves_whitespace_and_tsv_delimiter(tmp_path):
    path = tmp_path / "records.tsv"
    path.write_text('a\tb\n" x "\t"first\nsecond"\n', newline="")
    handle, reader, meta = open_delimited(path)
    with handle:
        assert list(reader) == [["a", "b"], [" x ", "first\nsecond"]]
    assert meta["delimiter"] == "\t"
    assert native.read_native_document(path)["status"] == "complete"


@pytest.mark.parametrize("header", ["", "same"])
def test_wide_native_header_projection_keeps_every_column_distinct(header):
    original = [header] * 10_000
    keys = column_keys(original, len(original))
    assert len(set(keys)) == len(original)
    assert original == [header] * 10_000
    assert dict(zip(keys, range(len(keys))))[keys[-1]] == 9999


def test_elt_tsv_shares_decoder_and_preserves_multiline_source_positions(tmp_path):
    from app.application.elt.parsers import parse_file
    from app.application.elt.upload_content_gate import check_declared_mime, check_stored_content
    from app.application.office_parse_app_service import resolve_office_read_employee

    path = tmp_path / "source.tsv"
    path.write_text(
        '产品型号\t产品名称\t数量\nA01\t"first\nsecond"\t0\nB01\tbottom\t2\n', newline=""
    )
    check_declared_mime(".tsv", "text/tab-separated-values")
    check_stored_content(path, ".tsv")
    assert resolve_office_read_employee(path.name) == "csv-full-read-employee"
    dataset = parse_file(path, target_type="products")
    try:
        assert len(dataset.rows) == 2
        assert dataset.rows[0].provenance["original_values"] == ["A01", "first\nsecond", "0"]
        assert dataset.rows[0].provenance["physical_line_start"] == 2
        assert dataset.rows[0].provenance["physical_line_end"] == 3
        assert dataset.rows[1].provenance["physical_line_start"] == 4
    finally:
        dataset.close()


def test_csv_late_encoding_error_is_detected_before_emitting_rows(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_bytes(b"a,b\n" + b"1,2\n" * 3000 + b"\xff\xff")
    with pytest.raises(ValueError, match="encoding"):
        open_delimited(path)


def test_csv_budget_is_partial_and_employee_refuses_false_full_read(tmp_path, monkeypatch):
    path = tmp_path / "data.csv"
    path.write_text("a,b\n1,2\n3,4\n")
    monkeypatch.setattr(native, "MAX_NATIVE_ITEMS", 4)
    facts = native.read_native_document(path)
    assert facts["status"] == "partial"
    with pytest.raises(ValueError, match="全量读取未完成"):
        _employee("csv").convert_file(path, tmp_path / "out.json", payload={}, ctx={}, rule_spec={})
    assert not (tmp_path / "out.json").exists()


def test_json_nested_values_are_not_flattened_or_coerced(tmp_path):
    path = tmp_path / "data.json"
    original = {"items": [{"zero": 0, "flag": False, "missing": None, "empty": ""}], "empty": []}
    path.write_text(json.dumps(original))
    facts = native.read_native_document(path)
    assert facts["regions"][0]["value"] == original
    assert facts["regions"][0]["source_ref"]["json_pointer"] == ""
    assert facts["tables"] == []


@pytest.mark.parametrize("raw", ['{"same":1,"same":2}', '{"number":NaN}'])
def test_ambiguous_json_is_rejected(tmp_path, raw):
    path = tmp_path / "data.json"
    path.write_text(raw)
    with pytest.raises(ValueError):
        native.read_native_document(path)


def test_xml_preserves_namespaces_attributes_order_and_tails(tmp_path):
    path = tmp_path / "data.xml"
    path.write_text('<r xmlns="urn:test">lead<x id="1">a</x>between<x id="2"/>tail</r>')
    tree = native.read_native_document(path)["regions"][0]["value"]
    assert tree["tag"] == "{urn:test}r"
    assert tree["text"] == "lead"
    assert tree["children"][0]["tail"] == "between"
    assert tree["children"][1]["attributes"] == {"id": "2"}
    assert tree["children"][1]["source_ref"]["xml_path"].endswith("/{urn:test}x[2]")


def test_xml_entities_are_never_resolved(tmp_path):
    path = tmp_path / "data.xml"
    path.write_text('<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><r>&x;</r>')
    from defusedxml.common import DefusedXmlException

    with pytest.raises(DefusedXmlException):
        native.read_native_document(path)


def test_word_order_merged_cells_nested_tables_and_empty_paragraphs(tmp_path):
    path = tmp_path / "document.docx"
    doc = Document()
    doc.add_paragraph("")
    doc.add_paragraph("before")
    table = doc.add_table(rows=3, cols=3)
    table.cell(0, 0).merge(table.cell(0, 1)).text = "wide"
    table.cell(1, 2).merge(table.cell(2, 2)).text = "tall"
    table.cell(1, 0).add_table(rows=1, cols=1).cell(0, 0).text = "nested"
    doc.add_paragraph("after")
    doc.save(path)
    facts = native.read_native_document(path)
    main_table = next(item for item in facts["tables"] if "/tc[" not in item["source_ref"]["part"])
    wide = next(cell for cell in main_table["cells"] if cell["value"] == "wide")
    assert wide["column_span"] == 2
    assert wide["source_ref"]["column"] == 1
    assert {cell["vertical_merge"] for cell in main_table["cells"]} >= {"restart", "continue"}
    assert any(cell["value"] == "nested" for item in facts["tables"] for cell in item["cells"])
    main_blocks = [
        item
        for item in facts["regions"]
        if "/tc[" not in item["source_ref"]["part"]
        and "word/document.xml" in item["source_ref"]["part"]
    ]
    assert [item["kind"] for item in main_blocks] == [
        "paragraph",
        "paragraph",
        "table",
        "paragraph",
    ]
    employee = _employee("word")
    extracted = employee._extract_docx_ooxml(path, tmp_path / "output")
    assert [b["text"] for b in extracted["blocks"] if b["type"] == "paragraph"] == [
        "before",
        "after",
    ]
    assert extracted["document_facts"]["document_id"] == facts["document_id"]


def test_ppt_employee_keeps_table_merge_and_shape_geometry(tmp_path):
    path = tmp_path / "deck.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    shape = slide.shapes.add_table(2, 3, Inches(1), Inches(2), Inches(4), Inches(1))
    shape.table.cell(0, 0).merge(shape.table.cell(0, 1))
    shape.table.cell(0, 0).text = "combined"
    shape.table.cell(1, 2).text = "0"
    prs.save(path)
    payload, _images = _employee("ppt")._extract_pptx(path)
    facts = payload["document_facts"]
    cell = next(c for c in facts["tables"][0]["cells"] if c["value"] == "combined")
    assert cell["column_span"] == 2
    assert cell["source_ref"]["bbox"] == [914400, 1828800, 4572000, 2743200]
    assert cell["source_ref"]["coordinate_unit"] == "EMU"
    assert len(facts["tables"][0]["cells"]) == 5


def test_pdf_retains_real_native_cell_bboxes_and_marks_scan_pages(tmp_path):
    path = tmp_path / "table.pdf"
    canvas = Canvas(str(path), pagesize=(300, 300))
    for x in (20, 120, 220):
        canvas.line(x, 100, x, 200)
    for y in (100, 150, 200):
        canvas.line(20, y, 220, y)
    canvas.drawString(30, 175, "Item")
    canvas.drawString(130, 175, "Count")
    canvas.drawString(30, 125, "A")
    canvas.drawString(130, 125, "0")
    canvas.showPage()
    canvas.showPage()
    canvas.save()
    facts = native.read_native_document(path)
    assert len(facts["pages"]) == 2
    assert facts["tables"][0]["cells"][0]["source_ref"]["bbox"] == [20.0, 100.0, 120.0, 150.0]
    assert [cell["value"] for cell in facts["tables"][0]["cells"]] == ["Item", "Count", "A", "0"]
    assert facts["status"] == "partial"
    assert {"code": "page_2_requires_ocr"} in facts["warnings"]


def test_html_spans_and_static_origin_without_script_execution(tmp_path):
    path = tmp_path / "table.html"
    path.write_text(
        '<table><tr><th rowspan="2">A</th><th colspan="2">B</th></tr><tr><td>0</td><td></td></tr></table><script>throw "not run";</script>'
    )
    facts = native.read_native_document(path)
    cells = facts["tables"][0]["cells"]
    assert [(cell["value"], cell["source_ref"]["column"]) for cell in cells] == [
        ("A", 1),
        ("B", 2),
        ("0", 2),
        ("", 3),
    ]
    assert cells[0]["row_span"] == 2
    assert cells[1]["column_span"] == 2
    assert all(cell["source_ref"]["node_path"].startswith("/html/") for cell in cells)
    assert facts["capabilities"]["script_execution"] is False
    assert facts["status"] == "partial"


def test_html_document_budget_is_shared_by_all_tables(tmp_path, monkeypatch):
    one_table = "<table><tr>" + "<td>x</td>" * 6 + "</tr></table>"
    path = tmp_path / "tables.html"
    monkeypatch.setattr(native, "MAX_NATIVE_ITEMS", 10)
    path.write_text(one_table)
    assert native.read_native_document(path)["status"] == "complete"
    path.write_text(one_table * 2)
    with pytest.raises(ValueError, match="HTML native item budget"):
        native.read_native_document(path)


def test_html_expired_spans_do_not_consume_future_placement_budget(tmp_path, monkeypatch):
    path = tmp_path / "repeated.html"
    monkeypatch.setattr(native, "MAX_NATIVE_ITEMS", 1000)
    path.write_text("<table>" + '<tr><td rowspan="2">value</td></tr>' * 250 + "</table>")
    facts = native.read_native_document(path)
    assert facts["status"] == "complete"
    cells = facts["tables"][0]["cells"]
    assert len(cells) == 250
    assert {cell["source_ref"]["column"] for cell in cells} == {1, 2}


def test_html_active_span_work_has_an_explicit_budget(tmp_path, monkeypatch):
    path = tmp_path / "active.html"
    monkeypatch.setattr(native, "MAX_NATIVE_ITEMS", 400)
    path.write_text("<table>" + '<tr><td rowspan="200">value</td></tr>' * 100 + "</table>")
    with pytest.raises(ValueError, match="HTML span placement budget"):
        native.read_native_document(path)


def test_html_depth_failure_is_not_recovered_as_complete_empty_document(tmp_path, monkeypatch):
    path = tmp_path / "deep.html"
    path.write_text("<div>" * 300 + "<table><tr><td>value</td></tr></table>" + "</div>" * 300)
    monkeypatch.setenv("XCAGI_DOC_PARSER", "legacy")
    _text, _parser, metadata = router.parse_document(path, lambda: ("value", "legacy", {}))
    assert metadata["structure_status"] == "blocked"
    assert "document_facts" not in metadata


def test_ppt_document_budget_is_shared_by_all_slides_and_tables(tmp_path, monkeypatch):
    path = tmp_path / "tables.pptx"
    presentation = Presentation()
    monkeypatch.setattr(native, "MAX_NATIVE_ITEMS", 8)
    for _index in range(2):
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        slide.shapes.add_table(2, 2, 0, 0, Inches(2), Inches(1))
        presentation.save(path)
        if len(presentation.slides) == 1:
            assert native.read_native_document(path)["status"] == "complete"
    with pytest.raises(ValueError, match="PPTX native item budget"):
        native.read_native_document(path)


def test_ppt_groups_have_a_depth_budget(tmp_path, monkeypatch):
    path = tmp_path / "groups.pptx"
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    children = slide.shapes
    for _index in range(4):
        children = children.add_group_shape().shapes
    children.add_textbox(0, 0, Inches(1), Inches(1)).text = "deep"
    presentation.save(path)
    monkeypatch.setattr(native, "MAX_GROUP_DEPTH", 2)
    with pytest.raises(ValueError, match="PPTX group nesting"):
        native.read_native_document(path)


def test_unqualified_formats_are_unsupported(tmp_path):
    for suffix in (".xlsb", ".ods", ".parquet", ".doc", ".ppt"):
        path = tmp_path / f"data{suffix}"
        path.write_bytes(b"fixture")
        assert native.read_native_document(path)["status"] == "unsupported"


def test_docling_keeps_native_export_and_provenance(tmp_path, monkeypatch):
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"contract fixture, not a real Docling inference")
    exported = {
        "tables": [
            {
                "self_ref": "#/tables/0",
                "data": {"num_rows": 2},
                "prov": [{"page_no": 1, "bbox": {"l": 5}}],
            }
        ],
        "texts": [{"self_ref": "#/texts/0", "text": "body"}],
        "pages": {"1": {"size": {"width": 100, "height": 200}}},
    }
    document = SimpleNamespace(
        export_to_markdown=lambda: "text",
        export_to_dict=lambda: exported,
        tables=exported["tables"],
        pages=exported["pages"],
    )
    converter = SimpleNamespace(
        DocumentConverter=lambda: SimpleNamespace(
            convert=lambda _: SimpleNamespace(document=document, status="success")
        )
    )
    monkeypatch.setitem(sys.modules, "docling.document_converter", converter)
    monkeypatch.setattr(router.importlib.metadata, "version", lambda _: "fixture-contract-version")
    parsed = router.parse_with_docling(source)
    facts = parsed.metadata["document_facts"]
    assert facts["native_extensions"]["docling_document"] == exported
    assert facts["tables"][0]["native_object"]["prov"] == exported["tables"][0]["prov"]
    assert facts["tables"][0]["source_ref"]["document_id"] == facts["document_id"]


def test_docling_source_change_verification_does_not_read_an_unbounded_file(tmp_path, monkeypatch):
    source = tmp_path / "changed.pdf"
    source.write_bytes(b"contract fixture")
    document = SimpleNamespace(export_to_markdown=lambda: "text")

    def convert(_path):
        with source.open("wb") as handle:
            handle.truncate(native.MAX_SOURCE_BYTES + 1)
        return SimpleNamespace(document=document, status="success")

    converter = SimpleNamespace(DocumentConverter=lambda: SimpleNamespace(convert=convert))
    monkeypatch.setitem(sys.modules, "docling.document_converter", converter)
    monkeypatch.setattr(Path, "read_bytes", lambda _self: pytest.fail("unbounded file read"))
    with pytest.raises(ValueError, match="Document changed"):
        router.parse_with_docling(source)


def test_router_keeps_plain_text_but_never_calls_it_complete_structure(tmp_path, monkeypatch):
    path = tmp_path / "bad.pdf"
    path.write_bytes(b"not a document")
    monkeypatch.setenv("XCAGI_DOC_PARSER", "legacy")
    text, parser, metadata = router.parse_document(path, lambda: ("text fallback", "legacy", {}))
    assert text == "text fallback"
    assert metadata["structure_status"] == "blocked"
    assert "document_facts" not in metadata


@pytest.mark.parametrize(
    "suffix,backend",
    [(".docx", "docx"), (".pptx", "pptx"), (".pdf", "pdfplumber"), (".html", "lxml")],
)
def test_each_native_format_marks_missing_backend_as_blocked(
    tmp_path, monkeypatch, suffix, backend
):
    """An available text lane cannot qualify a missing native structure backend."""
    source = tmp_path / f"document{suffix}"
    if suffix == ".docx":
        doc = Document()
        doc.add_table(rows=1, cols=1).cell(0, 0).text = "native value"
        doc.save(source)
    elif suffix == ".pptx":
        presentation = Presentation()
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        slide.shapes.add_table(1, 1, 0, 0, Inches(2), Inches(1)).table.cell(
            0, 0
        ).text = "native value"
        presentation.save(source)
    elif suffix == ".pdf":
        canvas = Canvas(str(source))
        canvas.drawString(20, 40, "native value")
        canvas.save()
    else:
        source.write_text("<table><tr><td>native value</td></tr></table>")
    original = source.read_bytes()
    assert native.read_native_document(source)["status"] == "complete"
    monkeypatch.setenv("XCAGI_DOC_PARSER", "auto")
    monkeypatch.setattr(router, "docling_available", lambda: False)
    monkeypatch.setitem(sys.modules, backend, None)
    text, parser, metadata = router.parse_document(
        source, lambda: ("retained text", "independent-text-lane", {})
    )
    assert (text, parser) == ("retained text", "independent-text-lane")
    assert metadata["structure_status"] == "blocked"
    assert "document_facts" not in metadata
    assert "ModuleNotFoundError" in metadata["structure_error"]
    assert source.read_bytes() == original


@pytest.mark.parametrize("suffix", [".docx", ".pptx"])
def test_unsafe_office_package_is_rejected_before_legacy_parser(tmp_path, monkeypatch, suffix):
    path = tmp_path / f"bad{suffix}"
    path.write_bytes(b"not an Office package")
    monkeypatch.setenv("XCAGI_DOC_PARSER", "legacy")
    calls = []
    with pytest.raises(ValueError, match="office_invalid_or_unsafe_archive"):
        router.parse_document(path, lambda: calls.append(path))
    assert calls == []


def test_office_size_budget_precedes_legacy_parser_and_full_file_read(tmp_path, monkeypatch):
    path = tmp_path / "large.docx"
    with path.open("wb") as handle:
        handle.truncate(native.MAX_SOURCE_BYTES + 1)
    monkeypatch.setenv("XCAGI_DOC_PARSER", "legacy")
    monkeypatch.setattr(Path, "read_bytes", lambda _self: pytest.fail("unbounded file read"))
    calls = []
    with pytest.raises(ValueError, match="office_compressed_budget_exceeded"):
        router.parse_document(path, lambda: calls.append(path))
    assert calls == []
