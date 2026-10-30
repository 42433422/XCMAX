"""Synthetic-only transport budgeting regressions; no provider credentials/calls."""

import json
from copy import deepcopy
from io import BytesIO

import pytest
from openpyxl import Workbook

from app.application.etl.errors import ReviewedExcelError
from app.application.reviewed_excel_audit import request_digest
from app.application.reviewed_excel_budget import (
    BUDGET_VERSION,
    MAX_OUTPUT_TOKENS,
    MAX_REQUEST_BYTES,
    RequestBudgetExceeded,
    fit_transport_batches,
    output_budget,
    request_bytes,
    validate_checkpoint_budget,
    validate_remaining_audit_budget,
)
from app.application.reviewed_excel_classification import _classify_semantic_batch
from app.application.reviewed_excel_evidence import (
    MAX_MODEL_TEXT_BYTES,
    _model_cell_cost,
    plan_semantic_batches,
)
from app.application.reviewed_excel_template import inspect_workbook


def workbook_review(rows=120, *, formulas=True):
    book = Workbook()
    sheet = book.active
    sheet.title = "Synthetic"
    for row in range(1, rows + 1):
        sheet.cell(
            row, 1, "=SUM(" + ",".join(f"B{i}" for i in range(1, 26)) + ")" if formulas else "x"
        )
    stream = BytesIO()
    book.save(stream)
    return inspect_workbook(stream.getvalue())


def test_complete_request_includes_dense_formulas_schema_and_preserves_all_cells(monkeypatch):
    monkeypatch.delenv("FHD_TEMPLATE_LLM_PROVIDER", raising=False)
    review = workbook_review()
    assert sum(map(_model_cell_cost, review["cells"])) < MAX_MODEL_TEXT_BYTES
    with pytest.raises(RequestBudgetExceeded):
        _classify_semantic_batch(review, prepare_only=True, reference_ids=True)
    original = deepcopy(review)
    batches, rounds = plan_semantic_batches(review, 4, neutral=True)
    assert 1 < len(batches) <= 99 and rounds == 4
    found = []
    for batch in batches:
        prepared = _classify_semantic_batch(
            {**review, "cells": batch, "full_cells": review["cells"]},
            prepare_only=True,
            reference_ids=True,
        )
        assert request_bytes(prepared) <= MAX_REQUEST_BYTES
        payload = json.loads(prepared["messages"][1]["content"])
        assert payload["integrity_constraints"]["formula_references"]
        assert payload["output_schema"] == prepared["schema"]
        found.extend(c["cell"] for c in batch if not c.get("context_only"))
    assert sorted(found) == sorted(c["cell"] for c in review["cells"])
    assert len(found) == len(set(found))
    assert review == original


def test_single_row_overhead_budget_rejects_before_provider(monkeypatch):
    review = workbook_review(1)
    monkeypatch.setattr("app.application.reviewed_excel_budget.MAX_REQUEST_BYTES", 100)
    monkeypatch.setattr(
        "app.application.reviewed_excel_template._template_mimo_complete",
        lambda *a: pytest.fail("must not call provider"),
    )
    with pytest.raises(RequestBudgetExceeded, match="单行"):
        plan_semantic_batches(review, neutral=True)


def test_oversized_primary_row_is_never_silently_dropped():
    review = workbook_review(2, formulas=False)
    review["cells"][0]["value"] = "x" * 100_000
    with pytest.raises(ReviewedExcelError, match="单行"):
        plan_semantic_batches(review, neutral=True)


def test_prepare_and_execution_use_identical_bounded_output_budget(monkeypatch):
    review = workbook_review(180, formulas=False)
    prepared = _classify_semantic_batch(review, prepare_only=True, reference_ids=True)
    assert 4000 < prepared["max_tokens"] <= MAX_OUTPUT_TOKENS
    monkeypatch.setenv("FHD_TEMPLATE_LLM_PROVIDER", "mimo")

    def capture(messages, schema, tokens):
        assert {"messages": messages, "schema": schema, "max_tokens": tokens} == prepared
        raise RuntimeError("synthetic provider boundary")

    monkeypatch.setattr("app.application.reviewed_excel_template._template_mimo_complete", capture)
    with pytest.raises(RuntimeError, match="synthetic provider boundary"):
        _classify_semantic_batch(
            review, reference_ids=True, expected_request_sha256=request_digest(prepared)
        )


def test_output_budget_is_bounded_and_ignores_repeated_context():
    assert output_budget([{}]) == 4000
    assert output_budget([{}] * 1000) == MAX_OUTPUT_TOKENS
    assert output_budget([{}] * 90 + [{"context_only": True}] * 400) == output_budget([{}] * 90)


@pytest.mark.parametrize("old", [{"results": []}, {"budget_version": "previous", "results": []}])
def test_old_or_different_budget_checkpoint_rejected_unchanged(old):
    before = deepcopy(old)
    with pytest.raises(ReviewedExcelError, match="原结果与审计保留"):
        validate_checkpoint_budget(old)
    assert old == before
    validate_checkpoint_budget({**old, "budget_version": BUDGET_VERSION})


def test_audit_reserves_group_and_counts_failed_and_not_sent():
    state = {"model_audit": [{"state": "failed"}, {"state": "not_sent"}]}
    checkpoint = {"results": [], "auto_group": True, "phase": "ready"}
    validate_remaining_audit_budget(state, checkpoint, 97)
    before = deepcopy(state)
    with pytest.raises(ReviewedExcelError, match="100条"):
        validate_remaining_audit_budget(state, checkpoint, 98)
    assert state == before


def test_plan_has_hard_audit_limit(monkeypatch):
    review = workbook_review(100, formulas=False)
    for i, cell in enumerate(review["cells"]):
        cell["sheet"] = f"S{i}"
    review["sheets"] = [c["sheet"] for c in review["cells"]]
    monkeypatch.setattr(
        "app.application.reviewed_excel_classification._classify_semantic_batch", lambda *a, **k: {}
    )
    with pytest.raises(RequestBudgetExceeded, match="99批"):
        fit_transport_batches(review, [[c] for c in review["cells"]])


@pytest.mark.parametrize("round_budget", [0, 5])
def test_per_round_budget_still_one_to_four(round_budget):
    with pytest.raises(ReviewedExcelError, match="1 至 4"):
        plan_semantic_batches(workbook_review(1), round_budget, neutral=True)


@pytest.mark.parametrize("value", ["0", "181", "nan", "inf", "not-a-number"])
def test_template_timeout_rejects_invalid_configuration(value, monkeypatch):
    from app.application.reviewed_excel_audit import ModelRequestNotSent
    from app.application.reviewed_excel_budget import template_timeout_seconds

    monkeypatch.setenv("FHD_TEMPLATE_LLM_TIMEOUT_SECONDS", value)
    with pytest.raises(ModelRequestNotSent):
        template_timeout_seconds()


def test_template_timeout_is_separate_from_etl_row_limit(monkeypatch):
    from app.application.reviewed_excel_budget import template_timeout_seconds

    monkeypatch.delenv("FHD_TEMPLATE_LLM_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setenv("FHD_ETL_LLM_TIMEOUT_SECONDS", "2")
    assert template_timeout_seconds() == 120
    monkeypatch.setenv("FHD_TEMPLATE_LLM_TIMEOUT_SECONDS", "180")
    assert template_timeout_seconds() == 180


def test_actual_prefix_request_sizes_are_monotone_with_fixed_edge_context():
    review = workbook_review(24)
    cells = review["cells"]
    edge_context = cells[:5] + cells[-5:]
    sizes = []
    for count in range(1, len(cells) + 1):
        selected = cells[:count]
        keys = {c["cell"] for c in selected}
        batch = selected + [
            {**c, "context_only": True} for c in edge_context if c["cell"] not in keys
        ]
        request = _classify_semantic_batch(
            {**review, "cells": batch, "full_cells": cells}, prepare_only=True, reference_ids=True
        )
        sizes.append(request_bytes(request))
    assert sizes == sorted(sizes)
    assert len(set(sizes)) == len(sizes)


def test_old_cell_chunk_boundaries_do_not_change_neutral_packing():
    review = workbook_review(300, formulas=False)
    cells = review["cells"]
    old_chunks = [cells[i : i + 75] for i in range(0, len(cells), 75)]
    combined = fit_transport_batches(review, [cells])
    repacked = fit_transport_batches(review, old_chunks)
    assert combined == repacked
    assert len(repacked) < len(old_chunks)
    assert sum(not c.get("context_only") for b in repacked for c in b) == 300


def test_full_width_primary_row_is_not_rejected_for_optional_context(monkeypatch):
    from openpyxl.utils.cell import get_column_letter

    review = {
        "sheets": ["S"],
        "cells": [
            {"sheet": "S", "cell": f"{get_column_letter(c)}2", "value": "x", "kind": "review"}
            for c in range(1, 501)
        ]
        + [{"sheet": "S", "cell": "A3", "value": "tail", "kind": "review"}],
    }
    monkeypatch.setattr(
        "app.application.reviewed_excel_classification._classify_semantic_batch", lambda *a, **k: {}
    )
    fitted = fit_transport_batches(review, [review["cells"][:500], review["cells"][500:]])
    assert len(fitted) == 2
    assert sum(not c.get("context_only") for c in fitted[0]) == 500
    assert sum(not c.get("context_only") for b in fitted for c in b) == 501
    assert all(len(b) <= 500 for b in fitted)


def saved_plan(review, batches):
    from app.application.reviewed_excel_plan import store_coordinate_plan

    checkpoint = {
        "budget_version": BUDGET_VERSION,
        "source_sha256": review["sha256"],
        "version": "synthetic-version",
        "max_calls": 2,
        "total": len(batches),
    }
    store_coordinate_plan(checkpoint, batches)
    return checkpoint


def test_coordinate_checkpoint_roundtrip_is_value_free_without_replanning(monkeypatch):
    from app.application.reviewed_excel_plan import restore_coordinate_plan

    review = workbook_review(120)
    batches, _ = plan_semantic_batches(review, 2, neutral=True)
    checkpoint = saved_plan(review, batches)
    assert "=SUM" not in json.dumps(checkpoint)
    monkeypatch.setattr(
        "app.application.reviewed_excel_classification._classify_semantic_batch",
        lambda *a, **k: pytest.fail("restore must not prepare the entire plan"),
    )
    rebuilt = restore_coordinate_plan(review, checkpoint)
    assert [[(c["cell"], bool(c.get("context_only"))) for c in b] for b in rebuilt] == [
        [(c["cell"], bool(c.get("context_only"))) for c in b] for b in batches
    ]
    assert [c["value"] for b in rebuilt for c in b] == [c["value"] for b in batches for c in b]


@pytest.mark.parametrize("tamper", ["missing", "digest", "source", "unknown", "duplicate", "omit"])
def test_coordinate_checkpoint_tampering_is_rejected(tamper):
    from app.application.reviewed_excel_plan import _digest, restore_coordinate_plan

    review = workbook_review(3, formulas=False)
    checkpoint = saved_plan(review, [review["cells"]])
    if tamper == "missing":
        checkpoint.pop("coordinate_plan")
    elif tamper == "digest":
        checkpoint["plan_digest"] = "0" * 64
    elif tamper == "source":
        checkpoint["source_sha256"] = "changed"
    else:
        if tamper == "unknown":
            checkpoint["coordinate_plan"][0][0][1] = "Z999"
        elif tamper == "duplicate":
            checkpoint["coordinate_plan"][0].append(checkpoint["coordinate_plan"][0][0])
        else:
            checkpoint["coordinate_plan"][0].pop()
        # Even a recomputed hash cannot authorize invalid coverage/coordinates.
        checkpoint["plan_digest"] = _digest(checkpoint)
    with pytest.raises(ReviewedExcelError, match="坐标计划"):
        restore_coordinate_plan(review, checkpoint)


def test_optional_large_context_never_excludes_valid_primary_rows():
    book = Workbook()
    sheet = book.active
    for row, count, length in [(1, 5, 3500), (2, 30, 2000), (3, 5, 3500)]:
        for col in range(1, count + 1):
            sheet.cell(row, col, "x" * length)
    stream = BytesIO()
    book.save(stream)
    review = inspect_workbook(stream.getvalue())
    for row in [1, 2, 3]:
        chosen = [c for c in review["cells"] if c["cell"].endswith(str(row))]
        prepared = _classify_semantic_batch(
            {**review, "cells": chosen, "full_cells": review["cells"]},
            prepare_only=True,
            reference_ids=True,
        )
        assert request_bytes(prepared) <= MAX_REQUEST_BYTES
    batches, _ = plan_semantic_batches(review, neutral=True)
    primary = [c["cell"] for b in batches for c in b if not c.get("context_only")]
    assert len(primary) == len(set(primary)) == 40
    for batch in batches:
        request = _classify_semantic_batch(
            {**review, "cells": batch, "full_cells": review["cells"]},
            prepare_only=True,
            reference_ids=True,
        )
        assert request_bytes(request) <= MAX_REQUEST_BYTES
