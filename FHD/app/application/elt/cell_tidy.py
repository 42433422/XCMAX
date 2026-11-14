"""Cell-level workbook reading and header beheading.

Two published algorithms are ported here instead of adding an R runtime:

* ``read_tidy_sheet`` mirrors tidyxl's ``xlsx_cells``: every populated cell
  becomes a record carrying its data type, formula text, merged span and the
  formatting flags (bold/filled/bordered) that separate header cells from data
  cells.
* ``behead_paths`` mirrors unpivotr's ``behead()``: one header layer is peeled
  off a rectangular block, merged spans are already expanded, and every column
  receives the header path accumulated from the layers above it.

Only the recognition layer consumes these helpers; business values keep flowing
through ``ParsedDataset`` unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.application.elt.parser_structure import clean_cell_text

MAX_TIDY_BYTES = 40 * 1024 * 1024
MAX_PROBE_ROWS = 60
MAX_PROBE_COLS = 200
_MERGE_EXPAND_LIMIT = 20_000
_DATA_TYPES = {
    "n": "numeric",
    "d": "date",
    "s": "character",
    "b": "logical",
    "e": "error",
    "f": "formula",
    "inlineStr": "character",
}


@dataclass(frozen=True, slots=True)
class TidyCell:
    row: int
    col: int
    value: Any
    data_type: str
    formula: str = ""
    bold: bool = False
    filled: bool = False
    bordered: bool = False
    merge: tuple[int, int, int, int] | None = None

    @property
    def is_blank(self) -> bool:
        return self.value in (None, "")

    @property
    def is_header_like(self) -> bool:
        return bool(self.bold or self.filled or self.bordered)


@dataclass(slots=True)
class TidySheet:
    name: str
    cells: dict[tuple[int, int], TidyCell]
    merges: list[tuple[int, int, int, int]]

    def value(self, row: int, col: int) -> Any:
        cell = self.cells.get((row, col))
        return cell.value if cell is not None else None

    def probe_rows(self, max_row: int = MAX_PROBE_ROWS) -> list[list[Any]]:
        """Merge-expanded probe rows, 1-based and index-aligned with the sheet."""
        if not self.cells:
            return []
        last_row = min(max((row for row, _col in self.cells), default=0), max_row)
        last_col = min(
            max((col for row, col in self.cells if row <= last_row), default=0),
            MAX_PROBE_COLS,
        )
        matrix: list[list[Any]] = [[None for _col in range(last_col)] for _row in range(last_row)]
        for (row, col), cell in self.cells.items():
            if row <= last_row and col <= last_col:
                matrix[row - 1][col - 1] = cell.value
        for merge in self.merges:
            _expand_merge(matrix, merge)
        return [[value if value is not None else "" for value in row] for row in matrix]

    def style_ratios(self, max_row: int | None = None) -> list[float]:
        """Share of populated cells per row that carry header formatting."""
        limit = max_row if max_row is not None else MAX_PROBE_ROWS
        counts: dict[int, list[int]] = {}
        for (row, _col), cell in self.cells.items():
            if row > limit:
                continue
            bucket = counts.setdefault(row, [0, 0])
            bucket[0] += 1
            bucket[1] += int(cell.is_header_like)
        return [
            (counts[row][1] / counts[row][0]) if row in counts else 0.0
            for row in range(1, limit + 1)
        ]


def _expand_merge(matrix: list[list[Any]], merge: tuple[int, int, int, int]) -> None:
    min_row, min_col, max_row, max_col = merge
    if (max_row - min_row + 1) * (max_col - min_col + 1) > _MERGE_EXPAND_LIMIT:
        return
    anchor = None
    if 0 < min_row <= len(matrix) and 0 < min_col <= len(matrix[min_row - 1]):
        anchor = matrix[min_row - 1][min_col - 1]
    if anchor is None:
        return
    for row in range(min_row, min(len(matrix), max_row) + 1):
        line = matrix[row - 1]
        for col in range(min_col, min(len(line), max_col) + 1):
            line[col - 1] = anchor


def read_tidy_sheet(worksheet: Any) -> TidySheet:
    """Mirror tidyxl's cell table for one openpyxl worksheet."""
    merges = [
        (item.min_row, item.min_col, item.max_row, item.max_col)
        for item in getattr(getattr(worksheet, "merged_cells", None), "ranges", ())
    ]
    anchors = {(merge[0], merge[1]): merge for merge in merges}
    cells: dict[tuple[int, int], TidyCell] = {}
    for row in worksheet.iter_rows():
        for cell in row:
            value = cell.value
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            data_type = _DATA_TYPES.get(str(getattr(cell, "data_type", "")), "character")
            cells[(cell.row, cell.column)] = TidyCell(
                row=cell.row,
                col=cell.column,
                value=value,
                data_type=data_type,
                formula=str(value) if data_type == "formula" else "",
                bold=bool(getattr(getattr(cell, "font", None), "bold", False)),
                filled=_is_filled(cell),
                bordered=_is_bordered(cell),
                merge=anchors.get((cell.row, cell.column)),
            )
    return TidySheet(name=str(worksheet.title), cells=cells, merges=merges)


def _is_filled(cell: Any) -> bool:
    fill = getattr(cell, "fill", None)
    fill_type = getattr(fill, "fill_type", None)
    return bool(fill_type and str(fill_type).lower() != "none")


def _is_bordered(cell: Any) -> bool:
    border = getattr(cell, "border", None)
    for side in ("left", "right", "top", "bottom"):
        edge = getattr(border, side, None)
        if edge is not None and getattr(edge, "style", None):
            return True
    return False


def read_tidy_workbook(path: Any, *, max_bytes: int = MAX_TIDY_BYTES) -> dict[str, TidySheet]:
    """Read every sheet at cell level; skipped for very large files."""
    from pathlib import Path

    from openpyxl import load_workbook

    source = Path(path)
    if source.stat().st_size > max_bytes:
        return {}
    workbook = load_workbook(source, data_only=True, keep_links=False)
    try:
        return {worksheet.title: read_tidy_sheet(worksheet) for worksheet in workbook.worksheets}
    finally:
        workbook.close()


def _forward_fill(values: list[Any], width: int) -> list[str]:
    result: list[str] = []
    current = ""
    for index in range(width):
        text = clean_cell_text(values[index] if index < len(values) else "")
        if text:
            current = text
        result.append(current)
    return result


def behead_paths(
    rows: list[list[Any]],
    *,
    width: int | None = None,
    direction: str = "up",
    fill_parents: bool = True,
    layers: int | None = None,
) -> list[list[str]]:
    """Port of unpivotr's ``behead()`` for one rectangular header block.

    ``direction="up"`` peels header layers from the top and returns one path per
    column.  ``direction="left"`` returns one path per row from its leading
    header columns (row-header tables), stripping ``layers`` cells at most.
    """
    if direction == "left":
        limit = layers if layers is not None else 1
        paths: list[list[str]] = []
        for row in rows:
            labels = [label for value in row if (label := clean_cell_text(value))]
            paths.append(labels[:limit])
        return paths
    if not rows:
        return []
    resolved_width = width if width is not None else max(len(row) for row in rows)
    column_paths: list[list[str]] = [[] for _ in range(resolved_width)]
    for index, row in enumerate(rows):
        padded = [row[col] if col < len(row) else "" for col in range(resolved_width)]
        layer = (
            _forward_fill(padded, resolved_width)
            if fill_parents and index < len(rows) - 1
            else [clean_cell_text(value) for value in padded]
        )
        for col in range(resolved_width):
            label = layer[col]
            if label and (not column_paths[col] or column_paths[col][-1] != label):
                column_paths[col].append(label)
    return column_paths


__all__ = [
    "MAX_TIDY_BYTES",
    "TidyCell",
    "TidySheet",
    "behead_paths",
    "read_tidy_sheet",
    "read_tidy_workbook",
]
