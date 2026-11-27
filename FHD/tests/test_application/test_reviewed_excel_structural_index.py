"""Tests for general workbook structural index (no customer hardcodes)."""

from __future__ import annotations

import json
from copy import deepcopy
from io import BytesIO

import pytest
from openpyxl import Workbook, load_workbook

from app.application.reviewed_excel_reference_ids import neutralize_messages
from app.application.reviewed_excel_structural_index import (
    SCHEMA_VERSION,
    _cap_candidate_ranges,
    attach_structural_index_to_draft,
    build_workbook_structural_index,
    compress_structural_index_for_model,
    ensure_review_structural_index,
    prefer_structural_classification_if_undersegmented,
)


def _sample_workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "出货台账"
    ws["A1"] = "厂名"
    ws["B1"] = "日期"
    ws["C1"] = "单号"
    ws["D1"] = "型号"
    # excel-ish serial dates + order keys
    rows = [
        (45000, 10),
        (45000, 10),
        (45001, 11),
        (45002, 12),
        (45003, 13),
        (45003, 13),
        (45004, 14),
        (45005, 15),
        (45006, 16),
    ]
    for i, (serial, order) in enumerate(rows, start=2):
        ws[f"A{i}"] = "甲厂"
        ws[f"B{i}"] = serial
        ws[f"C{i}"] = order
        ws[f"D{i}"] = f"M{i}"
    hidden = wb.create_sheet("报价隐表")
    hidden.sheet_state = "hidden"
    hidden["A1"] = "2026-01-01报价"
    hidden["A5"] = "2026-02-01报价"
    hidden["B2"] = "100"
    period = wb.create_sheet("期间块")
    period["A1"] = "某厂2026年01月01日-01月31日 购货明细"
    period["A10"] = "某厂2026年02月01日-02月28日 购货明细"
    period["B2"] = 1
    xref = wb.create_sheet("汇总")
    xref["A1"] = "=出货台账!C2"
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_index_schema_is_generic_and_includes_hidden():
    index = build_workbook_structural_index(_sample_workbook())
    assert index["schema_version"] == SCHEMA_VERSION
    assert index["stats"]["sheet_count"] == 4
    assert index["stats"]["hidden_sheet_count"] == 1
    names = {s["sheet"]: s for s in index["sheets"]}
    assert names["报价隐表"]["sheet_state"] == "hidden"
    assert names["报价隐表"]["block_title_rows"]
    assert names["期间块"]["candidate_row_ranges"]
    assert any(r["basis"] == "block_title" for r in names["期间块"]["candidate_row_ranges"])
    assert names["出货台账"]["ledger_run_hint_count"] >= 3
    assert any(r["basis"] == "ledger_key_run" for r in names["出货台账"]["candidate_row_ranges"])
    assert (
        sum(1 for r in names["出货台账"]["candidate_row_ranges"] if r["basis"] == "ledger_key_run")
        >= 3
    )
    assert index["cross_sheet_edges"]
    # Exclude content-addressing hash: hex digests may coincidentally contain
    # digit substrings we use as customer-hardcode sentinels (e.g. "165").
    content = {k: v for k, v in index.items() if k != "source_sha256"}
    blob = json.dumps(content, ensure_ascii=False)
    assert "澜宇" not in blob
    assert "165" not in blob


def test_compress_and_draft_attach():
    index = build_workbook_structural_index(_sample_workbook())
    compact = compress_structural_index_for_model(index, budget_bytes=8_000)
    assert compact["encoded_bytes"] <= 8_000
    draft = attach_structural_index_to_draft({}, index)
    assert draft["workbook_structural_index"]["schema_version"] == SCHEMA_VERSION
    assert draft["workbook_structural_index_full_sha256"] == index["source_sha256"]


def test_neutralize_keeps_structural_index_drops_structure_map():
    payload = {
        "sheets": [{"sheet": "表", "merged": []}],
        "cells": [{"sheet": "表", "cell": "A1", "value": "x", "kind": "review"}],
        "batch_coverage": [{"sheet": "表", "total_nonempty": 1}],
        "structure_map": [{"sheet": "表"}],
        "rule_hints": [],
        "relationship_context": {},
        "labels": ["a"],
        "workbook_structural_index": {"schema_version": SCHEMA_VERSION, "sheets": []},
    }
    messages = [
        {"role": "system", "content": ""},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    neutralize_messages(messages)
    kept = json.loads(messages[1]["content"])
    assert "workbook_structural_index" in kept
    assert kept["workbook_structural_index"]["schema_version"] == SCHEMA_VERSION
    assert "structure_map" not in kept
    assert "rule_hints" not in kept
    assert kept.get("labels") == ["a"]


def test_valid_model_regions_are_never_overridden_by_candidate_counts():
    """A model may correctly keep a continuous ledger despite multiple rule candidates."""
    review = {
        "sheet_overview": [
            {
                "sheet": "期间块",
                "sheet_state": "visible",
                "merged_regions": [],
                "rows": 30,
                "columns": 4,
            }
        ],
        "workbook_structural_index": {
            "schema_version": SCHEMA_VERSION,
            "source_sha256": "x",
            "sheets": [
                {
                    "sheet": "期间块",
                    "sheet_state": "visible",
                    "columns": 4,
                    "candidate_row_ranges": [
                        {"start_row": 1, "end_row": 9, "basis": "block_title"},
                        {"start_row": 10, "end_row": 20, "basis": "block_title"},
                        {"start_row": 21, "end_row": 30, "basis": "block_title"},
                    ],
                }
            ],
        },
        "sha256": "x",
    }
    # One valid model region remains one continuous document.
    under = {
        "model_status": "returned",
        "source_sha256": "x",
        "regions": [{"sheet": "期间块", "range": "A1:D30"}],
    }
    assert prefer_structural_classification_if_undersegmented(review, under) is under

    # equal counts → keep model
    equal = {
        "model_status": "returned",
        "source_sha256": "x",
        "regions": [
            {"sheet": "期间块", "range": "A1:D9"},
            {"sheet": "期间块", "range": "A10:D20"},
            {"sheet": "期间块", "range": "A21:D30"},
        ],
    }
    kept = prefer_structural_classification_if_undersegmented(review, equal)
    assert kept is equal

    # model has more → keep model
    over = {
        "model_status": "returned",
        "source_sha256": "x",
        "regions": [
            {"sheet": "期间块", "range": "A1:D5"},
            {"sheet": "期间块", "range": "A6:D9"},
            {"sheet": "期间块", "range": "A10:D20"},
            {"sheet": "期间块", "range": "A21:D30"},
        ],
    }
    kept2 = prefer_structural_classification_if_undersegmented(review, over)
    assert kept2 is over

    # missing classification → structural
    from_none = prefer_structural_classification_if_undersegmented(review, None)
    assert len(from_none["regions"]) == 3
    assert from_none["model_status"] == "fallback"
    assert from_none["needs_confirmation"] is True
    assert from_none["coverage_status"] == "unknown"
    for invalid in ("A0:D2", "A1:E30", "A1:D31", "A:D"):
        bad = {**under, "regions": [{"sheet": "期间块", "range": invalid}]}
        assert (
            prefer_structural_classification_if_undersegmented(review, bad)["model_status"]
            == "fallback"
        )
    stale = {**under, "source_sha256": "old"}
    assert (
        prefer_structural_classification_if_undersegmented(review, stale)["model_status"]
        == "fallback"
    )
    review["workbook_structural_index"]["sheets"][0]["candidate_row_ranges"][0]["end_row"] = 99
    with pytest.raises(ValueError, match="超出原件范围"):
        prefer_structural_classification_if_undersegmented(review, None)


def test_additional_return_note_absorbs_form_meta():
    """Mid-sheet 退货单 heading + following 购货单位 meta = one block_title atom.

    Keeps 退货单 as a real title word without inventing a phantom extra document
    relative to a sheet that already has a prior delivery-note form.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "客户表"
    ws["A1"] = "成都某公司送货单"
    ws["A2"] = "购货单位（乙方）：甲厂    联系人：张    日期：2026年01月01日   订单编号：26-1"
    ws["A10"] = "销售协议 | 1.甲方所供上列产品均属检验合格产品，送货单一式四联"
    ws["A12"] = "3.本送货单一式四联，白色联为存根联"
    ws["A20"] = "成都某公司退货单"
    ws["A21"] = "购货单位（乙方）：甲厂    联系人：张    日期：2025年08月01日   订单编号：25-1"
    ws["B22"] = "item"
    buf = BytesIO()
    wb.save(buf)
    index = build_workbook_structural_index(buf.getvalue())
    sheet = next(s for s in index["sheets"] if s["sheet"] == "客户表")
    title_cands = [c for c in sheet["candidate_row_ranges"] if c.get("basis") == "block_title"]
    starts = [c["start_row"] for c in title_cands]
    # First form keeps fine grain (送货单 + meta + agreement lines as separate cues).
    assert 1 in starts and 2 in starts
    # Second form: 退货单 present as heading, meta absorbed (no separate start at 21).
    assert 20 in starts
    assert 21 not in starts
    ret = next(c for c in title_cands if c["start_row"] == 20)
    assert ret["end_row"] >= 21


@pytest.mark.parametrize("count", [79, 80, 81, 1000])
def test_candidate_range_limit_retains_overflow_evidence_through_projection(count):
    ranges = [
        {
            "start_row": i * 3 + 1,
            "end_row": i * 3 + 2,
            "basis": "ledger_key_run",
            "run_hint_count": 2,
        }
        for i in range(count)
    ]
    capped = _cap_candidate_ranges(ranges, 80)
    assert len(capped) == min(count, 80)
    assert capped[: min(count, 79)] == ranges[: min(count, 79)]
    if count <= 80:
        assert capped == ranges
    else:
        assert capped[-1] == {
            "start_row": 238,
            "end_row": (count - 1) * 3 + 2,
            "basis": "candidate_ranges_remainder",
            "run_hint_count": 2 * (count - 79),
        }
    projected = compress_structural_index_for_model(
        {"sheets": [{"sheet": "S", "candidate_row_ranges": capped}]}
    )
    tail = projected["sheets"][0]["candidate_row_ranges"][-1]
    assert {key: tail[key] for key in capped[-1]} == capped[-1]


def test_sparse_index_keeps_remote_formula_without_materializing_gaps(monkeypatch):
    from app.application import reviewed_excel_structural_index as structural

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["日期", "单号"])
    sheet.append([45000, "one"])
    sheet["A1000000"] = 45001
    sheet["B1000000"] = "two"
    sheet["XFD1048576"] = "=Hidden!A1"
    hidden = workbook.create_sheet("Hidden")
    hidden.sheet_state = "veryHidden"
    hidden["A1"] = 0
    output = BytesIO()
    workbook.save(output)
    body = output.getvalue()
    original_load = load_workbook
    loaded = []

    def sparse_load(*args, **kwargs):
        result = original_load(*args, **kwargs)
        for item in result:
            before = len(item._cells)
            loaded.append((item, before))

            def forbidden(*args, **kwargs):
                pytest.fail("navigation must not materialize cells or scan a dense rectangle")

            monkeypatch.setattr(item, "cell", forbidden)
            monkeypatch.setattr(item, "iter_rows", forbidden)
        return result

    monkeypatch.setattr(structural, "load_workbook", sparse_load)
    index = build_workbook_structural_index(body)
    assert all(len(sheet._cells) == before for sheet, before in loaded)
    assert index["sheets"][0]["rows"] == 1048576
    assert index["sheets"][0]["columns"] == 16384
    assert index["sheets"][0]["ledger_run_hint_count"] == 2
    assert index["sheets"][0]["cross_sheet_formula_refs"][0]["from_cell"] == "XFD1048576"
    assert index["sheets"][1]["sheet_state"] == "veryHidden"


def test_model_budget_retains_every_sheet_and_counts_its_own_metadata():
    index = {
        "source_sha256": "a" * 64,
        "sheets": [
            {
                "sheet": f"工作表{i}",
                "sheet_state": "hidden" if i % 2 else "visible",
                "rows": 1000,
                "columns": 40,
                "block_title_rows": [{"row": j, "text": "标题" * 60} for j in range(40)],
                "candidate_row_ranges": [
                    {"start_row": j, "end_row": j + 1, "basis": "candidate"} for j in range(80)
                ],
            }
            for i in range(70)
        ],
    }
    before = deepcopy(index)
    summary = compress_structural_index_for_model(index)
    encoded = json.dumps(summary, ensure_ascii=False, separators=(",", ":")).encode()
    assert len(encoded) == summary["encoded_bytes"] <= 40000
    assert summary["truncated"] is True
    assert summary["is_full_facts"] is False
    assert summary["sheet_inventory_complete"] is True
    assert [sheet["sheet"] for sheet in summary["sheets"]] == [
        sheet["sheet"] for sheet in index["sheets"]
    ]
    assert summary["readback"]["expected_sha256"] == index["source_sha256"]
    assert index == before
    with pytest.raises(ValueError, match="完整工作表清单"):
        compress_structural_index_for_model(index, budget_bytes=100)


def test_changed_source_rebuilds_index_and_model_view():
    review = {}
    old = ensure_review_structural_index(review, _sample_workbook())
    workbook = Workbook()
    workbook.active.title = "New"
    workbook.active["A1"] = "changed"
    output = BytesIO()
    workbook.save(output)
    new = ensure_review_structural_index(review, output.getvalue())
    assert new["source_sha256"] != old["source_sha256"]
    assert review["workbook_structural_index_for_model"]["source_sha256"] == new["source_sha256"]
    assert [sheet["sheet"] for sheet in new["sheets"]] == ["New"]


def test_complete_sheet_inventory_keeps_unsupported_chart_sheets():
    from openpyxl.chart import BarChart, Reference

    workbook = Workbook()
    workbook.active["A1"] = 1
    chart = BarChart()
    chart.add_data(Reference(workbook.active, min_col=1, min_row=1))
    workbook.create_chartsheet("Chart").add_chart(chart)
    output = BytesIO()
    workbook.save(output)
    summary = compress_structural_index_for_model(
        build_workbook_structural_index(output.getvalue())
    )
    assert summary["sheet_inventory_complete"] is True
    assert [item["sheet"] for item in summary["sheets"]] == workbook.sheetnames
    assert summary["sheets"][1]["status"] == "unsupported"
