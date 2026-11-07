"""Apply deterministic table segmentation to generic workbook parsing."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.application.elt.table_segmentation import (
    EXCLUDED_ROLES,
    SegmentedTable,
    SheetSegmentation,
    segment_sheet,
    worksheet_grid,
)

MAX_STRUCTURE_BYTES = 40 * 1024 * 1024


@dataclass(slots=True)
class RowPlan:
    """Per-row destination for one sheet: a primary table or an explicit exclusion."""

    segmentation: SheetSegmentation
    tables: list[SegmentedTable]
    tables_by_row: dict[int, list[SegmentedTable]] = field(default_factory=dict)
    excluded: dict[int, tuple[str, str]] = field(default_factory=dict)
    excluded_counts: Counter = field(default_factory=Counter)

    def exclude(self, row: int) -> tuple[str, str]:
        role, reason = self.excluded.get(row, ("other_table", "属于同表其他独立表格，不并入主表"))
        self.excluded_counts[role] += 1
        return role, reason

    def public(self) -> dict[str, Any]:
        return {
            "tables": [table.public() for table in self.tables],
            "other_tables": [
                table.public() for table in self.segmentation.tables if table not in self.tables
            ],
            "cell_coverage": self.segmentation.coverage(),
            "excluded_row_counts": dict(sorted(self.excluded_counts.items())),
        }


def load_sheet_segmentations(path: Path) -> dict[str, SheetSegmentation]:
    """Segment every sheet; skipped for very large files where a full load is too costly."""
    from openpyxl import load_workbook

    if path.stat().st_size > MAX_STRUCTURE_BYTES:
        return {}
    workbook = load_workbook(path, data_only=True, keep_links=False)
    try:
        return {
            ws.title: segment_sheet(ws.title, *worksheet_grid(ws)) for ws in workbook.worksheets
        }
    finally:
        workbook.close()


def _qualified_group(segmentation: SheetSegmentation | None) -> list[SegmentedTable]:
    group = segmentation.dominant_group() if segmentation is not None else []
    return group if group and len(group[0].headers) >= 3 else []


def structured_layout(
    segmentation: SheetSegmentation | None, layout: Any, header_hints: list[str]
) -> Any:
    """Replace a header guess that no segmented table uses with the dominant table header."""
    from app.application.elt.parser_structure import TableLayout, semantic_key

    group = _qualified_group(segmentation)
    if layout is None or not group:
        return layout
    header_row = layout.header_end + 1
    if any(header_row in table.header_rows for table in group):
        return layout
    group_rows = sum(len(table.data_rows) for table in group)
    all_rows = sum(len(table.data_rows) for table in segmentation.tables)
    if group_rows * 2 <= all_rows and any(
        header_row in table.header_rows for table in segmentation.tables
    ):
        return layout
    table = min(group, key=lambda item: item.leaf_row)
    hint_keys = {semantic_key(value) for value in header_hints if semantic_key(value)}
    headers = [f"未命名列{index}" for index in range(1, table.min_col)] + list(table.headers)
    return TableLayout(
        header_start=table.header_rows[0] - 1,
        header_end=table.leaf_row - 1,
        headers=headers,
        confidence=layout.confidence,
        matched_hint_count=sum(
            1 for path in table.header_paths if path and semantic_key(path[-1]) in hint_keys
        ),
        reasons=(*layout.reasons, "table_segmentation_header"),
    )


def plan_rows(segmentation: SheetSegmentation | None, header_row: int) -> RowPlan | None:
    """Use the dominant table group when its header is the one the layout detector found."""
    group = _qualified_group(segmentation)
    if not any(header_row in table.header_rows for table in group):
        return None
    plan = RowPlan(segmentation, group)
    for table in group:
        for row in table.data_rows:
            plan.tables_by_row.setdefault(row, []).append(table)
    for item in segmentation.row_roles:
        if item["role"] in EXCLUDED_ROLES and item["row"] not in plan.tables_by_row:
            plan.excluded.setdefault(item["row"], (item["role"], item["reason"]))
    return plan


def table_values(values: tuple, table: SegmentedTable, plan: RowPlan, width: int) -> tuple:
    """Shift a side-by-side sibling onto the detected header's column positions."""
    offset = table.min_col - min(t.min_col for t in plan.tables)
    return tuple(values[offset : offset + width])


__all__ = ["RowPlan", "load_sheet_segmentations", "plan_rows", "structured_layout", "table_values"]
