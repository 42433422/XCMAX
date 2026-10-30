"""Pure transport budgets shared by planning and the exact archived request."""

import json
from collections import deque

from app.application.etl.errors import ReviewedExcelError

BUDGET_VERSION = "full-request-plan-v3-source-coordinates"
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


def fit_transport_batches(review: dict, batches: list[list[dict]]) -> list[list[dict]]:
    """Repack neutral source rows; old cell-only chunk boundaries carry no meaning."""
    from openpyxl.utils.cell import coordinate_from_string

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
            groups = [rows[row] for row in sorted(rows)]
            source = [cell for group in groups for cell in group]
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
                        raise RequestBudgetExceeded(
                            "单行完整模型请求超过安全预算，未调用模型"
                        ) from None
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
