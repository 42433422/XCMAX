from __future__ import annotations

import hashlib
import json

import pytest
from openpyxl import load_workbook

from app.application.elt.table_structure_ocr import (
    TableGrid,
    html_to_grid,
    recognize_table_pages,
    recognize_table_structures,
)
from app.application.shipment_excel_elt_ocr import tables_to_workbook_path

_TABLE_HTML = """
<table>
  <tr><td rowspan="2">客户</td><td colspan="2">数量</td></tr>
  <tr><td>桶数</td><td>公斤</td></tr>
  <tr><td>张三</td><td>3</td><td>90</td></tr>
</table>
"""


class _FakePipeline:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def predict(self, input=None, **kwargs):
        self.calls += 1
        return [{"res": self.payload}]


def test_html_to_grid_keeps_spans_and_merge_ranges():
    grid, merges = html_to_grid(_TABLE_HTML)

    assert grid == [
        ["客户", "数量", ""],
        ["", "桶数", "公斤"],
        ["张三", "3", "90"],
    ]
    assert merges == [(1, 1, 2, 1), (1, 2, 1, 3)]


def test_recognize_table_structures_reads_pipeline_payload():
    pipeline = _FakePipeline(
        {
            "table_res_list": [{"pred_html": _TABLE_HTML}],
            "parsing_res_list": [
                {"block_label": "text", "block_content": "客户：张三"},
                {"block_label": "text", "block_content": "无关说明"},
            ],
        }
    )

    tables = recognize_table_structures([object()], pipeline=pipeline)

    assert pipeline.calls == 1
    assert len(tables) == 1
    assert tables[0].page == 1
    assert tables[0].meta_lines == ["客户：张三"]
    assert tables[0].merges == [(1, 1, 2, 1), (1, 2, 1, 3)]


def test_recognize_table_structures_returns_empty_without_a_pipeline(monkeypatch):
    monkeypatch.setattr(
        "app.application.elt.table_structure_ocr.get_table_structure_pipeline",
        lambda: None,
    )

    assert recognize_table_structures([object()]) == []


def test_tables_to_workbook_path_writes_each_table_with_merges(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    tables = [
        TableGrid(grid=[["客户", "数量"], ["张三", "3"]], page=1),
        TableGrid(
            grid=[["客户", "数量", "数量"], ["", "桶数", "公斤"], ["张三", "3", "90"]],
            merges=[(1, 1, 2, 1), (1, 2, 1, 3)],
            page=2,
            meta_lines=["客户：李四"],
        ),
    ]

    path = tables_to_workbook_path(
        tables,
        output_path=tmp_path / "structured.xlsx",
        sheet_name="OCR",
        meta_lines=["客户：张三"],
    )

    workbook = load_workbook(path)
    try:
        assert workbook.sheetnames == ["OCR_1", "OCR_2"]
        first = workbook["OCR_1"]
        assert first["A1"].value == "客户：张三"
        assert first["A2"].value == "客户"
        assert not list(first.merged_cells.ranges)
        second = workbook["OCR_2"]
        # 每张表自带 meta 行，合并区域随之下移一行
        assert second["A1"].value == "客户：李四"
        assert second["A2"].value == "客户"
        assert sorted(str(item) for item in second.merged_cells.ranges) == ["A2:A3", "B2:C2"]
    finally:
        workbook.close()


def test_blank_and_merged_trailing_rows_are_not_discarded():
    grid, merges = html_to_grid(
        '<table><tr><td rowspan="2">x</td><td>y</td></tr><tr><td></td></tr></table>'
    )
    assert grid == [["x", "y"], ["", ""]]
    assert merges == [(1, 1, 2, 1)]


def test_overlapping_and_unbounded_spans_rejected():
    with pytest.raises(ValueError, match="overlapping_table_spans"):
        html_to_grid(
            '<table><tr><td>x</td><td rowspan="2">y</td></tr>'
            '<tr><td colspan="2">z</td></tr></table>'
        )
    with pytest.raises(ValueError, match="table_grid_limit"):
        html_to_grid('<table><tr><td rowspan="999999">x</td></tr></table>')


def test_page_reports_keep_duplicates_only_across_distinct_table_entries():
    class Engine:
        def predict(self, input=None):
            if input == "broken":
                raise OSError("backend failed")
            yield {
                "res": {
                    "table_res_list": [{"pred_html": _TABLE_HTML}, {"pred_html": _TABLE_HTML}],
                    "parsing_res_list": [{"block_label": "table", "block_content": _TABLE_HTML}],
                    "overall_ocr_res": {
                        "rec_texts": ["张三"],
                        "rec_scores": [0.9],
                        "rec_boxes": [[1, 2, 5, 8]],
                    },
                }
            }

    reports = recognize_table_pages(["good", "broken", "good"], pipeline=Engine())
    assert [report.status for report in reports] == ["recognized", "failed", "recognized"]
    assert [[(table.page, table.index) for table in report.tables] for report in reports] == [
        [(1, 0), (1, 1)],
        [],
        [(3, 0), (3, 1)],
    ]
    assert reports[0].blocks[0]["confidence"] == 0.9
    assert reports[0].blocks[0]["width"] == 4
    assert reports[0].tables[0].source_html == _TABLE_HTML


def test_ocr_workbook_preserves_formula_like_text(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    path = tables_to_workbook_path(
        [TableGrid(grid=[["=1+1", "普通文本"]])], output_path=tmp_path / "literal.xlsx"
    )
    workbook = load_workbook(path)
    try:
        assert workbook.active["A1"].value == "=1+1"
        assert workbook.active["A1"].data_type == "s"
    finally:
        workbook.close()


def test_local_model_manifest_rejects_tampered_weight(tmp_path, monkeypatch):
    import json

    from app.application.elt import table_structure_ocr as structure

    dirs = {}
    models = {}
    for key in structure._MODEL_ENV:
        directory = tmp_path / key
        directory.mkdir()
        (directory / "weights").write_bytes(b"local model")
        dirs[key] = str(directory)
        models[key] = {
            "source": "test fixture, not production model",
            "sha256": structure._directory_sha256(directory),
        }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"paddleocr_version": "test", "models": models}))
    monkeypatch.setattr(structure, "version", lambda name: "test")
    monkeypatch.setenv("FHD_ETL_TABLE_STRUCTURE_MODEL_MANIFEST", str(manifest))
    assert structure._verify_local_models(dirs)
    (tmp_path / next(iter(dirs)) / "weights").write_bytes(b"changed")
    assert not structure._verify_local_models(dirs)


def test_elt_ocr_bridge_keeps_pages_and_table_candidates(tmp_path, monkeypatch):
    from PIL import Image

    from app.application.elt import table_structure_ocr as structure
    from app.application.shipment_excel_elt_ocr import ocr_source_to_workbook

    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("FHD_EXCEL_ELT_OCR_MAX_PAGES", "5")
    monkeypatch.setenv("FHD_ETL_TABLE_STRUCTURE", "required")
    source = tmp_path / "two-pages.tiff"
    first = Image.new("RGB", (40, 30), "white")
    second = Image.new("RGB", (40, 30), "black")
    first.save(source, save_all=True, append_images=[second])
    pipeline = _FakePipeline({"table_res_list": [{"pred_html": _TABLE_HTML}]})
    monkeypatch.setattr(structure, "get_table_structure_pipeline", lambda: pipeline)
    result = ocr_source_to_workbook(source, output_path=tmp_path / "output.xlsx")
    assert result["success"]
    assert result["structure_status"] == "candidate"
    assert [page["page_number"] for page in result["pages"]] == [1, 2]
    assert len({page["image_sha256"] for page in result["pages"]}) == 2
    assert pipeline.calls == 2
    workbook = load_workbook(result["file_path"])
    try:
        assert workbook.sheetnames == [page["sheet_name"] for page in result["pages"]]
    finally:
        workbook.close()


def test_elt_ocr_bridge_does_not_silently_truncate_pages(tmp_path, monkeypatch):
    from PIL import Image

    from app.application.shipment_excel_elt_ocr import ocr_source_to_workbook

    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("FHD_EXCEL_ELT_OCR_MAX_PAGES", "1")
    source = tmp_path / "two-pages.tiff"
    Image.new("RGB", (8, 8), "white").save(
        source, save_all=True, append_images=[Image.new("RGB", (8, 8), "black")]
    )
    result = ocr_source_to_workbook(source, output_path=tmp_path / "output.xlsx")
    assert not result["success"]
    assert result["error_code"] == "ocr_page_limit"
    assert not (tmp_path / "output.xlsx").exists()


def test_selected_ocr_pages_preserve_original_numbers():
    pipeline = _FakePipeline({"table_res_list": [{"pred_html": _TABLE_HTML}]})
    reports = recognize_table_pages([object(), object()], pipeline=pipeline, page_numbers=[2, 5])
    assert [report.page for report in reports] == [2, 5]
    assert [report.tables[0].page for report in reports] == [2, 5]


def test_mixed_pdf_routes_only_scan_pages_to_ocr(tmp_path, monkeypatch):
    import numpy as np

    from app.application import shipment_excel_elt_ocr as bridge
    from app.application.elt import table_structure_ocr as structure

    source = tmp_path / "mixed.pdf"
    source.write_bytes(b"%PDF fixture; native and raster adapters stubbed")
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    native_table = TableGrid(grid=[["name"], ["native"]], page=1, bbox=[0, 0, 20, 20])
    native = structure.PageStructure(
        1,
        "native_candidate",
        [native_table],
        coordinate_space="pdf_points_top_left",
        page_size=(40, 40),
    )
    monkeypatch.setattr(bridge, "_native_pdf_candidates", lambda handle: (2, {1: native}))
    calls = []

    def render(handle, **kwargs):
        assert isinstance(handle.read(0), bytes)
        calls.extend(kwargs["page_indices"])
        return [np.zeros((4, 4, 3), dtype=np.uint8)]

    monkeypatch.setattr(bridge, "_load_image_arrays", render)
    pipeline = _FakePipeline({"table_res_list": [{"pred_html": _TABLE_HTML}]})
    monkeypatch.setattr(structure, "get_table_structure_pipeline", lambda: pipeline)
    result = bridge.ocr_source_to_workbook(source, output_path=tmp_path / "out.xlsx")
    assert result["success"]
    assert result["structure_status"] == "partial"
    assert calls == [1]
    assert pipeline.calls == 1
    assert [page["page_number"] for page in result["pages"]] == [1, 2]
    assert [page["backend"] for page in result["pages"]] == ["pdfplumber", "pp-structure-v3"]
    assert result["pages"][0]["image_sha256"] is None
    assert result["pages"][1]["image_sha256"] is not None


@pytest.fixture
def owned_ocr_pdf(tmp_path, monkeypatch):
    from pypdf import PdfWriter

    from app.application.elt import table_structure_ocr as structure
    from app.domain.app_pure import excel_elt_kb

    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("FHD_ETL_TABLE_STRUCTURE", "required")
    monkeypatch.setenv("FHD_SHIPMENT_ELT_LLM", "0")
    monkeypatch.setattr(
        excel_elt_kb, "_KB", excel_elt_kb.ExcelEltKnowledgeBase(path=tmp_path / "kb.json")
    )
    source = tmp_path / "scanned.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=100)
    with source.open("wb") as stream:
        writer.write(stream)
    pipeline = _FakePipeline(
        {
            "table_res_list": [
                {
                    "pred_html": "<table><tr><td>产品名称</td><td>数量</td></tr>"
                    "<tr><td>原始材料</td><td>3</td></tr></table>",
                    "block_bbox": [8, 8, 90, 42],
                }
            ],
            "overall_ocr_res": {
                "rec_texts": ["原始材料", "3"],
                "rec_scores": [0.99, 0.98],
                "rec_boxes": [[10, 20, 60, 35], [70, 20, 80, 35]],
            },
        }
    )
    monkeypatch.setattr(structure, "get_table_structure_pipeline", lambda: pipeline)
    return source, pipeline, tmp_path / "runtime" / "temp_excel"


def test_ocr_text_consumer_reads_file_path_and_releases_workbook(owned_ocr_pdf):
    from app.application.office_template_media_bridge import _ocr_pdf_plaintext

    source, pipeline, staging = owned_ocr_pdf
    original = source.read_bytes()
    result = _ocr_pdf_plaintext(str(source))
    assert result["success"], result
    assert result["text"] == "产品名称\t数量\n原始材料\t3"
    assert result["source_sha256"] == hashlib.sha256(original).hexdigest()
    assert "workbook_path" not in result and "file_path" not in result
    assert pipeline.calls == 1
    assert source.read_bytes() == original
    assert list(staging.iterdir()) == []


def test_ocr_document_page_limit_removes_owned_workspace(tmp_path, monkeypatch):
    from PIL import Image

    from app.application.shipment_excel_elt_ocr import parse_ocr_document

    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("FHD_EXCEL_ELT_OCR_MAX_PAGES", "1")
    source = tmp_path / "two-pages.tiff"
    Image.new("RGB", (8, 8), "white").save(
        source, save_all=True, append_images=[Image.new("RGB", (8, 8), "black")]
    )
    original = source.read_bytes()
    result = parse_ocr_document(source)
    assert not result["success"]
    assert result["error_code"] == "ocr_page_limit"
    assert result["notes"] == []
    assert source.read_bytes() == original
    assert list((tmp_path / "runtime" / "temp_excel").iterdir()) == []


def test_ocr_elt_rows_keep_original_provenance_after_workbook_cleanup(owned_ocr_pdf):
    from app.application.elt.parsers import parse_file

    source, pipeline, staging = owned_ocr_pdf
    original = source.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    dataset = parse_file(source, target_type="products")
    try:
        assert [row.values for row in dataset.rows] == [{"产品名称": "原始材料", "数量": "3"}]
        assert dataset.source_features["ocr_source_sha256"] == digest
        assert dataset.rows[0].provenance["source_sha256"] == digest
        assert dataset.rows[0].provenance["page"] == 1
        assert dataset.rows[0].provenance["cells"]["产品名称"]["position"] == {
            "left": 10,
            "top": 20,
            "width": 50,
            "height": 15,
        }
        assert dataset.rows[0].provenance["requires_confirmation"] is True
        assert dataset.source_features["ocr_page_count"] == 1
        assert list(staging.iterdir()) == []
        first = dataset.rows[0]
        dataset.rows[0] = first
        assert list(dataset.rows) == [first]
    finally:
        dataset.close()
    assert pipeline.calls == 1
    assert source.read_bytes() == original


def test_ocr_note_consumer_returns_original_source_not_deleted_workbook(owned_ocr_pdf):
    from app.application.shipment_excel_elt_ocr import parse_ocr_document

    source, pipeline, staging = owned_ocr_pdf
    pipeline.payload["table_res_list"][0]["pred_html"] = (
        "<table><tr><td>型号</td><td>产品名称</td><td>数量</td></tr>"
        "<tr><td>PC-01</td><td>原始材料</td><td>3</td></tr></table>"
    )
    pipeline.payload["parsing_res_list"] = [
        {"block_label": "text", "block_content": "送货单"},
        {"block_label": "text", "block_content": "客户：原件客户"},
    ]
    original = source.read_bytes()
    result = parse_ocr_document(source)
    assert result["success"], result
    assert result["file_path"] == result["source_path"] == str(source)
    assert result["file_name"] == source.name
    assert result["source_sha256"] == hashlib.sha256(original).hexdigest()
    assert result["ocr"]["source_sha256"] == result["source_sha256"]
    assert result["ocr"]["pages"][0]["page_number"] == 1
    assert result["ocr"]["pages"][0]["bbox"] == [8, 8, 90, 42]
    assert result["notes"], result
    assert result["notes"][0]["items"][0]["product_name"] == "原始材料"
    assert "file_path" not in result["ocr"]
    assert str(staging) not in json.dumps(result, ensure_ascii=False)
    assert pipeline.calls == 1
    assert source.read_bytes() == original
    assert list(staging.iterdir()) == []


@pytest.mark.parametrize("consumer", ["text", "notes", "elt", "direct"])
def test_ocr_consumer_releases_partial_output_on_write_failure(
    owned_ocr_pdf, monkeypatch, consumer
):
    from openpyxl import Workbook

    from app.application.elt.errors import EltError
    from app.application.elt.parsers import parse_file
    from app.application.office_template_media_bridge import _ocr_pdf_plaintext
    from app.application.shipment_excel_elt_ocr import ocr_source_to_workbook, parse_ocr_document

    source, _pipeline, staging = owned_ocr_pdf
    original = source.read_bytes()

    def interrupted_save(self, stream):
        stream.write(b"partial workbook")
        raise OSError("disk write interrupted")

    monkeypatch.setattr(Workbook, "save", interrupted_save)
    if consumer == "elt":
        with pytest.raises(EltError, match="OCR"):
            parse_file(source, target_type="products")
    else:
        result = (
            _ocr_pdf_plaintext(str(source))
            if consumer == "text"
            else parse_ocr_document(source)
            if consumer == "notes"
            else ocr_source_to_workbook(source)
        )
        assert not result["success"]
    assert source.read_bytes() == original
    assert list(staging.iterdir()) == []


@pytest.mark.parametrize("consumer", ["notes", "elt"])
def test_ocr_consumer_exception_cleans_only_its_owned_files(owned_ocr_pdf, monkeypatch, consumer):
    from app.application import shipment_excel_elt_app_service
    from app.application.elt import parsers
    from app.application.shipment_excel_elt_ocr import parse_ocr_document

    source, _pipeline, staging = owned_ocr_pdf
    staging.mkdir(parents=True)
    sentinel = staging / "preexisting.xlsx"
    sentinel.write_bytes(b"unrelated caller-owned file")
    original = source.read_bytes()
    consumed = []

    def fail_notes(path, **kwargs):
        workbook = load_workbook(path, read_only=True)
        try:
            assert workbook.active["A2"].value == "原始材料"
        finally:
            workbook.close()
        raise ValueError("consumer interrupted")

    def fail_provenance(dataset, result, **kwargs):
        assert dataset.rows[0].values["产品名称"] == "原始材料"
        consumed.append(dataset.rows)
        raise ValueError("consumer interrupted")

    if consumer == "notes":
        monkeypatch.setattr(shipment_excel_elt_app_service, "parse_delivery_notes", fail_notes)
    else:
        monkeypatch.setattr(parsers, "enrich_ocr_provenance", fail_provenance)
    with pytest.raises(ValueError, match="consumer interrupted"):
        if consumer == "notes":
            parse_ocr_document(source)
        else:
            parsers.parse_file(source, target_type="products")
    assert all(rows.closed for rows in consumed)
    assert source.read_bytes() == original
    assert sentinel.read_bytes() == b"unrelated caller-owned file"
    assert list(staging.iterdir()) == [sentinel]


@pytest.mark.parametrize("explicit_output", [True, False])
def test_ocr_direct_output_remains_available_to_its_caller(owned_ocr_pdf, explicit_output):
    from pathlib import Path

    from app.application.shipment_excel_elt_ocr import ocr_source_to_workbook

    source, _pipeline, _staging = owned_ocr_pdf
    output = source.with_suffix(".xlsx") if explicit_output else None
    result = ocr_source_to_workbook(source, output_path=output)
    assert result["success"], result
    target = Path(result["file_path"])
    if explicit_output:
        assert target == output
    workbook = load_workbook(target, read_only=True)
    try:
        assert workbook.active["A2"].value == "原始材料"
    finally:
        workbook.close()
    assert target.is_file() and source.is_file()


def test_ocr_text_iteration_failure_closes_workbook_before_cleanup(owned_ocr_pdf, monkeypatch):
    import openpyxl

    from app.application.office_template_media_bridge import _ocr_pdf_plaintext

    source, _pipeline, staging = owned_ocr_pdf
    original = source.read_bytes()
    load = openpyxl.load_workbook
    opened = []

    def interrupted_rows(*args, **kwargs):
        raise OSError("row read interrupted")

    def open_then_interrupt(path, **kwargs):
        workbook = load(path, **kwargs)
        opened.append(workbook)
        monkeypatch.setattr(workbook.active, "iter_rows", interrupted_rows)
        return workbook

    monkeypatch.setattr(openpyxl, "load_workbook", open_then_interrupt)
    result = _ocr_pdf_plaintext(str(source))
    assert result["success"] is False
    assert "row read interrupted" in result["message"]
    assert len(opened) == 1 and opened[0]._archive.fp is None
    assert source.read_bytes() == original
    assert list(staging.iterdir()) == []
