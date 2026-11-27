"""Generated native geometry is source evidence, never a business classification."""

import hashlib
import json
from io import BytesIO

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Border, PatternFill, Side
from openpyxl.utils.cell import range_boundaries
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.table import Table
from openpyxl.worksheet.worksheet import Worksheet

from app.application.elt.parser_table_structure import load_sheet_segmentations
from app.application.elt.table_segmentation import (
    iter_structure_candidates,
    validate_candidate_selection,
)
from app.application.reviewed_excel_structural_index import (
    build_workbook_structural_index,
    compress_structural_index_for_model,
)
from app.infrastructure.excel.cell_visual_facts import (
    worksheet_geometry_regions,
    worksheet_visual_facts,
)


def _frame(sheet, ref, *, headers=True, grid=False):
    left, top, right, bottom = range_boundaries(ref)
    edge = Side(style="medium", color="FF284B63")
    inner = Side(style="thin") if grid else Side()
    for row in range(top, bottom + 1):
        for column in range(left, right + 1):
            cell = sheet.cell(row, column)
            cell.value = f"field_{top}_{column}" if headers and row == top else row * 100 + column
            cell.border = Border(
                left=edge if column == left else inner,
                right=edge if column == right else inner,
                top=edge if row == top else inner,
                bottom=edge if row == bottom else inner,
            )


def _save(book, path):
    book.save(path)
    book.close()
    return path.read_bytes()


@pytest.mark.parametrize(
    "ranges,headers,grid",
    [
        (("A1:B3", "C1:D3"), True, False),
        (("A1:B3", "A4:B6"), True, False),
        (("A8:B10", "C8:D10"), False, False),
        (("B4:D8", "E4:G8"), True, True),
    ],
)
def test_touching_native_frames_reach_model_navigation_without_semantic_promotion(
    tmp_path, ranges, headers, grid
):
    book = Workbook()
    sheet = book.active
    for ref in ranges:
        _frame(sheet, ref, headers=headers, grid=grid)
    path = tmp_path / "touching.xlsx"
    original = _save(book, path)

    segmentation = load_sheet_segmentations(path)["Sheet"]
    candidates = list(iter_structure_candidates(segmentation))
    framed = [item for item in candidates if item["basis"] == "border_enclosure"]
    assert {item["range"] for item in framed} == set(ranges)
    assert all(item["status"] == "candidate" and item["header_rows"] == [] for item in framed)
    assert (
        validate_candidate_selection(candidates, [item["candidate_id"] for item in framed])
        == framed
    )
    assert segmentation.coverage()["unassigned_cells"] == 0
    assert segmentation.public()["structure_candidate_total"] == len(candidates)

    navigation = compress_structural_index_for_model(build_workbook_structural_index(original))
    offered = navigation["sheets"][0]["structure_candidates"]
    assert {item["range"] for item in offered if item["basis"] == "border_enclosure"} == set(ranges)
    assert navigation["readback"]["expected_sha256"] == hashlib.sha256(original).hexdigest()
    assert path.read_bytes() == original


def test_sparse_remote_header_and_unclosed_region_keep_all_original_coordinates(
    tmp_path, monkeypatch
):
    book = Workbook()
    sheet = book.active
    _frame(sheet, "C60000:F60003")
    sheet["D60001"], sheet["E60002"] = None, None
    sheet["C60001"], sheet["F60003"] = 0, False
    sheet["XFD1048576"] = "isolated"
    # A second outline is deliberately open: no closed-table evidence may be invented.
    _frame(sheet, "H60000:I60003", headers=False)
    sheet["H60002"].border = Border()
    path = tmp_path / "sparse.xlsx"
    original = _save(book, path)

    def dense_read(*args, **kwargs):
        pytest.fail("geometry must use materialized native cells, never a dense worksheet walk")

    monkeypatch.setattr(Worksheet, "iter_rows", dense_read)
    result = load_sheet_segmentations(path)["Sheet"]
    candidates = list(iter_structure_candidates(result))
    assert {item["range"] for item in candidates if item["basis"] == "border_enclosure"} == {
        "C60000:F60003"
    }
    assert any(item["range"] == "XFD1048576:XFD1048576" for item in candidates)
    # The far header is evidence for the model, not an asserted fallback role.
    assert any(item["range"] == "C60000:F60003" for item in candidates)
    assert (60001, 3) in result.source_positions and (60003, 6) in result.source_positions
    assert result.coverage()["unassigned_cells"] == 0
    assert all(
        any(
            top <= row <= bottom and left <= column <= right
            for left, top, right, bottom in (range_boundaries(item["range"]) for item in candidates)
        )
        for row, column in result.source_positions
    )
    navigation = compress_structural_index_for_model(build_workbook_structural_index(original))
    assert "XFD1048576:XFD1048576" in {
        item["range"] for item in navigation["sheets"][0]["structure_candidates"]
    }
    assert path.read_bytes() == original


def test_merged_span_and_native_regions_coexist_in_model_navigation(tmp_path):
    book = Workbook()
    sheet = book.active
    _frame(sheet, "A1:C4")
    sheet.merge_cells("A1:C1")
    _frame(sheet, "D1:F4")
    sheet.add_table(Table(displayName="NativeRegion", ref="D1:F4"))
    book.defined_names.add(DefinedName("ExplicitArea", attr_text="'Sheet'!$D$2:$F$4"))
    path = tmp_path / "merged-and-native.xlsx"
    original = _save(book, path)

    result = load_sheet_segmentations(path)["Sheet"]
    candidates = list(iter_structure_candidates(result))
    assert {item["range"] for item in candidates if item["basis"] == "border_enclosure"} == {
        "A1:C4",
        "D1:F4",
    }
    expected = {("excel_table", "D1:F4"), ("defined_name", "D2:F4")}
    assert expected <= {(item["basis"], item["range"]) for item in candidates}
    navigation = compress_structural_index_for_model(build_workbook_structural_index(original))
    assert expected <= {
        (item["basis"], item["range"]) for item in navigation["sheets"][0]["structure_candidates"]
    }
    assert result.coverage()["unexpected_cells"] == 0
    assert result.coverage()["unassigned_cells"] == 0


def test_unclosed_outline_does_not_absorb_following_frame_or_unstyled_cells(tmp_path):
    book = Workbook()
    sheet = book.active
    _frame(sheet, "A1:B3", headers=False)
    for address in ("A3", "B3"):
        border = sheet[address].border
        sheet[address].border = Border(left=border.left, right=border.right)
    _frame(sheet, "A4:B6", headers=False)
    sheet["C4"], sheet["D4"], sheet["C5"], sheet["D5"] = 0, 2, False, 3
    path = tmp_path / "open-outline.xlsx"
    _save(book, path)

    result = load_sheet_segmentations(path)["Sheet"]
    candidates = list(iter_structure_candidates(result))
    assert {item["range"] for item in candidates if item["basis"] == "border_enclosure"} == {
        "A4:B6"
    }
    assert all(item["status"] == "candidate" for item in candidates)
    assert result.coverage()["nonempty_cells"] == 16
    assert result.coverage()["unassigned_cells"] == 0


def test_native_style_continuity_is_a_candidate_and_unstyled_gap_is_not_bridged(tmp_path):
    book = Workbook()
    sheet = book.active
    for column, color in ((1, "FFCCDDEE"), (3, "FFFFEEDD")):
        for row in range(1, 4):
            for offset in (0, 1):
                cell = sheet.cell(row, column + offset, row * 100 + column + offset)
                cell.fill = PatternFill("solid", fgColor=color)
    sheet["A10"] = "separate"
    sheet["A10"].fill = PatternFill("solid", fgColor="FFCCDDEE")
    path = tmp_path / "fills.xlsx"
    _save(book, path)
    result = load_sheet_segmentations(path)["Sheet"]
    candidates = list(iter_structure_candidates(result))
    assert {item["range"] for item in candidates if item["basis"] == "style_continuity"} == {
        "A1:B3",
        "C1:D3",
    }
    assert all(item["status"] == "candidate" for item in candidates)


def test_unstyled_two_column_and_headerless_regions_reach_model_without_rule_labels(tmp_path):
    book = Workbook()
    sheet = book.active
    for row, values in ((40000, ("x axis", "y axis")), (40001, (0, False)), (90000, (17, 23))):
        for column, value in enumerate(values, start=1):
            sheet.cell(row, column, value)
    path = tmp_path / "unstyled.xlsx"
    original = _save(book, path)
    navigation = compress_structural_index_for_model(build_workbook_structural_index(original))
    offered = navigation["sheets"][0]["structure_candidates"]
    assert {item["range"] for item in offered} == {"A40000:B40001", "A90000:B90000"}
    assert all(
        item["basis"] == "occupied_region"
        and item["status"] == "candidate"
        and not item["header_rows"]
        for item in offered
    )
    assert navigation["readback"]["expected_sha256"] == hashlib.sha256(original).hexdigest()


def test_geometry_survives_actual_ai_first_request_preparation(tmp_path):
    from app.application.reviewed_excel_classification import _classify_semantic_batch
    from app.application.reviewed_excel_structural_index import ensure_review_structural_index
    from app.application.reviewed_excel_template import inspect_workbook

    book = Workbook()
    for ref in ("A1:B3", "C1:D3"):
        _frame(book.active, ref)
    original = _save(book, tmp_path / "model-evidence.xlsx")
    review = inspect_workbook(original)
    ensure_review_structural_index(review, original)
    request = _classify_semantic_batch(review, prepare_only=True, reference_ids=True)
    payload = json.loads(request["messages"][1]["content"])
    index = payload["workbook_structural_index"]
    assert {
        item["range"]
        for item in index["sheets"][0]["structure_candidates"]
        if item["basis"] == "border_enclosure"
    } == {"A1:B3", "C1:D3"}
    assert index["readback"]["expected_sha256"] == hashlib.sha256(original).hexdigest()
    assert "rule_hints" not in payload and "structure_map" not in payload


def test_native_neighbor_features_keep_both_axes_gaps_and_styled_blanks_after_roundtrip():
    book = Workbook()
    sheet = book.active
    sheet["B2"], sheet["C2"], sheet["B3"], sheet["B1000000"] = 0, False, "near", "far"
    sheet["B2"].border = Border(right=Side(style="thin"), bottom=Side(style="medium"))
    sheet["C2"].border = Border(left=Side(style="thin"))
    sheet["B3"].border = Border(top=Side(style="medium"))
    sheet["D2"].fill = PatternFill("solid", fgColor="FFCCDDEE")
    body = BytesIO()
    book.save(body)
    loaded = load_workbook(BytesIO(body.getvalue()))
    try:
        positions = set(loaded.active._cells)
        facts = worksheet_visual_facts(loaded.active)
        edges = {(item["from"], item["to"]): item for item in facts["neighbor_candidates"]}
        assert edges[("B2", "C2")]["facing_borders"] == ["thin", "thin"]
        assert edges[("B2", "B3")]["facing_borders"] == ["medium", "medium"]
        assert edges[("B3", "B1000000")]["gap"] == 999996
        assert edges[("B3", "B1000000")]["facing_borders"] is None
        assert any(item["address"] == "D2" and item["blank"] for item in facts["cells"])
        assert set(loaded.active._cells) == positions
    finally:
        loaded.close()
        book.close()


def test_geometry_does_not_materialize_default_styles_in_unstyled_body_cells():
    book = Workbook()
    book.active["A1"] = "styled header"
    book.active["A1"].fill = PatternFill("solid", fgColor="FFCCDDEE")
    book.active["A2"], book.active["B2"] = 0, False
    try:
        sheet = book.active
        before = {position: cell._style for position, cell in sheet._cells.items()}
        assert before[(2, 1)] is None and before[(2, 2)] is None
        assert worksheet_geometry_regions(sheet) == ()
        assert all(cell._style is before[position] for position, cell in sheet._cells.items())
    finally:
        book.close()


def test_geometry_navigation_budget_records_omission_and_exact_source_readback():
    book = Workbook()
    for index in range(90):
        row = index * 4 + 1
        _frame(book.active, f"A{row}:B{row + 2}", headers=False)
    book.create_sheet("Hidden").sheet_state = "veryHidden"
    body = BytesIO()
    book.save(body)
    book.close()
    index = build_workbook_structural_index(body.getvalue())
    sheet = index["sheets"][0]
    assert sheet["structure_candidate_total"] == 180  # 90 borders + 90 occupied regions.
    assert len(sheet["structure_candidates"]) < sheet["structure_candidate_total"]
    assert sheet["structure_candidates_truncated"] is True
    compact = compress_structural_index_for_model(index, budget_bytes=2500)
    assert compact["truncated"] is True and compact["sheet_inventory_complete"] is True
    assert [item["sheet"] for item in compact["sheets"]] == ["Sheet", "Hidden"]
    assert compact["sheets"][0]["structure_candidate_total"] == 180
    assert compact["sheets"][0]["structure_candidates_truncated"] is True
    assert compact["sheets"][0]["structure_readback_range"] == "A1:B359"
    assert compact["readback"]["expected_sha256"] == hashlib.sha256(body.getvalue()).hexdigest()
    assert compact["encoded_bytes"] == len(
        json.dumps(compact, ensure_ascii=False, separators=(",", ":")).encode()
    )
    assert compact["encoded_bytes"] <= 2500
