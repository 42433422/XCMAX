# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Status matching, write-back, and metrics for digest action items."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _action_items_module():
    # Lazy facade lookup preserves existing patch points and avoids a circular
    # import while digest_action_items re-exports this module's public API.
    from modstore_server import digest_action_items

    return digest_action_items


def normalize_match_text(text: str) -> str:
    action_items = _action_items_module()
    return action_items._normalize_action_text(text)[:400]


def text_matches(item_text: str, task_text: str) -> bool:
    first = normalize_match_text(item_text)
    second = normalize_match_text(task_text)
    if not first or not second:
        return False
    if first == second:
        return True
    shorter, longer = (first, second) if len(first) <= len(second) else (second, first)
    if len(shorter) >= 12 and shorter in longer:
        return True
    return len(shorter) >= 6 and shorter in longer and len(longer) - len(shorter) <= 80


def find_matching_item_ids(
    *,
    record_id: int,
    employee_id: str,
    kind: str,
    task_text: str,
    day: Optional[str] = None,
) -> List[int]:
    action_items = _action_items_module()
    items = action_items.list_action_items(kind=kind, record_id=int(record_id or 0), limit=500)
    if day:
        items = [item for item in items if str(item.get("day") or "") == day]
    employee = (employee_id or "").strip()
    matched_ids: List[int] = []
    for item in items:
        if employee and str(item.get("employee_id") or "").strip() != employee:
            continue
        if text_matches(str(item.get("text") or ""), task_text):
            matched_ids.append(int(item["id"]))
    if matched_ids or not employee:
        return matched_ids
    for item in items:
        if text_matches(str(item.get("text") or ""), task_text):
            item_id = int(item["id"])
            if item_id not in matched_ids:
                matched_ids.append(item_id)
    return matched_ids


def set_status_if_advanced(item_id: int, status: str) -> bool:
    action_items = _action_items_module()
    status = str(status or "").strip().lower()
    if status not in action_items.VALID_STATUS:
        return False
    from sqlalchemy import text as sql_text

    engine = action_items._engine()
    with engine.begin() as connection:
        row = connection.execute(
            sql_text("SELECT status FROM daily_action_items WHERE id=:id"),
            {"id": int(item_id)},
        ).first()
        if not row:
            return False
        current = str(row[0] or "open").strip().lower()
        if action_items._STATUS_RANK.get(status, 0) <= action_items._STATUS_RANK.get(current, 0):
            return False
        connection.execute(
            sql_text("UPDATE daily_action_items SET status=:s, updated_at=:u WHERE id=:id"),
            {"s": status, "u": action_items._now(), "id": int(item_id)},
        )
    return True


def set_status(item_id: int, status: str) -> Dict[str, Any]:
    action_items = _action_items_module()
    status = str(status or "").strip().lower()
    if status not in action_items.VALID_STATUS:
        return {
            "ok": False,
            "error": f"invalid status; allowed={action_items.VALID_STATUS}",
        }
    from sqlalchemy import text as sql_text

    engine = action_items._engine()
    with engine.begin() as connection:
        connection.execute(
            sql_text("UPDATE daily_action_items SET status=:s, updated_at=:u WHERE id=:id"),
            {"s": status, "u": action_items._now(), "id": int(item_id)},
        )
    return {"ok": True, "id": int(item_id), "status": status}


def sync_dispatched_for_work_units(record_id: int, units: Sequence[Any]) -> Dict[str, Any]:
    action_items = _action_items_module()
    updated = 0
    matched: List[int] = []
    for unit in units:
        list_kind = str(
            getattr(unit, "list_kind", None)
            or (unit.get("list_kind") if isinstance(unit, dict) else "")
            or ""
        )
        kind = action_items.KIND_PATCH if list_kind == "patches" else action_items.KIND_UPDATE
        employee_id = str(
            getattr(unit, "employee_id", None)
            or (unit.get("employee_id") if isinstance(unit, dict) else "")
            or ""
        )
        task_brief = str(
            getattr(unit, "task_brief", None)
            or (unit.get("task_brief") if isinstance(unit, dict) else "")
            or ""
        )
        if not task_brief:
            continue
        item_ids = action_items.find_matching_item_ids(
            record_id=int(record_id),
            employee_id=employee_id,
            kind=kind,
            task_text=task_brief,
        )
        for item_id in item_ids:
            if item_id in matched:
                continue
            if action_items.set_status_if_advanced(item_id, "dispatched"):
                updated += 1
                matched.append(item_id)
    logger.info("action_items dispatch writeback record=%s updated=%s", record_id, updated)
    return {"ok": True, "updated": updated, "matched_ids": matched}


def sync_merged_on_deploy(
    *, record_id: Optional[int] = None, day: Optional[str] = None
) -> Dict[str, Any]:
    action_items = _action_items_module()
    use_day = (day or "").strip() or action_items.latest_day()
    items = action_items.list_action_items(day=use_day or None, limit=2000)
    if record_id:
        items = [item for item in items if int(item.get("record_id") or 0) == int(record_id)]
    updated = 0
    merged_ids: List[int] = []
    for item in items:
        if str(item.get("status") or "open") not in ("dispatched", "in_progress"):
            continue
        item_id = int(item["id"])
        if action_items.set_status_if_advanced(item_id, "merged"):
            updated += 1
            merged_ids.append(item_id)
    logger.info("action_items merge writeback day=%s updated=%s", use_day, updated)
    return {"ok": True, "updated": updated, "merged_ids": merged_ids, "day": use_day}


def stats(*, kind: Optional[str] = None, day: Optional[str] = None) -> Dict[str, Any]:
    action_items = _action_items_module()
    try:
        action_items.ensure_table()
    except RECOVERABLE_ERRORS:
        return {
            "total": 0,
            "done": 0,
            "completion_rate": 0.0,
            "by_status": {},
            "by_line": {},
            "by_priority": {},
        }
    from sqlalchemy import text as sql_text

    where = []
    params: Dict[str, Any] = {}
    if kind:
        where.append("kind=:kind")
        params["kind"] = kind
    if day:
        where.append("day=:day")
        params["day"] = day
    sql = "SELECT status, line, priority, COUNT(*) AS n FROM daily_action_items"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " GROUP BY status, line, priority"
    total = 0
    by_status: Dict[str, int] = {}
    by_line: Dict[str, int] = {}
    by_priority: Dict[str, int] = {}
    engine = action_items._engine()
    with engine.begin() as connection:
        rows = connection.execute(sql_text(sql), params).mappings()
        for row in rows:
            count = int(row.get("n") or 0)
            total += count
            status = str(row.get("status") or "")
            line = str(row.get("line") or "")
            priority = str(row.get("priority") or "")
            by_status[status] = by_status.get(status, 0) + count
            by_line[line] = by_line.get(line, 0) + count
            if priority:
                by_priority[priority] = by_priority.get(priority, 0) + count
    done = by_status.get("merged", 0) + by_status.get("closed", 0)
    return {
        "total": total,
        "done": done,
        "completion_rate": round(done / total * 100, 1) if total else 0.0,
        "by_status": by_status,
        "by_line": by_line,
        "by_priority": by_priority,
    }
