"""No model IDs: immutable source ranges prove data and final grouping coverage."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.application.elt.errors import ReviewedExcelError
from app.application.reviewed_excel_classification import _classify_semantic_batch
from tests.test_application.test_reviewed_excel_atoms import source

SHEET = "O'Brien ! 表"


def region(r1=1, r2=1, c1=1, c2=3, *, sheet=SHEET):
    return {
        "sheet_name": sheet,
        "row_start": r1,
        "row_end": r2,
        "column_start": c1,
        "column_end": c2,
    }


def answer(*ranges, can_slice=True):
    return {
        "documents": [{"ranges": list(ranges), "reason": "synthetic source relationship"}],
        "can_slice": can_slice,
    }


def execute(monkeypatch, review, raw):
    original = deepcopy(raw)
    monkeypatch.setattr(
        "app.application.reviewed_excel_template._template_platform_complete",
        lambda *args, **kwargs: SimpleNamespace(data=raw, model="synthetic-no-network"),
    )
    try:
        return _classify_semantic_batch(review, reference_ids=True)
    finally:
        assert original == raw


def test_source_proves_all_cells_without_model_numbering(monkeypatch):
    review = source(["A1", "B1", "C1"])
    raw = answer(region())
    prepared = _classify_semantic_batch(review, prepare_only=True, reference_ids=True)
    payload = json.loads(prepared["messages"][1]["content"])
    assert "source_sheet_prefixes" not in payload
    assert all("evidence_id" not in cell for cell in payload["cells"])
    result = execute(monkeypatch, review, raw)
    assert result["regions"][0]["range"] == "A1:C1"
    assert result["input_summary"]["reference_response"] == raw
    assert result["input_summary"]["source_coverage"]["regions"][0]["source_cells"] == [
        "A1",
        "B1",
        "C1",
    ]
    assert result["logical_documents"][0]["document_id"].startswith("source-")
    assert result["input_summary"]["source_coverage"]["can_slice"] is True


def test_range_schema_names_only_sheets_with_primary_cells():
    review = source(["A1", "B1", "C1"], second=True)
    review["cells"] = [cell for cell in review["cells"] if cell["sheet"] == SHEET]
    prepared = _classify_semantic_batch(review, prepare_only=True, reference_ids=True)
    payload = json.loads(prepared["messages"][1]["content"])
    area = payload["output_schema"]["properties"]["documents"]["items"]["properties"]["ranges"]
    assert area["items"]["properties"]["sheet_name"]["enum"] == [SHEET]
    assert {sheet["sheet"] for sheet in payload["sheets"]} == {SHEET, "第二"}


def test_provider_envelope_reason_is_ignored(monkeypatch):
    # Live providers sometimes wrap the verified document list in one
    # informational root reason (and may append stray closing brackets).
    raw = answer(region())
    raw["reason"] = "整表为一张单据，按结构拆分为互不重叠的完整区域。"
    result = execute(monkeypatch, source(["A1", "B1", "C1"]), raw)
    assert result["regions"][0]["range"] == "A1:C1"
    assert result["input_summary"]["reference_response"]["reason"] == raw["reason"]


def test_unknown_envelope_field_is_still_rejected(monkeypatch):
    raw = answer(region())
    raw["summary"] = "not part of the source range contract"
    with pytest.raises(ReviewedExcelError):
        execute(monkeypatch, source(["A1", "B1", "C1"]), raw)


@pytest.mark.parametrize(
    "key,value",
    [
        ("row_start", True),
        ("row_end", 1.0),
        ("column_start", "1"),
        ("row_start", 0),
        ("row_end", 2),
        ("column_end", 4),
        ("column_start", 3),
        ("sheet_name", "unknown"),
        ("primary_id", "S1:A1"),
    ],
)
def test_invalid_bounds_fail_without_repair(monkeypatch, key, value):
    raw = answer(region(c2=2))
    raw["documents"][0]["ranges"][0][key] = value
    with pytest.raises(ReviewedExcelError):
        execute(monkeypatch, source(["A1", "B1", "C1"]), raw)


@pytest.mark.parametrize("context", [False, True])
def test_no_unread_or_context_borrowing_at_outer_rows(monkeypatch, context):
    review = source(["A1", "A2", "A3"])
    full = review["cells"]
    cells = [full[1]] + (
        [{**full[0], "context_only": True}, {**full[2], "context_only": True}] if context else []
    )
    with pytest.raises(ReviewedExcelError, match="上下文或未发送"):
        execute(
            monkeypatch, {**review, "cells": cells, "full_cells": full}, answer(region(1, 3, 1, 1))
        )


def test_merge_cut_is_tolerated_for_export_flatten(monkeypatch):
    # Classify no longer hard-fails merge cuts; export flattens them.
    result = execute(monkeypatch, source(["DN3"], ["DN3:DO3"]), answer(region(2, 3, 65, 118)))
    assert result["regions"]


def test_geometric_overlap_only_at_blank_still_fails(monkeypatch):
    with pytest.raises(ReviewedExcelError, match="重叠"):
        execute(
            monkeypatch,
            source(["A2", "C2", "B1", "B3"]),
            answer(region(2, 2, 1, 3), region(1, 3, 2, 2)),
        )


def test_duplicate_coverage_rejected(monkeypatch):
    with pytest.raises(ReviewedExcelError, match="重复覆盖"):
        execute(monkeypatch, source(["A1", "C1"]), answer(region(), region()))


def test_identify_prompt_states_the_three_rejection_rules():
    from app.application.reviewed_excel_reference_prompts import IDENTIFY_PROMPT

    assert "每个划定范围至少包含一个非空主单元格（合并格无值不算）" in IDENTIFY_PROMPT
    assert "不要覆盖全空尾部行" in IDENTIFY_PROMPT
    assert "范围之间不能重叠，否则整批拒绝" in IDENTIFY_PROMPT
    assert "由你决定这些单据现在能不能切片" in IDENTIFY_PROMPT
    assert "无论是否有范围外的主单元格，顶层都必须返回布尔值 can_slice" in IDENTIFY_PROMPT


def test_model_slice_decision_is_kept_and_required(monkeypatch):
    refused = execute(monkeypatch, source(["A1", "B1", "C1"]), answer(region(), can_slice=False))
    assert refused["input_summary"]["source_coverage"]["can_slice"] is False
    raw = answer(region())
    raw.pop("can_slice")
    with pytest.raises(ReviewedExcelError):
        execute(monkeypatch, source(["A1", "B1", "C1"]), raw)


def test_disjoint_nonempty_ranges_pass(monkeypatch):
    result = execute(
        monkeypatch,
        source(["A1", "C1"], ["C10:E10"]),
        answer(region(1, 1, 1, 1), region(1, 1, 3, 3)),
    )
    assert [item["range"] for item in result["regions"]] == ["A1:A1", "C1:C1"]


def test_blank_range_is_left_out_and_the_slice_decision_is_kept(monkeypatch):
    review = source(["A1"], ["C10:E10"])
    result = execute(monkeypatch, review, answer(region(1, 1, 1, 1), region(10, 10, 3, 5)))
    assert [item["range"] for item in result["regions"]] == ["A1:A1"]
    assert result["input_summary"]["source_coverage"]["can_slice"] is True


def test_only_a_blank_range_is_still_rejected(monkeypatch):
    with pytest.raises(ReviewedExcelError, match="主体为空或重复覆盖"):
        execute(monkeypatch, source(["A1"], ["C10:E10"]), answer(region(10, 10, 3, 5)))


def test_overlapping_primary_ranges_are_rejected(monkeypatch):
    with pytest.raises(ReviewedExcelError, match="主体为空或重复覆盖"):
        execute(
            monkeypatch,
            source(["A1", "B1"]),
            answer(region(1, 1, 1, 2), region(1, 1, 2, 2)),
        )


def test_partial_boundary_keeps_covered_cells_for_a_person(monkeypatch):
    """Synthetic fixture: the model rectangle covers A1 and leaves C1 uncovered."""
    from app.application.reviewed_excel_partition import boundary_left_for_confirmation

    review = source(["A1", "C1"])
    raw = answer(region(c2=1))
    original = deepcopy(raw)
    calls = []

    def complete(*_args, **_kwargs):
        calls.append(raw)
        return SimpleNamespace(data=raw, model="synthetic-no-network")

    monkeypatch.setattr(
        "app.application.reviewed_excel_template._template_platform_complete", complete
    )
    result = _classify_semantic_batch(review, reference_ids=True)
    assert raw == original and calls == [raw]
    assert [item["range"] for item in result["regions"]] == ["A1:A1"]
    pending = result["input_summary"]["source_coverage"]["pending_confirmation"]
    assert pending == [{"sheet": SHEET, "cell": "C1"}]
    assert boundary_left_for_confirmation({"input_summaries": [result["input_summary"]]}) is True


def test_flat_source_range_documents_are_coerced_before_validation(monkeypatch):
    raw = {
        "documents": [
            {
                "sheet_name": SHEET,
                "row_start": 1,
                "row_end": 1,
                "column_start": 1,
                "column_end": 3,
                "reason": "生产打印单分段",
            }
        ],
        "reason": "整表分段",
        "can_slice": True,
    }
    result = execute(monkeypatch, source(["A1", "B1", "C1"]), raw)
    assert result["regions"][0]["range"] == "A1:C1"


def test_real_special_sheet_name_not_batch_number(monkeypatch):
    review = source(["A1"], second=True)
    result = execute(
        monkeypatch,
        {**review, "cells": review["cells"][1:], "full_cells": review["cells"]},
        answer(region(c2=1, sheet="第二")),
    )
    assert result["regions"][0]["sheet"] == "第二"


def test_legacy_atom_answer_not_reinterpreted(monkeypatch):
    raw = {
        "physical_regions": [
            {"atom_ids": ["S1:A1"], "primary_id": "S1:A1", "dependency_ids": [], "reason": "old"}
        ],
        "logical_documents": [],
        "layout_references": [],
    }
    with pytest.raises(ReviewedExcelError, match="白名单"):
        execute(monkeypatch, source(["A1"]), raw)


def test_contract_rejects_one_sided_dimension_drift():
    from app.application.reviewed_excel_reference_ids import IDENTIFY_PROMPT, verify_contract

    schema = _classify_semantic_batch(source(["A1", "A10"]), prepare_only=True, reference_ids=True)[
        "schema"
    ]
    schema["properties"]["documents"]["items"]["properties"]["ranges"]["items"]["properties"][
        "row_start"
    ]["maximum"] = 999
    with pytest.raises(ReviewedExcelError, match="契约"):
        verify_contract(IDENTIFY_PROMPT, schema, "identify")


def synthetic_source_region(payload):
    """Test fixture only, not a business classifier."""
    from openpyxl.utils.cell import range_boundaries

    cells = [cell for cell in payload["cells"] if not cell.get("context_only")]
    assert len({cell["sheet"] for cell in cells}) == 1
    boxes = [range_boundaries(cell.get("required_extent", cell["cell"])) for cell in cells]
    return region(
        min(box[1] for box in boxes),
        max(box[3] for box in boxes),
        min(box[0] for box in boxes),
        max(box[2] for box in boxes),
        sheet=cells[0]["sheet"],
    )


def synthetic_document_answer(payload):
    if "ranges" in payload:
        # Group input may annotate sheet_state for the model; schema forbids extras.
        ranges = [
            {
                key: part[key]
                for key in ("sheet_name", "row_start", "row_end", "column_start", "column_end")
            }
            for part in payload["ranges"]
        ]
        return {"documents": [{"ranges": ranges, "reason": "synthetic source relationship"}]}
    return answer(synthetic_source_region(payload))


@pytest.mark.parametrize("mutation", ["duplicate", "omit", "expand", "shrink", "unknown", "bool"])
def test_final_grouping_exact_unique_complete(monkeypatch, mutation):
    from app.application.reviewed_excel_grouping import group_semantic_fragments

    review = source(["A1", "C1"])
    classification = {
        "source_sha256": review["sha256"],
        "coverage": [{"sheet": SHEET, "unread": 0, "unassigned": 0, "merged_omitted": 0}],
        "regions": [
            {"sheet": SHEET, "range": "A1:A1", "evidence": [{"sheet": SHEET, "cell": "A1"}]},
            {"sheet": SHEET, "range": "C1:C1", "evidence": [{"sheet": SHEET, "cell": "C1"}]},
        ],
    }
    raw = answer(region(c2=1), region(c1=3, c2=3))
    if mutation == "duplicate":
        raw["documents"][0]["ranges"].append(region(c2=1))
    elif mutation == "omit":
        raw["documents"][0]["ranges"].pop()
    elif mutation == "expand":
        raw["documents"][0]["ranges"][0]["column_end"] = 2
    elif mutation == "shrink":
        raw["documents"][0]["ranges"][1]["column_start"] = 4
    elif mutation == "unknown":
        raw["documents"][0]["ranges"][0]["sheet_name"] = "unknown"
    else:
        raw["documents"][0]["ranges"][0]["row_start"] = True
    original = deepcopy(raw)
    monkeypatch.setattr(
        "app.application.reviewed_excel_template._template_platform_complete",
        lambda *args, **kwargs: SimpleNamespace(data=raw, model="synthetic-no-network"),
    )
    with pytest.raises(ReviewedExcelError):
        group_semantic_fragments(review, classification)
    assert raw == original


def test_formula_metadata_uses_source_coordinate_not_model_id():
    review = source(["A1", "B1", "C1"])
    review["cells"][0].update(value="=SUM(B1:C1)", kind="formula")
    request = _classify_semantic_batch(review, prepare_only=True, reference_ids=True)
    payload = json.loads(request["messages"][1]["content"])
    formula = payload["integrity_constraints"]["formula_references"][0]
    assert formula == {
        "sheet": SHEET,
        "cell": "A1",
        "references": [{"sheet": SHEET, "range": "B1:C1"}],
        "unresolved": False,
    }
    assert "evidence_id" not in json.dumps(payload)


def test_range_schema_fingerprint_and_boolean_dimension_drift():
    from app.application.reviewed_excel_reference_ids import IDENTIFY_PROMPT, verify_contract

    schema = _classify_semantic_batch(source(["A1"]), prepare_only=True, reference_ids=True)[
        "schema"
    ]
    hashes = verify_contract(IDENTIFY_PROMPT, schema, "identify")
    assert hashes["version"] == "independent-excel-v11-document-ranges"
    assert (
        hashes["schema_template_sha256"]
        == "b1455573350323b3d7d3317c5202954d06e01f6675597532586facc2bdbc2b85"
    )
    schema["properties"]["documents"]["items"]["properties"]["ranges"]["items"]["properties"][
        "row_end"
    ]["maximum"] = True
    with pytest.raises(ReviewedExcelError, match="契约"):
        verify_contract(IDENTIFY_PROMPT, schema, "identify")


def test_documents_do_not_raise_global_100_region_limit(monkeypatch):
    review = source([f"A{row}" for row in range(1, 102)])
    ranges = [region(row, row, 1, 1) for row in range(1, 102)]
    raw = {
        "documents": [
            {"ranges": ranges[start : start + 20], "reason": "synthetic"}
            for start in range(0, len(ranges), 20)
        ],
        "can_slice": True,
    }
    with pytest.raises(ReviewedExcelError, match="范围总数超过100"):
        execute(monkeypatch, review, raw)
