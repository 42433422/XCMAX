"""Bounded, value-free checkpoint plans; continuations do not replan source data."""

import hashlib
import json
from typing import NoReturn

from app.application.elt.errors import ReviewedExcelError
from app.application.reviewed_excel_budget import BUDGET_VERSION, MAX_CLASSIFICATION_BATCHES
from app.application.reviewed_excel_evidence import MAX_MODEL_CELLS

MAX_PLAN_BYTES = 3_000_000


def _digest(checkpoint: dict) -> str:
    bound = {
        key: checkpoint[key]
        for key in ("source_sha256", "version", "budget_version", "max_calls", "coordinate_plan")
    }
    return hashlib.sha256(
        json.dumps(bound, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def store_coordinate_plan(checkpoint: dict, batches: list[list[dict]]) -> None:
    checkpoint["coordinate_plan"] = [
        [[cell["sheet"], cell["cell"], bool(cell.get("context_only"))] for cell in batch]
        for batch in batches
    ]
    if len(json.dumps(checkpoint["coordinate_plan"], ensure_ascii=False).encode()) > MAX_PLAN_BYTES:
        raise ReviewedExcelError("分类坐标计划超过安全预算，未调用模型")
    checkpoint["plan_digest"] = _digest(checkpoint)


def split_plan_step(checkpoint: dict, step: int, review: dict) -> bool:
    """Replace a truncated unit by two row-halves that no merge or drawing spans.

    False when the unit is a single closed row band or the plan has no room; the
    caller then fails closed instead of resending the same prompt.
    """
    from openpyxl.utils.cell import coordinate_from_string, range_boundaries

    plan = checkpoint.get("coordinate_plan")
    if not isinstance(plan, list) or not 0 <= step < len(plan):
        return False
    if len(plan) >= MAX_CLASSIFICATION_BATCHES:
        return False
    spans: dict[str, list[tuple[int, int]]] = {}
    for overview in review.get("sheet_overview", []):
        for area in overview.get("merged_regions", []):
            _c1, r1, _c2, r2 = range_boundaries(area)
            if r1 is None or r2 is None:
                continue
            spans.setdefault(overview["sheet"], []).append((r1, r2))
    for drawing in review.get("drawing_evidence", []):
        last = drawing.get("last_row") or (
            int(drawing["to"]["row"]) + 1 if drawing.get("to") is not None else None
        )
        if drawing.get("geometry_error") or not last:
            return False
        spans.setdefault(drawing["sheet"], []).append((drawing["from"]["row"] + 1, int(last)))

    closed: dict[str, list[list[int]]] = {}
    for sheet, intervals in spans.items():
        for first, last in sorted(intervals):
            merged = closed.setdefault(sheet, [])
            if merged and first <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], last)
            else:
                merged.append([first, last])

    def band(item) -> tuple[str, int]:
        row = coordinate_from_string(item[1])[1]
        start = next((a for a, b in closed.get(item[0], []) if a <= row <= b), row)
        return item[0], start

    primary = [item for item in plan[step] if not item[2]]
    context = [item for item in plan[step] if item[2]]
    groups: dict[tuple[str, int], list] = {}
    for item in primary:
        groups.setdefault(band(item), []).append(item)
    ordered = [groups[key] for key in sorted(groups)]
    if len(ordered) < 2:
        return False
    total, running, cut = len(primary), 0, 0
    for index, group in enumerate(ordered):
        running += len(group)
        if running * 2 >= total:
            cut = index + 1
            break
    cut = min(max(cut, 1), len(ordered) - 1)
    halves = [
        [item for group in ordered[:cut] for item in group],
        [item for group in ordered[cut:] for item in group],
    ]
    plan[step : step + 1] = [half + [list(item) for item in context] for half in halves]
    checkpoint["total"] = len(plan)
    checkpoint["plan_digest"] = _digest(checkpoint)
    return True


def restore_coordinate_plan(review: dict, checkpoint: dict) -> list[list[dict]]:
    def invalid() -> NoReturn:
        raise ReviewedExcelError("分类坐标计划缺失或已改变，请显式重新分类；原审计保留")

    plan = checkpoint.get("coordinate_plan")
    if (
        checkpoint.get("budget_version") != BUDGET_VERSION
        or checkpoint.get("source_sha256") != review["sha256"]
        or not isinstance(checkpoint.get("version"), str)
        or not checkpoint["version"]
        or type(checkpoint.get("max_calls")) is not int
        or not 1 <= checkpoint["max_calls"] <= 4
        or not isinstance(plan, list)
        or not 1 <= len(plan) <= MAX_CLASSIFICATION_BATCHES
        or checkpoint.get("total") != len(plan)
    ):
        invalid()
    if len(json.dumps(plan, ensure_ascii=False).encode()) > MAX_PLAN_BYTES:
        invalid()
    if checkpoint.get("plan_digest") != _digest(checkpoint):
        invalid()
    source = {(c["sheet"], c["cell"]): c for c in review["cells"]}
    if len(source) != len(review["cells"]):
        invalid()
    if review.get("drawing_evidence"):
        from app.application.reviewed_excel_drawing import plan_drawing_batches

        # Reattach source-derived geometry only, without any LLM request preparation.
        source = {
            (c["sheet"], c["cell"]): c for batch in plan_drawing_batches(review) for c in batch
        }
    result: list[list[dict]] = []
    primary: set[tuple[str, str]] = set()
    for batch in plan:
        if not isinstance(batch, list) or not 1 <= len(batch) <= MAX_MODEL_CELLS:
            invalid()
        rebuilt = []
        seen: set[tuple[str, str]] = set()
        for item in batch:
            if (
                not isinstance(item, list)
                or len(item) != 3
                or not isinstance(item[0], str)
                or not isinstance(item[1], str)
                or type(item[2]) is not bool
            ):
                invalid()
            key = (item[0], item[1])
            if key not in source or key in seen or (not item[2] and key in primary):
                invalid()
            seen.add(key)
            if not item[2]:
                primary.add(key)
            rebuilt.append({**source[key], "context_only": item[2]})
        if all(cell["context_only"] for cell in rebuilt):
            invalid()
        result.append(rebuilt)
    if primary != set(source):
        invalid()
    return result


def restore_checkpoint_review(review: dict, checkpoint: dict) -> tuple[dict, list[list[dict]]]:
    """Recreate the exact source scope used by a checkpoint, including hidden-sheet skips."""
    from app.application.reviewed_excel_evidence import prepare_auto_slice_review

    if checkpoint.get("skip_hidden_sheets") is True:
        scoped = prepare_auto_slice_review(review, skip_hidden_sheets=True)
        return scoped, restore_coordinate_plan(scoped, checkpoint)
    try:
        return review, restore_coordinate_plan(review, checkpoint)
    except ReviewedExcelError as original_error:
        scoped = prepare_auto_slice_review(review, skip_hidden_sheets=True)
        if scoped is review:
            raise
        try:
            batches = restore_coordinate_plan(scoped, checkpoint)
        except ReviewedExcelError:
            raise original_error
        # Older checkpoints created after hidden-sheet filtering did not persist
        # the scope marker. The saved coordinate plan proves the filtered scope.
        checkpoint["skip_hidden_sheets"] = True
        return scoped, batches


def restore_completed_review(review: dict, scope: dict | None) -> dict:
    """Restore server-saved completed scope without guessing for legacy versions."""
    from app.application.reviewed_excel_evidence import prepare_auto_slice_review

    if scope is None:
        return review
    if (
        not isinstance(scope, dict)
        or set(scope) != {"source_sha256", "skip_hidden_sheets", "sheets"}
        or scope.get("source_sha256") != review["sha256"]
        or type(scope.get("skip_hidden_sheets")) is not bool
    ):
        raise ReviewedExcelError("分类来源范围已改变，请重新分类")
    scoped = prepare_auto_slice_review(review, skip_hidden_sheets=scope["skip_hidden_sheets"])
    if scope.get("sheets") != scoped["sheets"]:
        raise ReviewedExcelError("分类来源范围已改变，请重新分类")
    return scoped
