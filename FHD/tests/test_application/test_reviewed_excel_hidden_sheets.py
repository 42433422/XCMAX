"""Hidden source sheets remain archived, but are not standalone template choices."""

import hashlib
import json
from io import BytesIO

import pytest
from openpyxl import Workbook, load_workbook

from app.application.elt.errors import ReviewedExcelError
from app.application.reviewed_excel_classification import classify_review_workbook
from app.application.reviewed_excel_template import derive_document_workbook, inspect_workbook
from tests.test_application.test_reviewed_excel_template import review_store as review_store


def hidden_first_workbook(state):
    workbook = Workbook()
    hidden = workbook.active
    hidden.title = "Internal"
    hidden.append(["Synthetic internal", 1])
    hidden.sheet_state = state
    visible = workbook.create_sheet("Visible")
    visible.append(["Synthetic visible", 2])
    workbook.active = 1
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


@pytest.mark.parametrize("scope", ["full", "visible", "legacy_visible"])
def test_checkpoint_restores_saved_sheet_scope_and_rejects_missing_cells(scope):
    from app.application.reviewed_excel_evidence import prepare_auto_slice_review
    from app.application.reviewed_excel_plan import restore_checkpoint_review
    from tests.test_application.test_reviewed_excel_budget import saved_plan

    review = inspect_workbook(hidden_first_workbook("hidden"))
    scoped = (
        review if scope == "full" else prepare_auto_slice_review(review, skip_hidden_sheets=True)
    )
    checkpoint = saved_plan(scoped, [scoped["cells"]])
    if scope == "visible":
        checkpoint["skip_hidden_sheets"] = True
    restored, batches = restore_checkpoint_review(review, checkpoint)
    assert restored["sheets"] == scoped["sheets"]
    assert batches == [[{**cell, "context_only": False} for cell in scoped["cells"]]]
    assert review["sheets"] == ["Internal", "Visible"]
    with pytest.raises(ReviewedExcelError, match="坐标计划"):
        restore_checkpoint_review({**review, "cells": []}, checkpoint)


@pytest.mark.parametrize("state", ["hidden", "veryHidden"])
def test_classification_marks_hidden_unprocessable_without_omitting_or_unhiding(state):
    body = hidden_first_workbook(state)
    info = inspect_workbook(body)
    sheets = classify_review_workbook(info)
    assert [sheet["sheet"] for sheet in sheets] == ["Internal", "Visible"]
    assert sheets[0]["sheet_state"] == state and sheets[0]["processable"] is False
    assert "隐藏工作表" in sheets[0]["processing_message"]
    assert sheets[1]["sheet_state"] == "visible" and sheets[1]["processable"] is True
    with pytest.raises(ReviewedExcelError, match="隐藏工作表"):
        derive_document_workbook(body, [{"sheet": "Internal", "range": "A1:B1"}])
    derived = derive_document_workbook(body, [{"sheet": "Visible", "range": "A1:B1"}])
    assert load_workbook(BytesIO(derived)).sheetnames == ["Visible"]
    assert inspect_workbook(body)["sha256"] == hashlib.sha256(body).hexdigest()
    original = load_workbook(BytesIO(body))
    assert original["Internal"].sheet_state == state
    original.close()


def test_archive_classification_exposes_visibility_and_hidden_preview_stays_400(review_store):
    body = hidden_first_workbook("hidden")
    client = review_store.client
    response = client.post(
        "/api/templates/reviewed-excel/archive-classify",
        data={"expected_actor": "1:7", "request_key": "synthetic-hidden-first"},
        files={"file": ("synthetic.xlsx", body)},
    )
    assert response.status_code == 200, response.text
    classification = response.json()
    sheets = classification["sheets"]
    assert sheets[0]["processable"] is False and sheets[1]["processable"] is True
    base = f"/api/templates/reviewed-excel/classifications/{classification['classification_id']}"
    labels = [
        {"sheet": sheet["sheet"], "range": region["range"], "labels": region["labels"]}
        for sheet in sheets
        for region in sheet["regions"]
    ]
    confirmed = client.post(
        base + "/confirm",
        data={"version": classification["version"], "labels_json": json.dumps(labels)},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["sheets"][0]["processable"] is False
    params = {
        "expected_actor": "1:7",
        "classification_id": classification["classification_id"],
        "classification_version": confirmed.json()["version"],
        "region_sheet": "Internal",
        "region_range": "A1:B1",
    }
    blocked = client.post(
        "/api/templates/reviewed-excel/preview",
        data=params,
        files={"file": ("synthetic.xlsx", body)},
    )
    assert blocked.status_code == 400 and "隐藏工作表" in blocked.text
    assert inspect_workbook(body)["sha256"] == hashlib.sha256(body).hexdigest()


def test_route_ignores_only_hidden_refusal_and_hidden_coverage(monkeypatch):
    from types import SimpleNamespace

    from app.fastapi_routes import reviewed_excel_template as routes

    body = hidden_first_workbook("hidden")
    visible = {"sheet": "Visible", "range": "A1:B1"}
    latest = {
        "version": "saved",
        "model_status": "returned",
        "sheets": [
            {"sheet": "Internal", "sheet_state": "hidden", "regions": []},
            {"sheet": "Visible", "regions": [{"range": "A1:B1", "range_source": "model"}]},
        ],
        "coverage": [
            {"sheet": "Internal", "total": 2, "sent": 0, "unread": 2},
            {"sheet": "Visible", "total": 2, "sent": 2},
        ],
        "input_summaries": [
            {
                "source_coverage": {"can_slice": False},
                "reference_index": {"r1": {"ref": {"sheet": "Internal"}}},
            }
        ],
        "suggested_documents": [{"fragments": [visible]}],
    }
    run = SimpleNamespace(
        draft_json=json.dumps({"versions": [latest]}), file_sha256=inspect_workbook(body)["sha256"]
    )
    monkeypatch.setattr(routes, "_classification_run", lambda *_: run)
    monkeypatch.setattr(routes, "_source", lambda *_: body)
    slices, _, _ = routes._auto_slices(None, "saved", "saved", 1, 7)
    assert [s["fragments"] for s in slices] == [[visible]]
    latest["input_summaries"][0]["reference_index"]["r1"]["ref"]["sheet"] = "Visible"
    run.draft_json = json.dumps({"versions": [latest]})
    with pytest.raises(ReviewedExcelError, match="不能自动切片"):
        routes._auto_slices(None, "saved", "saved", 1, 7)
