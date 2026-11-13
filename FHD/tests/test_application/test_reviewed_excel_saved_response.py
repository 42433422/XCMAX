import base64
import hashlib
import json

import pytest

from app.application.elt.errors import ReviewedExcelError
from app.application.reviewed_excel_audit import request_digest
from app.application.reviewed_excel_saved_response import saved_classification_answer


def record():
    answer = '{"documents":[]}] , "can_slice":false}'
    body = (
        "event: delta\ndata: "
        + json.dumps({"delta": answer})
        + "\n\n"
        + "event: done\ndata: "
        + json.dumps({"ok": True, "content": answer})
        + "\n\n"
    ).encode()
    request = {"messages": [], "schema": {}, "max_tokens": 1}
    return {
        "state": "answered_invalid",
        "phase": "classification",
        "classification_id": "id",
        "classification_version": "v1",
        "source_sha256": "source",
        "http_status": 200,
        "request": request,
        "request_sha256": request_digest(request),
        "response_base64": base64.b64encode(body).decode(),
        "response_sha256": hashlib.sha256(body).hexdigest(),
    }


def test_reads_original_answer_without_calling_model():
    row = record()
    answer, request = saved_classification_answer(row, "id", "v1", "source")
    assert answer.endswith('"can_slice":false}')
    assert request == row["request"]
    assert row["state"] == "answered_invalid"


@pytest.mark.parametrize(
    "field,value",
    [
        ("classification_id", "other"),
        ("source_sha256", "other"),
        ("classification_version", "other"),
        ("state", "unknown"),
        ("request_sha256", "other"),
        ("response_sha256", "other"),
    ],
)
def test_rejects_stale_identity_or_tampered_receipt(field, value):
    row = record()
    row[field] = value
    with pytest.raises(ReviewedExcelError):
        saved_classification_answer(row, "id", "v1", "source")


def test_rejects_incomplete_or_inconsistent_stream():
    row = record()
    body = b'event: delta\ndata: {"delta":"incomplete"}\n\n'
    row["response_base64"] = base64.b64encode(body).decode()
    row["response_sha256"] = hashlib.sha256(body).hexdigest()
    with pytest.raises(ReviewedExcelError):
        saved_classification_answer(row, "id", "v1", "source")


def test_recovery_endpoint_revalidates_once_without_model_or_cross_tenant_access(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace

    from fastapi import HTTPException

    from app.application.reviewed_excel_budget import BUDGET_VERSION
    from app.application.reviewed_excel_classification import _classify_semantic_batch
    from app.application.reviewed_excel_plan import store_coordinate_plan
    from app.application.reviewed_excel_template import inspect_workbook
    from app.fastapi_routes import reviewed_excel_template as routes
    from tests.fixtures.elt_template.sources.generate import sample
    from tests.test_application.test_reviewed_excel_boundaries import synthetic_document_answer

    body = sample()
    review = inspect_workbook(body)
    batches = [review["cells"]]
    prepared = _classify_semantic_batch(review, prepare_only=True, reference_ids=True)
    model = synthetic_document_answer(json.loads(prepared["messages"][1]["content"]))
    model["can_slice"] = False
    answer = (
        json.dumps({"documents": model["documents"]}, ensure_ascii=False) + '],"can_slice":false}'
    )
    stream = (
        "event: delta\ndata: "
        + json.dumps({"delta": answer})
        + "\n\n"
        + "event: done\ndata: "
        + json.dumps({"ok": True, "content": answer})
        + "\n\n"
    ).encode()
    sha = hashlib.sha256(body).hexdigest()
    checkpoint = {
        "phase": "failed",
        "version": "v1",
        "source_sha256": sha,
        "budget_version": BUDGET_VERSION,
        "results": [],
        "total": 1,
        "max_calls": 1,
        "calls_in_round": 1,
        "auto_group": True,
        "repair": {"step": 0, "exhausted": True},
    }
    store_coordinate_plan(checkpoint, batches)
    audit = {
        "state": "answered_invalid",
        "phase": "classification",
        "classification_id": "id",
        "classification_version": "v1",
        "source_sha256": sha,
        "http_status": 200,
        "request": prepared,
        "request_sha256": request_digest(prepared),
        "response_base64": base64.b64encode(stream).decode(),
        "response_sha256": hashlib.sha256(stream).hexdigest(),
    }
    run = SimpleNamespace(
        draft_json=json.dumps(
            {
                "versions": [{"version": "v1"}],
                "analysis_checkpoint": checkpoint,
                "model_audit": [audit],
            }
        ),
        file_sha256=sha,
    )
    monkeypatch.setattr(routes, "tenant_scope", lambda *_: nullcontext())
    monkeypatch.setattr(routes, "get_db", lambda: nullcontext(object()))

    def find_run(_db, _id, tenant, owner):
        if (tenant, owner) != (1, 7):
            raise HTTPException(status_code=404)
        return run

    monkeypatch.setattr(routes, "_classification_run", find_run)
    monkeypatch.setattr(routes, "_source", lambda *_: body)
    monkeypatch.setattr(routes, "_recheck", lambda *_: None)
    monkeypatch.setattr(
        routes,
        "_classification_cas",
        lambda _db, _run, old, state: setattr(run, "draft_json", json.dumps(state)),
    )
    monkeypatch.setattr(
        "app.application.reviewed_excel_template._template_platform_complete",
        lambda *_a, **_kw: pytest.fail("model called"),
    )
    result = routes.reviewed_excel_recover_answer(
        "id", None, "v1", SimpleNamespace(tenant_id=1, id=7)
    )
    assert result["checkpoint"]["completed"] == 1 and result["can_slice"] is False
    state = json.loads(run.draft_json)
    assert state["model_audit"] == [audit] and len(state["saved_response_revalidations"]) == 1
    again = routes.reviewed_excel_recover_answer(
        "id", None, "v1", SimpleNamespace(tenant_id=1, id=7)
    )
    assert again["replayed"] is True and again["checkpoint"]["completed"] == 1
    with pytest.raises(HTTPException) as denied:
        routes.reviewed_excel_recover_answer("id", None, "v1", SimpleNamespace(tenant_id=2, id=7))
    assert denied.value.status_code == 404


def test_model_refusal_blocks_automatic_slicing_even_when_fully_covered(monkeypatch):
    from types import SimpleNamespace

    from app.fastapi_routes import reviewed_excel_template as routes

    latest = {
        "version": "v1",
        "model_status": "returned",
        "coverage": [],
        "input_summaries": [{"source_coverage": {"can_slice": False}}],
    }
    run = SimpleNamespace(draft_json=json.dumps({"versions": [latest]}))
    monkeypatch.setattr(routes, "_classification_run", lambda *_: run)
    monkeypatch.setattr(routes, "_source", lambda *_: b"source")
    with pytest.raises(ReviewedExcelError, match="不能自动切片"):
        routes._auto_slices(None, "id", "v1", 1, 7)
