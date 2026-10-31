"""No model IDs: immutable source ranges prove data and final grouping coverage."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.application.etl.errors import ReviewedExcelError
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


def answer(*ranges):
    return {"documents": [{"ranges": list(ranges), "reason": "synthetic source relationship"}]}


def execute(monkeypatch, review, raw):
    original = deepcopy(raw)
    monkeypatch.setenv("FHD_TEMPLATE_LLM_PROVIDER", "mimo")
    monkeypatch.setattr(
        "app.application.reviewed_excel_template._template_mimo_complete",
        lambda *args: SimpleNamespace(data=raw, model="synthetic-no-network"),
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


def test_missing_and_duplicate_coverage_rejected(monkeypatch):
    for raw in (answer(region(c2=1)), answer(region(), region())):
        with pytest.raises(ReviewedExcelError):
            execute(monkeypatch, source(["A1", "C1"]), raw)


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
    return answer(
        *(payload["ranges"] if "ranges" in payload else [synthetic_source_region(payload)])
    )


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
    monkeypatch.setenv("FHD_TEMPLATE_LLM_PROVIDER", "mimo")
    monkeypatch.setattr(
        "app.application.reviewed_excel_template._template_mimo_complete",
        lambda *args: SimpleNamespace(data=raw, model="synthetic-no-network"),
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
    assert hashes["version"] == "independent-excel-v10-document-ranges"
    assert (
        hashes["schema_template_sha256"]
        == "06548a8c4a41b87333a2e19dba43320f23ead21993ff7884ff884c54c60699e2"
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
        ]
    }
    with pytest.raises(ReviewedExcelError, match="范围总数超过100"):
        execute(monkeypatch, review, raw)
