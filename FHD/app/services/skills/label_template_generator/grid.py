"""Detect label grid geometry from a thresholded image without owning image or OCR services."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, SupportsInt

from .ports import Grid, Payload

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


def _longest_run(values: Iterable[SupportsInt]) -> int:
    longest = current = 0
    for value in values:
        if int(value) > 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _merge_lines(lines: list[int], threshold: int, *, average: bool = False) -> list[int]:
    if not lines:
        return []
    merged = [lines[0]]
    for line in lines[1:]:
        if line - merged[-1] > threshold:
            merged.append(line)
        elif average:
            merged[-1] = (merged[-1] + line) // 2
    return merged


def detect_grid(binary: NDArray[np.uint8]) -> Grid:
    height, width = binary.shape
    horizontal = [y for y in range(height) if _longest_run(binary[y, :]) > width * 0.5]
    vertical = [x for x in range(width) if _longest_run(binary[:, x]) > height * 0.5]
    horizontal = _merge_lines(_merge_lines(horizontal, 5, average=True), 50)
    vertical = _merge_lines(_merge_lines(vertical, 5, average=True), 50)
    cells: list[Payload] = []
    merged_cells: list[Payload] = []
    if len(horizontal) > 1 and len(vertical) > 1:
        rows, cols = len(horizontal) - 1, len(vertical) - 1
        for row in range(rows):
            for col in range(cols):
                x, y = vertical[col], horizontal[row]
                cell_width = vertical[col + 1] - x
                cell_height = horizontal[row + 1] - y
                cell = {
                    "row": row,
                    "col": col,
                    "x": x,
                    "y": y,
                    "width": cell_width,
                    "height": cell_height,
                    "should_merge_right": False,
                }
                if col < cols - 1:
                    border_x = x + cell_width
                    black = total = 0
                    for border_y in range(y, y + cell_height):
                        if border_y < height and border_x < width:
                            total += 1
                            if binary[border_y, border_x] > 0:
                                black += 1
                    if total > 0 and 0 < black < cell_height * 0.5:
                        cell["should_merge_right"] = True
                cells.append(cell)
        by_position = {(cell["row"], cell["col"]): cell for cell in cells}
        visited: set[tuple[int, int]] = set()
        for row in range(rows):
            for col in range(cols):
                if (row, col) in visited:
                    continue
                cell = by_position[(row, col)]
                count = 1
                while cell["should_merge_right"] and col + count < cols:
                    visited.add((row, col + count))
                    count += 1
                    if col + count < cols:
                        cell = by_position[(row, col + count)]
                    else:
                        break
                merged_cells.append(
                    {
                        "row": row,
                        "start_col": col,
                        "end_col": col + count - 1,
                        "merge_cols": count,
                        "x": vertical[col],
                        "y": horizontal[row],
                        "width": vertical[col + count] - vertical[col],
                        "height": horizontal[row + 1] - horizontal[row],
                        "original_cols": list(range(col, col + count)),
                    }
                )
                visited.add((row, col))
    merged = [
        {"row": cell["row"], "start_col": cell["start_col"], "end_col": cell["end_col"]}
        for cell in merged_cells
        if cell["start_col"] != cell["end_col"]
    ]
    return Grid(horizontal, vertical, merged_cells or cells, merged)
