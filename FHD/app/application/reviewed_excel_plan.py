"""Bounded, value-free checkpoint plans; continuations do not replan source data."""

import hashlib
import json
from typing import NoReturn

from app.application.etl.errors import ReviewedExcelError
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
