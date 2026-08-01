"""Bounded retention policy for self-maintenance runtime evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence


def retain_completed_merge_runs(
    eligible: Sequence[tuple[dict[str, Any], datetime]],
    *,
    latest_by_run: Mapping[str, datetime],
    recent_run_ids: set[str],
    cutoff: datetime,
    row_limit: int,
) -> list[dict[str, Any]]:
    """Preserve coherent completed runs before filling the recent-feed budget.

    A completed merge is durable work proof, not feed activity.  Frequent
    failed retries may consume the recent-run limit, but cannot evict a
    completed run while it remains inside the caller's time and row bounds.
    """

    completed_run_ids = {
        str(row.get("run_id") or "").strip()
        for row, _ in eligible
        if str(row.get("run_id") or "").strip()
        and str(row.get("status") or "").strip().lower() == "completed_merged"
        and row.get("ok") is not False
    }
    completed_run_ids.update(
        str(row.get("run_id") or "").strip()
        for row, _ in eligible
        if str(row.get("run_id") or "").strip()
        and str(row.get("event") or "").strip().lower() == "merge_completed"
        and row.get("ok") is True
    )
    rows_by_run: dict[str, list[dict[str, Any]]] = {}
    for row, _ in eligible:
        run_id = str(row.get("run_id") or "").strip()
        if run_id:
            rows_by_run.setdefault(run_id, []).append(row)

    reserved_run_ids: set[str] = set()
    reserved_row_count = 0
    for run_id in sorted(
        completed_run_ids,
        key=lambda value: latest_by_run.get(value, cutoff),
        reverse=True,
    ):
        run_row_count = len(rows_by_run.get(run_id, []))
        if run_row_count and reserved_row_count + run_row_count <= row_limit:
            reserved_run_ids.add(run_id)
            reserved_row_count += run_row_count

    reserved_row_object_ids = {
        id(row) for row, _ in eligible if str(row.get("run_id") or "").strip() in reserved_run_ids
    }
    recent_candidates = [
        row
        for row, _ in eligible
        if id(row) not in reserved_row_object_ids
        and (
            not str(row.get("run_id") or "").strip()
            or str(row.get("run_id") or "").strip() in recent_run_ids
        )
    ]
    remaining_budget = row_limit - reserved_row_count
    recent_row_object_ids = (
        {id(row) for row in recent_candidates[-remaining_budget:]} if remaining_budget else set()
    )
    return [
        row
        for row, _ in eligible
        if id(row) in reserved_row_object_ids or id(row) in recent_row_object_ids
    ]


__all__ = ["retain_completed_merge_runs"]
