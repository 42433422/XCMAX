"""Pure transport budgets shared by planning and the exact archived request."""

import json
from collections import deque

from app.application.etl.errors import ReviewedExcelError

BUDGET_VERSION = "full-request-plan-v6-merge-closed"
MAX_REQUEST_BYTES = 96_000
MAX_OUTPUT_TOKENS = 16_000
MAX_CLASSIFICATION_BATCHES = 99  # Reserve one of the 100 audit slots for grouping.


class RequestBudgetExceeded(ReviewedExcelError):
    """A local preflight rejection, never a provider failure."""


def request_bytes(request: dict) -> int:
    # Include schema separately as well: provider envelopes may duplicate it.
    # UTF-8 bytes are a conservative transport bound, not a tokenizer estimate.
    return len(json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def output_budget(cells: list[dict]) -> int:
    primary = sum(not cell.get("context_only") for cell in cells)
    return min(MAX_OUTPUT_TOKENS, max(4000, 2000 + 40 * primary))


def validate_request_budget(request: dict) -> None:
    if request_bytes(request) > MAX_REQUEST_BYTES:
        raise RequestBudgetExceeded("完整模型请求超过安全预算，未调用模型")


def _closed_axis_groups(cells: list[dict], merges: list[tuple], axis: int) -> list[list[dict]]:
    """Group source coordinates between cuts that cannot bisect a merged rectangle."""
    from openpyxl.utils.cell import column_index_from_string, coordinate_from_string

    intervals: list[list[int]] = []
    for first, last in sorted((area[axis], area[axis + 2]) for area in merges):
        if intervals and first <= intervals[-1][1]:
            intervals[-1][1] = max(intervals[-1][1], last)
        else:
            intervals.append([first, last])
    grouped: dict[int, list[dict]] = {}
    for cell in cells:
        col, row = coordinate_from_string(cell["cell"])
        coordinate = row if axis else column_index_from_string(col)
        start = next(
            (first for first, last in intervals if first <= coordinate <= last), coordinate
        )
        grouped.setdefault(start, []).append(cell)
    return [grouped[start] for start in sorted(grouped)]


def _split_closed_band(cells: list[dict], merges: list[tuple], prepare) -> list[list[dict]]:
    """Only source-safe column cuts may split an over-budget merge-closed row band."""
    from openpyxl.utils.cell import coordinate_from_string

    first = min(coordinate_from_string(cell["cell"])[1] for cell in cells)
    last = max(coordinate_from_string(cell["cell"])[1] for cell in cells)
    # Include the complete connected row span, even where merged subordinate cells are blank.
    relevant = [area for area in merges if area[1] <= last and first <= area[3]]
    while relevant:
        bounds = (
            min(first, *(area[1] for area in relevant)),
            max(last, *(area[3] for area in relevant)),
        )
        if bounds == (first, last):
            break
        first, last = bounds
        relevant = [area for area in merges if area[1] <= last and first <= area[3]]
    groups = _closed_axis_groups(cells, relevant, 0)
    result = []
    offset = 0
    while offset < len(groups):
        low, high, best = 1, len(groups) - offset, 0
        while low <= high:
            amount = (low + high) // 2
            chosen = [cell for group in groups[offset : offset + amount] for cell in group]
            try:
                prepare(chosen)
            except RequestBudgetExceeded:
                high = amount - 1
            else:
                best, low = amount, amount + 1
        if not best:
            raise RequestBudgetExceeded("单行或合并闭包无安全二维分割且超过请求预算，未调用模型")
        chosen = [cell for group in groups[offset : offset + best] for cell in group]
        prepare(chosen)
        result.append(chosen)
        offset += best
    return result


def fit_transport_batches(review: dict, batches: list[list[dict]]) -> list[list[dict]]:
    """Pack merge-closed source bands; transport boundaries carry no business meaning."""
    from openpyxl.utils.cell import coordinate_from_string, range_boundaries

    from app.application.reviewed_excel_classification import _classify_semantic_batch
    from app.application.reviewed_excel_evidence import (
        MAX_MODEL_CELLS,
        MAX_MODEL_TEXT_BYTES,
        _model_cell_cost,
    )

    def prepare(batch: list[dict]) -> None:
        if len(batch) > MAX_MODEL_CELLS or sum(map(_model_cell_cost, batch)) > MAX_MODEL_TEXT_BYTES:
            raise RequestBudgetExceeded("本批证据超过安全预算，未调用模型")
        _classify_semantic_batch(
            {**review, "cells": batch, "full_cells": review["cells"]},
            prepare_only=True,
            reference_ids=True,
        )

    already_fits = False
    if len(batches) == 1:
        try:
            prepare(batches[0])
        except RequestBudgetExceeded:
            pass
        else:
            already_fits = True
    if already_fits:
        fitted = batches
    elif review.get("drawing_evidence"):
        # Keep verified drawing/merge boundaries; never bisect them.
        for batch in batches:
            prepare(batch)
        fitted = batches
    else:
        by_sheet: dict[str, dict[int, list[dict]]] = {}
        for batch in batches:
            for cell in batch:
                if not cell.get("context_only"):
                    row = coordinate_from_string(cell["cell"])[1]
                    by_sheet.setdefault(cell["sheet"], {}).setdefault(row, []).append(cell)
        queues = []
        count = 0
        for sheet in review["sheets"]:
            rows = by_sheet.get(sheet, {})
            source = [cell for row in sorted(rows) for cell in rows[row]]
            merges = [
                range_boundaries(area)
                for overview in review.get("sheet_overview", [])
                if overview["sheet"] == sheet
                for area in overview.get("merged_regions", [])
            ]
            groups = _closed_axis_groups(source, merges, 1)
            context = source[:5] + source[-5:]
            queue: deque[list[dict]] = deque()
            offset = 0
            while offset < len(groups):

                def candidate(amount: int) -> list[dict]:
                    chosen = [c for group in groups[offset : offset + amount] for c in group]
                    keys = {(c["sheet"], c["cell"]) for c in chosen}
                    for cell in context:
                        key = (cell["sheet"], cell["cell"])
                        if key not in keys:
                            chosen.append({**cell, "context_only": True})
                            keys.add(key)
                    return chosen

                low, high, best = 1, min(len(groups) - offset, MAX_MODEL_CELLS), 0
                while low <= high:
                    midpoint = (low + high) // 2
                    try:
                        prepare(candidate(midpoint))
                    except RequestBudgetExceeded:
                        high = midpoint - 1
                    else:
                        best, low = midpoint, midpoint + 1
                if not best:
                    # A source row cannot be split. Drop only optional context if it
                    # would otherwise exclude this independently valid primary row.
                    chosen = [c for c in candidate(1) if not c.get("context_only")]
                    try:
                        prepare(chosen)
                    except RequestBudgetExceeded:
                        pieces = _split_closed_band(chosen, merges, prepare)
                        queue.extend(pieces)
                        offset += 1
                        count += len(pieces)
                        if count > MAX_CLASSIFICATION_BATCHES:
                            raise RequestBudgetExceeded("完整分析计划超过99批审计预算，未调用模型")
                        continue
                    best = 1
                else:
                    chosen = candidate(best)
                # Authoritative final preflight even if a size discontinuity wastes capacity.
                prepare(chosen)
                queue.append(chosen)
                offset += best
                count += 1
                if count > MAX_CLASSIFICATION_BATCHES:
                    raise RequestBudgetExceeded("完整分析计划超过99批审计预算，未调用模型")
            if queue:
                queues.append(queue)
        fitted = []
        while any(queues):
            for queue in queues:
                if queue:
                    fitted.append(queue.popleft())
    if len(fitted) > MAX_CLASSIFICATION_BATCHES:
        raise RequestBudgetExceeded("完整分析计划超过99批审计预算，未调用模型")
    expected = {(c["sheet"], c["cell"]) for c in review["cells"] if not c.get("context_only")}
    actual = [
        (c["sheet"], c["cell"]) for batch in fitted for c in batch if not c.get("context_only")
    ]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise RequestBudgetExceeded("分析计划未完整覆盖源证据，未调用模型")
    return fitted


def validate_checkpoint_budget(checkpoint: dict | None) -> None:
    if checkpoint and checkpoint.get("budget_version") != BUDGET_VERSION:
        raise ReviewedExcelError(
            "模型预算版本已改变，请显式重新分类；原结果与审计保留，不会自动重跑"
        )


def validate_remaining_audit_budget(state: dict, checkpoint: dict, total: int) -> None:
    completed = len(checkpoint.get("results", []))
    # Even failures/not_sent remain in the immutable audit and consume slots.
    grouping = int(bool(checkpoint.get("auto_group")) and checkpoint.get("phase") != "complete")
    needed = max(0, total - completed) + grouping
    if len(state.get("model_audit", [])) + needed > 100:
        raise ReviewedExcelError("剩余完整分析超过100条审计预算，请新建分类；原审计保留")


def template_timeout_seconds() -> float:
    """Template-only finite timeout; row suggestion limits remain unchanged."""
    import math
    import os

    from app.application.reviewed_excel_audit import ModelRequestNotSent

    try:
        value = float(os.environ.get("FHD_TEMPLATE_LLM_TIMEOUT_SECONDS", "120"))
    except ValueError:
        raise ModelRequestNotSent("模板模型超时配置无效，未调用模型") from None
    if not math.isfinite(value) or not 1 <= value <= 180:
        raise ModelRequestNotSent("模板模型超时必须为1至180秒，未调用模型")
    return value
