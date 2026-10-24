"""Discover employee blocks, calendar columns and summary locations."""

from __future__ import annotations

import unicodedata

from .template_cells import _plain_cell_text
from .template_schema import (
    _ATT_MARK,
    DETAIL_HEADER_ROWS,
    DETAIL_MAX_COL,
    DETAIL_PERSON_BLOCK_ROWS,
    DETAIL_TEMPLATE_SUMMARY_BEGIN_COL,
)


def find_template_base_rows(ws) -> dict[str, int]:
    """每人块仅认第 1 行（块首）C 列姓名，与 ``rebuild_detail_sheet_person_blocks`` 的 6 行步进一致。"""
    mapping: dict[str, int] = {}
    for row in iter_detail_sheet_block_base_rows(ws):
        name = ws.cell(row, 3).value
        if name not in (None, ""):
            key = str(name).strip()
            if key:
                mapping[key] = row
    return mapping


def find_template_side_summary_rows(ws, header_rows: int = DETAIL_HEADER_ROWS) -> dict[str, int]:
    """Map each identity to its consecutive side-summary row."""
    block_rows = iter_detail_sheet_block_base_rows(ws, header_rows)
    if not block_rows:
        return {}
    first_body = header_rows + 1
    mapping: dict[str, int] = {}
    for pidx, base_row in enumerate(block_rows, start=1):
        name = ws.cell(base_row, 3).value
        if name in (None, ""):
            continue
        key = str(name).strip()
        if key:
            mapping[key] = first_body + pidx - 1
    return mapping


def _unmerge_cell_rectangle(ws, r1: int, r2: int, c1: int, c2: int) -> None:
    """解除与矩形 [r1..r2]×[c1..c2] 相交的合并，便于清空侧栏单元格。"""
    for rng in list(ws.merged_cells.ranges):
        min_col, min_row, max_col, max_row = rng.bounds
        if max_row < r1 or min_row > r2 or max_col < c1 or (min_col > c2):
            continue
        ws.unmerge_cells(str(rng))


def iter_detail_sheet_block_base_rows(ws, header_rows: int = DETAIL_HEADER_ROWS) -> list[int]:
    """按「每人 6 行」几何位置枚举明细块首行（自上而下）。"""
    first_body = header_rows + 1
    rows: list[int] = []
    row = first_body
    while row + DETAIL_PERSON_BLOCK_ROWS - 1 <= ws.max_row:
        rows.append(row)
        row += DETAIL_PERSON_BLOCK_ROWS
    return rows


def set_template_month(ws, month_label: str) -> None:
    if not month_label:
        return
    year_str, month_str = month_label.split("-", 1)
    ws["M1"] = int(year_str)
    ws["S1"] = int(month_str)


def _detail_calendar_anchor_col(ws, header_rows: int = DETAIL_HEADER_ROWS) -> int | None:
    """表头行中「1 日」所在列（上午格），作为日×2 槽起点；与 ``DETAIL_TEMPLATE_SUMMARY_BEGIN_COL`` 之前扫描。"""
    row = header_rows
    hi = min(DETAIL_TEMPLATE_SUMMARY_BEGIN_COL - 1, DETAIL_MAX_COL)
    for c in range(5, hi + 1):
        v = ws.cell(row, c).value
        if v in (1, "1", "１"):
            return c
        if isinstance(v, str) and unicodedata.normalize("NFKC", v).strip() in {"1", "１"}:
            return c
    return None


def _first_attendance_symbol_col(ws, sample_row: int) -> int:
    """日×2 考勤写入起始列：优先用表头「1 日」列，避免首格为空时误把第 2 日当作起点（会侵占 BP 侧栏）。"""
    anchor = _detail_calendar_anchor_col(ws, DETAIL_HEADER_ROWS)
    if anchor is not None:
        return int(anchor)
    for c in range(5, DETAIL_MAX_COL + 1):
        v = ws.cell(sample_row, c).value
        text = _plain_cell_text(v).strip()
        if not text:
            continue
        text = unicodedata.normalize("NFKC", text).strip()
        if text in _ATT_MARK:
            return c
    return 5
