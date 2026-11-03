"""Analyze must keep closed label vocab and survive freestyle model labels (佳诺 #3)."""

from __future__ import annotations

import base64
import json
from io import BytesIO
from types import SimpleNamespace

from openpyxl import Workbook

from app.application.reviewed_excel_audit import claim_request, record_response
from app.application.reviewed_excel_classification import _classify_semantic_batch
from app.application.reviewed_excel_partition import (
    DOCUMENT_LABELS,
    coerce_payload_document_labels,
    normalize_document_labels,
)
from app.application.reviewed_excel_reference_ids import neutralize_messages
from app.application.reviewed_excel_reference_prompts import SOURCE_PROTOCOL
from app.application.reviewed_excel_template import inspect_workbook


def _delivery_review():
    book = Workbook()
    sheet = book.active
    sheet.title = "送货单"
    sheet["A1"] = "送货单"
    sheet["A3"] = "供货单位"
    sheet["B3"] = "示例厂"
    sheet["A7"] = "品名"
    sheet["B7"] = "数量"
    sheet["A8"] = "涂料"
    sheet["B8"] = "1"
    stream = BytesIO()
    book.save(stream)
    return inspect_workbook(stream.getvalue())


def test_normalize_document_labels_maps_freestyle_to_unknown():
    assert normalize_document_labels(["title", "footnote"]) == ["unknown"]
    assert normalize_document_labels(["delivery", "title"]) == ["delivery"]
    assert normalize_document_labels(["unknown", "delivery"]) == ["delivery"]
    assert set(DOCUMENT_LABELS) >= {"delivery", "unknown"}


def test_neutralize_keeps_closed_label_vocab_and_drops_business_hints():
    payload = {
        "sheets": [{"sheet": "送货单", "merged": []}],
        "cells": [{"sheet": "送货单", "cell": "A1", "value": "送货单", "kind": "review"}],
        "batch_coverage": [{"sheet": "送货单", "total_nonempty": 1}],
        "structure_map": [{"sheet": "送货单"}],
        "rule_hints": [{"hint": "x"}],
        "relationship_context": {"x": 1},
        "labels": sorted(DOCUMENT_LABELS),
        "output_schema": {"type": "object"},
    }
    messages = [
        {"role": "system", "content": ""},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    neutralize_messages(messages)
    kept = json.loads(messages[1]["content"])
    assert kept["labels"] == sorted(DOCUMENT_LABELS)
    assert not {"rule_hints", "structure_map", "relationship_context"} & kept.keys()
    assert messages[0]["content"] == SOURCE_PROTOCOL


def test_prepare_only_analyze_request_keeps_labels_and_schema_enum():
    request = _classify_semantic_batch(_delivery_review(), prepare_only=True, reference_ids=False)
    payload = json.loads(request["messages"][1]["content"])
    assert payload["labels"] == sorted(DOCUMENT_LABELS)
    label_schema = request["schema"]["properties"]["physical_regions"]["items"]["properties"][
        "labels"
    ]
    assert label_schema["items"]["enum"] == sorted(DOCUMENT_LABELS)


def test_freestyle_labels_are_coerced_and_analyze_batch_succeeds(monkeypatch):
    review = _delivery_review()
    prepared = _classify_semantic_batch(review, prepare_only=True, reference_ids=False)
    payload = json.loads(prepared["messages"][1]["content"])
    cells = payload["cells"]
    # One region covering every supplied primary cell with freestyle labels (佳诺 shape).
    sheet = cells[0]["sheet"]
    coords = [cell["cell"] for cell in cells if cell["sheet"] == sheet]
    # Use a bounding range of all cells on the sheet for a simple valid geometry.
    from openpyxl.utils import get_column_letter
    from openpyxl.utils.cell import column_index_from_string, coordinate_from_string

    rows = []
    cols = []
    for cell in coords:
        col, row = coordinate_from_string(cell)
        rows.append(row)
        cols.append(column_index_from_string(col))
    area = f"{get_column_letter(min(cols))}{min(rows)}:{get_column_letter(max(cols))}{max(rows)}"
    freestyle = {
        "physical_regions": [
            {
                "sheet": sheet,
                "range": area,
                "labels": ["title", "parties", "line item table", "footnote"],
                "evidence": [{"sheet": sheet, "cell": coords[0]}],
                "dependencies": [],
                "reason": "freestyle labels from failover model",
            }
        ],
        "logical_documents": [],
        "layout_references": [],
    }
    coerced = coerce_payload_document_labels(json.loads(json.dumps(freestyle)))
    assert coerced["physical_regions"][0]["labels"] == ["unknown"]

    monkeypatch.setattr(
        "app.application.reviewed_excel_template._template_platform_complete",
        lambda *args, **kwargs: SimpleNamespace(
            used_llm=True, model="mimo-v2.6-flash", data=freestyle, provider="xiaomi"
        ),
    )
    result = _classify_semantic_batch(review, reference_ids=False)
    assert result["regions"]
    assert result["regions"][0]["labels"] == ["unknown"]


def test_record_response_stores_actual_model_and_failover_from():
    state: dict = {}
    request = {
        "messages": [{"role": "user", "content": "{}"}],
        "schema": {"type": "object"},
        "max_tokens": 16,
    }
    digest = claim_request(
        state,
        request,
        source_sha256="a" * 64,
        version="b" * 64,
        classification_id="00000000-0000-0000-0000-000000000001",
        code_version="test",
        model="platform-default",
        phase="classification",
    )
    body = json.dumps(
        {
            "ok": True,
            "content": "{}",
            "provider": "xiaomi",
            "model": "mimo-v2.6-flash",
            "failover_from": "doubao/deepseek-r1-250120",
            "usage": {"total_tokens": 1},
        }
    ).encode()
    record_response(state, digest, body, 200, "req-1")
    entry = state["model_audit"][-1]
    assert entry["model"] == "mimo-v2.6-flash"
    assert entry["provider"] == "xiaomi"
    assert entry["failover_from"] == "doubao/deepseek-r1-250120"
    assert entry["http_status"] == 200
    assert base64.b64decode(entry["response_base64"]) == body
