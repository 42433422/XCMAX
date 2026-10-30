import json
from io import BytesIO

import pytest
from openpyxl import Workbook

from app.application.etl.errors import ReviewedExcelError
from app.application.reviewed_excel_classification import _classify_semantic_batch
from app.application.reviewed_excel_grouping import group_semantic_fragments
from app.application.reviewed_excel_reference_ids import (
    IDENTIFY_PROMPT,
    contract_hashes,
    verify_contract,
)
from app.application.reviewed_excel_template import inspect_workbook


def test_independent_contract_is_identical_for_unseen_structures(monkeypatch):
    monkeypatch.setenv("FHD_TEMPLATE_LLM_PROVIDER", "mimo")
    hashes = []
    for sheet_name, address, merged in [
        ("甲", "B3", False),
        ("测试", "C8", True),
        ("Other", "F5", False),
    ]:
        book = Workbook()
        sheet = book.active
        sheet.title = sheet_name
        sheet[address] = "synthetic title"
        sheet["A12"] = "synthetic data"
        if merged:
            sheet.merge_cells("C8:D8")
        stream = BytesIO()
        book.save(stream)
        review = inspect_workbook(stream.getvalue())
        prepared = _classify_semantic_batch(review, prepare_only=True, reference_ids=True)
        payload = json.loads(prepared["messages"][1]["content"])
        assert prepared["messages"][0]["content"] == IDENTIFY_PROMPT
        assert (
            not {"rule_hints", "structure_map", "relationship_context", "labels"} & payload.keys()
        )
        assert (
            "labels"
            not in prepared["schema"]["properties"]["physical_regions"]["items"]["properties"]
        )
        hashes.append(
            verify_contract(prepared["messages"][0]["content"], prepared["schema"], "identify")
        )
    assert hashes[0] == hashes[1] == hashes[2]
    assert (
        hashes[0]["schema_template_sha256"]
        == "e2e1ceb650586cdc2954e2e622e6807a03a3fec251aa122dc17d1fdd6dc01b4a"
    )
    with pytest.raises(ReviewedExcelError, match="契约"):
        verify_contract(IDENTIFY_PROMPT + " changed", prepared["schema"], "identify")


def test_grouping_contract_has_stable_template_across_model_fragments():
    fingerprints = []
    for sheet, cell in [("Alpha", "B5"), ("乙", "C9")]:
        review = {
            "sha256": "synthetic",
            "sheets": [sheet],
            "cells": [{"sheet": sheet, "cell": cell, "value": "synthetic", "kind": "text"}],
        }
        classification = {
            "source_sha256": "synthetic",
            "coverage": [{"sheet": sheet, "unread": [], "unassigned": [], "merged_omitted": 0}],
            "regions": [
                {
                    "sheet": sheet,
                    "range": f"{cell}:{cell}",
                    "evidence": [{"sheet": sheet, "cell": cell}],
                }
            ],
        }
        request = group_semantic_fragments(review, classification, prepare_only=True)
        fingerprints.append(contract_hashes(request["schema"], "group"))
    assert fingerprints[0] == fingerprints[1]
    assert (
        fingerprints[0]["schema_template_sha256"]
        == "f0f500cbbf7f3925cae7f6885e51a46c92cb4069a8ded998c2724fdc4ba5f379"
    )
