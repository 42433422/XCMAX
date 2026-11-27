"""Finite native regions and offered structural candidates for sheet recognition.

Candidates retain source coordinates and are evidence for a model decision;
legacy table roles remain fallback interpretations.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from itertools import chain, groupby
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.application.elt.table_segmentation import Merge, SheetSegmentation


def _candidate(
    sheet: str, bounds: Merge, basis: str, source: str, headers: Iterable[int] = ()
) -> dict[str, Any]:
    from openpyxl.utils import get_column_letter

    r1, c1, r2, c2 = bounds
    ref = f"{get_column_letter(c1)}{r1}:{get_column_letter(c2)}{r2}"
    return {
        "candidate_id": f"{sheet}!{ref}:{basis}:{source}",
        "sheet": sheet,
        "range": ref,
        "basis": basis,
        "source": source,
        "header_rows": list(headers),
        "status": "candidate",
    }


def summarize_structure_candidates(candidates: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Keep bounded model navigation and the exact count of offered alternatives."""
    retained: list[dict[str, Any]] = []
    total = 0
    for item in candidates:
        total += 1
        if len(retained) < 80:
            retained.append(item)
    return {
        "structure_candidates": retained,
        "structure_candidate_total": total,
        "structure_candidates_truncated": total > len(retained),
    }


def worksheet_candidate_summary(worksheet: Any) -> dict[str, Any]:
    from app.infrastructure.excel.cell_visual_facts import worksheet_geometry_regions

    occupied = (
        position
        for position, cell in worksheet._cells.items()
        if cell.value is not None and str(cell.value).strip()
    )
    return {
        **summarize_structure_candidates(
            _candidate(worksheet.title, bounds, basis, name)
            for bounds, basis, name in chain(
                worksheet_native_regions(worksheet),
                worksheet_geometry_regions(worksheet),
                ((bounds, "occupied_region", "") for bounds in _occupied_regions(occupied)),
            )
        ),
        # Combined with the outer navigation's SHA-bound readback and sheet name.
        "structure_readback_range": worksheet.calculate_dimension(),
    }


def worksheet_native_regions(worksheet: Any) -> tuple[tuple[Merge, str, str], ...]:
    """Read explicit finite Table/name ranges; never evaluate a defined-name formula."""
    from openpyxl.formula.tokenizer import TokenizerError
    from openpyxl.utils.cell import range_boundaries

    result: set[tuple[Merge, str, str]] = set()

    def add(ref: str, basis: str, name: str) -> None:
        try:
            c1, r1, c2, r2 = range_boundaries(ref)
        except (ValueError, TypeError):
            return
        if r1 is None or c1 is None or r2 is None or c2 is None:
            return
        if 1 <= r1 <= r2 <= 1048576 and 1 <= c1 <= c2 <= 16384:
            result.add(((r1, c1, r2, c2), basis, name))

    for table in getattr(worksheet, "tables", {}).values():
        add(table.ref, "excel_table", table.name)
    for owner in (worksheet.parent, worksheet):
        for name in getattr(owner, "defined_names", {}).values():
            try:
                if not name.attr_text or name.type != "RANGE":
                    continue
                for sheet, ref in name.destinations:
                    if sheet == worksheet.title:
                        add(ref, "defined_name", name.name)
            except (ValueError, TypeError, IndexError, TokenizerError):
                # Dynamic/unparseable names are not finite region evidence.
                continue
    return tuple(sorted(result))


def iter_structure_candidates(segmentation: SheetSegmentation):
    """Enumerate alternative structural candidates, not approved business mappings.

    Native ranges, legacy Segmenter tables, and unresolved occupied runs coexist.
    The latter retain coordinates even when fallback roles exclude a row.
    """

    def candidate(bounds: Merge, basis: str, source: str, headers=()):
        return _candidate(segmentation.sheet, bounds, basis, source, headers)

    for bounds, basis, name in (*segmentation.native_regions, *segmentation.geometry_regions):
        yield candidate(bounds, basis, name)
    table_bounds = {}
    for table in segmentation.tables:
        bounds = (
            table.header_rows[0] if table.header_rows else table.leaf_row,
            table.min_col,
            max(table.end_row, table.leaf_row),
            table.max_col,
        )
        table_bounds[table.table_id] = bounds
        yield candidate(bounds, "segmenter_fallback", table.table_id, table.header_rows)

    # Sparse row runs for every position not reliably attributed to a table body/header.
    # Do not inflate a disconnected sparse sheet into one enormous rectangle.
    def unresolved():
        for row, col in segmentation.source_positions:
            role, table_id = segmentation.cells.get((row, col), ("unknown", ""))
            assigned_bounds = table_bounds.get(table_id)
            if role in {"data", "header", "parent_header", "repeated_header"} and assigned_bounds:
                r1, c1, r2, c2 = assigned_bounds
                if r1 <= row <= r2 and c1 <= col <= c2:
                    continue
            yield row, col

    for bounds in _occupied_regions(unresolved()):
        yield candidate(bounds, "unresolved_occupied", "")


def _occupied_regions(positions: Iterable[tuple[int, int]]) -> Iterator[Merge]:
    """Reuse sparse occupied-run coalescing for fallback and model navigation."""
    runs: list[Merge] = []
    for row, col in sorted(positions):
        if runs and runs[-1][0] == row and runs[-1][3] + 1 == col:
            r1, c1, r2, _ = runs[-1]
            runs[-1] = (r1, c1, r2, col)
        else:
            runs.append((row, col, row, col))
    # Combine identical column spans on consecutive rows, without creating blank-gap rows.
    active: dict[tuple[int, int], Merge] = {}
    for row, row_runs in groupby(runs, key=lambda rect: rect[0]):
        current: dict[tuple[int, int], Merge] = {}
        for r1, c1, r2, c2 in row_runs:
            key = (c1, c2)
            previous = active.pop(key, None)
            if previous is not None and previous[2] == row - 1:
                current[key] = (previous[0], c1, r2, c2)
            else:
                if previous is not None:
                    yield previous
                current[key] = (r1, c1, r2, c2)
        for bounds in active.values():
            yield bounds
        active = current
    for bounds in active.values():
        yield bounds


def validate_candidate_selection(
    offered: list[dict[str, Any]], selected_ids: list[str]
) -> list[dict[str, Any]]:
    """Validate only candidate IDs actually offered to a model; never accept new coordinates."""
    by_id = {item["candidate_id"]: item for item in offered}
    if (
        not isinstance(selected_ids, list)
        or len(by_id) != len(offered)
        or any(not isinstance(item, str) for item in selected_ids)
    ):
        raise ValueError("invalid structure candidate contract")
    if len(set(selected_ids)) != len(selected_ids) or any(
        item not in by_id for item in selected_ids
    ):
        raise ValueError("duplicate or unoffered structure candidate")
    return [by_id[item] for item in selected_ids]
