from copy import deepcopy

import pytest

from app.application.etl.errors import ReviewedExcelError
from app.application.reviewed_excel_reference_ids import normalize_reference_ids, reference_contract
from tests.test_application.test_reviewed_excel_boundaries import synthetic_document_answer


def contract():
    ref = {
        "type": "object",
        "required": ["sheet", "cell"],
        "additionalProperties": False,
        "properties": {"sheet": {"type": "string"}, "cell": {"type": "string"}},
    }
    region = {
        "type": "object",
        "required": ["sheet", "range", "labels", "evidence", "dependencies", "reason"],
        "additionalProperties": False,
        "properties": {
            "sheet": {"type": "string"},
            "range": {"type": "string"},
            "labels": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            "evidence": {"type": "array", "maxItems": 100, "items": ref},
            "dependencies": {"type": "array", "maxItems": 100, "items": ref},
            "reason": {"type": "string"},
        },
    }
    schema = {
        "type": "object",
        "required": ["physical_regions", "logical_documents", "layout_references"],
        "additionalProperties": False,
        "properties": {
            "physical_regions": {"type": "array", "minItems": 1, "items": region},
            "logical_documents": {"type": "array", "items": {"type": "string"}},
            "layout_references": {"type": "array", "items": {"type": "string"}},
        },
    }
    cells = [
        {"sheet": "表", "cell": "A1", "value": "标题", "kind": "review"},
        {"sheet": "表", "cell": "D11", "value": "说明", "kind": "review", "context_only": True},
    ]
    _, refs, id_schema = reference_contract(cells, schema)
    data = {
        "physical_regions": [
            {
                "sheet": "表",
                "range": "A1:B4",
                "primary_id": "S1:A1",
                "evidence_ids": ["S1:A1"],
                "dependency_ids": ["S1:D11"],
                "reason": "主体与上下文",
            }
        ],
        "logical_documents": [],
        "layout_references": [],
    }
    return refs, id_schema, schema, data


def test_id_mapping_preserves_source_and_original_schema():
    refs, id_schema, schema, data = contract()
    result = normalize_reference_ids(data, refs, id_schema, schema)
    assert result["physical_regions"][0]["evidence"] == [{"sheet": "表", "cell": "A1"}]
    assert result["physical_regions"][0]["dependencies"] == [{"sheet": "表", "cell": "D11"}]
    assert data["physical_regions"][0]["evidence_ids"] == ["S1:A1"]


def test_rejects_sheet_as_cell_and_unread_phantom_region():
    refs, id_schema, schema, data = contract()
    wrong = deepcopy(data)
    wrong["physical_regions"][0]["sheet"] = "D11"
    with pytest.raises(ReviewedExcelError, match="白名单"):
        normalize_reference_ids(wrong, refs, id_schema, schema)
    wrong = deepcopy(data)
    wrong["physical_regions"][0]["evidence_ids"] = ["D11"]
    with pytest.raises(ReviewedExcelError, match="白名单"):
        normalize_reference_ids(wrong, refs, id_schema, schema)
    wrong = deepcopy(data)
    wrong["physical_regions"][0]["range"] = "A50:T166"
    with pytest.raises(ReviewedExcelError, match="主体证据"):
        normalize_reference_ids(wrong, refs, id_schema, schema)
    wrong = deepcopy(data)
    wrong["physical_regions"][0]["primary_id"] = "S1:D11"
    with pytest.raises(ReviewedExcelError, match="白名单"):
        normalize_reference_ids(wrong, refs, id_schema, schema)
    wrong = deepcopy(data)
    wrong["physical_regions"][0]["evidence_ids"] = ["S1:D11"]
    with pytest.raises(ReviewedExcelError, match="白名单"):
        normalize_reference_ids(wrong, refs, id_schema, schema)


def test_grouping_uses_only_validated_region_and_evidence_ids(monkeypatch):
    from types import SimpleNamespace

    from app.application import reviewed_excel_grouping as grouping
    from app.application import reviewed_excel_template as template

    source = {
        "source_sha256": "test",
        "source_sheet_prefixes": [{"sheet": "表", "prefix": "S1"}],
        "fragments": [{"sheet": "表", "range": "A1:A2", "labels": ["unknown"], "reason": ""}],
        "cells": [{"sheet": "表", "cell": "A1", "value": "标题", "kind": "review"}],
    }
    monkeypatch.setattr(grouping, "prepare_grouping", lambda *_: source)
    group = {
        "ranges": [
            {"sheet_name": "表", "row_start": 1, "row_end": 2, "column_start": 1, "column_end": 1}
        ],
        "reason": "主体",
    }
    monkeypatch.setattr(
        template, "_template_llm_complete", lambda *a, **k: SimpleNamespace(data={"documents": [group]})
    )
    result = grouping.group_semantic_fragments({}, {})
    assert result[0]["fragments"] == [{"sheet": "表", "range": "A1:A2"}]
    assert result[0]["model_range_response"] == group
    group["ranges"][0]["row_end"] = 999
    with pytest.raises(ReviewedExcelError, match="白名单"):
        grouping.group_semantic_fragments({}, {})


def test_primary_formula_and_merge_constraints_do_not_infer_business_identity():
    from app.application.reviewed_excel_reference_ids import integrity_constraints

    cells = [
        {
            "sheet": "表",
            "cell": "A1",
            "evidence_id": "E0001",
            "kind": "formula",
            "value": "=SUM(B2:B5)",
        },
        {
            "sheet": "表",
            "cell": "A2",
            "evidence_id": "E0002",
            "kind": "formula",
            "value": '=INDIRECT("B2")',
        },
        {
            "sheet": "表",
            "cell": "A5",
            "evidence_id": "E0003",
            "kind": "formula",
            "value": "=C1",
            "context_only": True,
        },
    ]
    result = integrity_constraints(
        cells, [{"sheet": "表", "merged": ["A1:B1"], "merged_omitted": 2}]
    )
    assert result["primary_rows"] == [{"sheet": "表", "primary_row_spans": [[1, 2]]}]
    assert result["formula_references"][0] == {
        "evidence_id": "E0001",
        "references": [{"sheet": "表", "range": "B2:B5"}],
        "unresolved": False,
    }
    assert result["formula_references"][1]["unresolved"] is True
    assert len(result["formula_references"]) == 2
    assert result["merged_ranges"][0]["omitted"] == 2


def test_independent_prompt_has_only_source_facts_and_no_program_candidates(monkeypatch):
    import json
    from types import SimpleNamespace

    from app.application import reviewed_excel_template as template
    from app.application.reviewed_excel_classification import _classify_semantic_batch
    from tests.fixtures.etl_template.sources.generate import sample

    monkeypatch.setenv("FHD_TEMPLATE_LLM_PROVIDER", "mimo")
    captured = {}

    def fake(messages, schema, tokens):
        captured["messages"] = messages
        captured["schema"] = schema
        payload = json.loads(messages[1]["content"])
        return SimpleNamespace(model="fixture", data=synthetic_document_answer(payload))

    monkeypatch.setattr(template, "_template_mimo_complete", fake)
    result = _classify_semantic_batch(template.inspect_workbook(sample()), reference_ids=True)
    payload = json.loads(captured["messages"][1]["content"])
    assert not {"rule_hints", "structure_map", "relationship_context", "labels"} & payload.keys()
    properties = payload["output_schema"]["properties"]["documents"]["items"]["properties"]
    assert "labels" not in properties
    assert "unknown" not in captured["messages"][0]["content"]
    assert (
        "every supplied primary cell is covered exactly once" in captured["messages"][0]["content"]
    )
    assert payload["cells"] and payload["integrity_constraints"]["merged_ranges"]
    assert result["regions"][0]["labels"] == ["unknown"]
    assert (
        result["input_summary"]["reference_response"]["documents"][0]["ranges"][0]["row_start"] == 1
    )


def test_neutral_batches_do_not_invoke_business_prefilter(monkeypatch):
    from app.application import reviewed_excel_classification as classification
    from app.application.reviewed_excel_template import inspect_workbook
    from tests.fixtures.etl_template.sources.generate import large_quotation

    monkeypatch.setattr(
        classification,
        "classify_review_workbook",
        lambda _: (_ for _ in ()).throw(AssertionError("business hints invoked")),
    )
    review = inspect_workbook(large_quotation())
    batches, budget = classification.plan_semantic_batches(review, 4, neutral=True)
    keys = [
        (cell["sheet"], cell["cell"])
        for batch in batches
        for cell in batch
        if not cell.get("context_only")
    ]
    assert len(keys) == len(set(keys)) == len(review["cells"])
    from app.application.reviewed_excel_evidence import MAX_MODEL_CELLS

    assert all(len(batch) <= MAX_MODEL_CELLS for batch in batches) and budget == 4


def test_source_coordinate_ids_are_stable_across_batches_and_special_sheet_names():
    _, _, schema, _ = contract()
    sheets = [{"sheet": "先行"}, {"sheet": "O'Brien ! 表"}, {"sheet": "S1"}]
    cells = [
        {"sheet": "O'Brien ! 表", "cell": "C17", "value": "synthetic", "kind": "review"},
        {"sheet": "S1", "cell": "C17", "value": "synthetic", "kind": "review"},
    ]
    presented, refs, _ = reference_contract(cells, schema, sheets=sheets)
    assert [cell["evidence_id"] for cell in presented] == ["S2:C17", "S3:C17"]
    assert refs["S2:C17"]["ref"] == {"sheet": "O'Brien ! 表", "cell": "C17"}
    for cell in cells:
        one, one_refs, _ = reference_contract([cell], schema, sheets=sheets)
        key = one[0]["evidence_id"]
        assert key in refs and one_refs[key] == refs[key]
    assert cells[0] == {
        "sheet": "O'Brien ! 表",
        "cell": "C17",
        "value": "synthetic",
        "kind": "review",
    }


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("primary_id", "S1:B1", "白名单"),
        ("primary_id", "S2:A1", "白名单"),
        ("primary_id", "E0001", "白名单"),
        ("range", "B1:B1", "主体证据"),
        ("evidence_ids", ["S1:A1"] * 101, "白名单"),
    ],
)
def test_coordinate_contract_rejects_unknown_blank_and_oversized_responses(field, value, error):
    refs, id_schema, schema, data = contract()
    original = deepcopy(data)
    data["physical_regions"][0][field] = value
    with pytest.raises(ReviewedExcelError, match=error):
        normalize_reference_ids(data, refs, id_schema, schema)
    assert data["physical_regions"][0][field] == value
    assert original["physical_regions"][0]["primary_id"] == "S1:A1"


def test_coordinate_contract_keeps_blank_space_inside_evidenced_region():
    refs, id_schema, schema, data = contract()
    result = normalize_reference_ids(data, refs, id_schema, schema)
    assert result["physical_regions"][0]["range"] == "A1:B4"
    assert result["physical_regions"][0]["evidence"] == [{"sheet": "表", "cell": "A1"}]


def test_coordinate_primary_cannot_borrow_other_sent_cell():
    _, _, original, _ = contract()
    cells = [
        {"sheet": "表", "cell": "A1", "value": "first", "kind": "review"},
        {"sheet": "表", "cell": "C1", "value": "second", "kind": "review"},
    ]
    _, refs, schema = reference_contract(cells, original)
    data = {
        "physical_regions": [
            {
                "sheet": "表",
                "range": "C1",
                "primary_id": "S1:A1",
                "evidence_ids": ["S1:C1"],
                "dependency_ids": [],
                "reason": "synthetic",
            }
        ],
        "logical_documents": [],
        "layout_references": [],
    }
    with pytest.raises(ReviewedExcelError, match="主体证据"):
        normalize_reference_ids(data, refs, schema, original)
    assert data["physical_regions"][0]["primary_id"] == "S1:A1"
    data["physical_regions"][0]["primary_id"] = "S1:C1"
    result = normalize_reference_ids(data, refs, schema, original)
    assert result["physical_regions"][0]["evidence"] == [{"sheet": "表", "cell": "C1"}]
