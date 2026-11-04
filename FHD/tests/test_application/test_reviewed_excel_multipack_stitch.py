"""Unit tests for overlapped multi-pack stitch helpers (no network)."""

from app.application.reviewed_excel_evidence import MAX_MODEL_CELLS
from app.application.reviewed_excel_multipack_stitch import (
    build_overlapped_sheet_packs,
    packs_without_cells,
    programmatic_merge_inventories,
)


def _cell(sheet: str, coord: str, value: str) -> dict:
    return {
        "sheet": sheet,
        "cell": coord,
        "value": value,
        "kind": "value",
        "number_format": "General",
        "context_only": False,
    }


def test_overlap_anchors_on_long_sheet():
    # 2500 fake cells on one sheet → must split with overlap metadata
    cells = []
    for row in range(1, 501):
        for col in range(1, 6):
            from openpyxl.utils.cell import get_column_letter

            cells.append(_cell("S", f"{get_column_letter(col)}{row}", f"r{row}c{col}"))
    review = {
        "sheets": ["S"],
        "cells": cells,
        "sheet_overview": [{"sheet": "S", "sheet_state": "visible"}],
    }
    packs = build_overlapped_sheet_packs(review, overlap_rows=8)
    assert len(packs) >= 2
    assert all(p["cell_count"] <= MAX_MODEL_CELLS for p in packs)
    # second pack should declare overlap with previous
    assert packs[1]["overlap_with_previous"] is not None
    assert packs[1]["overlap_with_previous"]["continues_sheet"] == "S"
    assert packs[1]["header_fingerprint"]
    meta = packs_without_cells(packs)
    assert "cells" not in meta[0]


def test_programmatic_merge_dedupes_order_key():
    a = {
        "documents": [
            {"sheet": "A", "order_key": "k1", "range": "A1:B2"},
            {"sheet": "A", "order_key": "k2", "range": "A3:B4"},
        ]
    }
    b = {
        "documents": [
            {"sheet": "A", "order_key": "k1", "range": "A1:B2"},  # dup
            {"sheet": "B", "order_key": "x", "range": "A1:A1"},
        ]
    }
    merged = programmatic_merge_inventories([a, b])
    assert merged["total"] == 3
    assert merged["by_sheet_counts"]["A"] == 2
