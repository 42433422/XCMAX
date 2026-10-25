"""Identity-scoped remediation closure and bounded memory retention."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from modstore_server.operational_errors import RECOVERABLE_ERRORS

from . import config, store


def _memory_context(memory: Dict[str, Any]) -> str:
    recent_runs = memory.get("recent_runs") if isinstance(memory, dict) else []
    open_items = memory.get("open_items") if isinstance(memory, dict) else []
    closed_items = memory.get("closed_items") if isinstance(memory, dict) else []
    last_decision = (
        memory.get("last_policy_decision") if isinstance(memory, dict) else None
    )
    payload = {
        "closed_items": closed_items[-8:] if isinstance(closed_items, list) else [],
        "last_policy_decision": last_decision,
        "open_items": open_items[-8:] if isinstance(open_items, list) else [],
        "recent_runs": recent_runs[-5:] if isinstance(recent_runs, list) else [],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)[:6000]


def _coerce_str_set(values: Optional[List[str]]) -> set:
    return {str(value).strip() for value in values or [] if str(value).strip()}


def _open_item_steps(item: Dict[str, Any]) -> List[str]:
    steps = item.get("steps")
    if not isinstance(steps, list):
        return []
    return [str(step) for step in steps if str(step)]


def _failed_open_item_identity(item: Dict[str, Any]) -> str:
    """Stable identity for max-retry open items; run_id alone is not unique enough."""
    return "|".join(
        [
            str(item.get("kind") or ""),
            str(item.get("run_id") or ""),
            str(item.get("branch") or ""),
            str(item.get("para_task_id") or item.get("task_id") or ""),
            ",".join(_open_item_steps(item)),
            str(item.get("created_at") or ""),
        ]
    )


def _open_item_matches_resolution(
    item: Dict[str, Any],
    *,
    branches: set,
    reasons: set,
    run_ids: set,
    task_ids: set,
) -> bool:
    if run_ids and str(item.get("run_id") or "") in run_ids:
        return True
    if branches and str(item.get("branch") or "") in branches:
        return True
    if reasons and str(item.get("reason") or "") in reasons:
        return True
    if task_ids:
        item_task_ids = {
            str(item.get("task_id") or ""),
            str(item.get("para_task_id") or ""),
        }
        if task_ids & {value for value in item_task_ids if value}:
            return True
    return False


def _close_open_items_in_memory(
    memory: Dict[str, Any],
    *,
    actor: str,
    branches: Optional[List[str]] = None,
    reasons: Optional[List[str]] = None,
    resolution_reason: str,
    run_ids: Optional[List[str]] = None,
    task_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    open_items = memory.get("open_items")
    if not isinstance(open_items, list):
        open_items = []
    closed_items = memory.get("closed_items")
    if not isinstance(closed_items, list):
        closed_items = []
    branch_set = _coerce_str_set(branches)
    reason_set = _coerce_str_set(reasons)
    run_id_set = _coerce_str_set(run_ids)
    task_id_set = _coerce_str_set(task_ids)
    kept: List[Dict[str, Any]] = []
    closed: List[Dict[str, Any]] = []
    closed_at = config._iso(config._utc_now())
    for item in open_items:
        if not isinstance(item, dict):
            continue
        if _open_item_matches_resolution(
            item,
            branches=branch_set,
            reasons=reason_set,
            run_ids=run_id_set,
            task_ids=task_id_set,
        ):
            closed.append(
                {
                    "actor": actor,
                    "closed_at": closed_at,
                    "original_item": item,
                    "resolution_reason": resolution_reason,
                }
            )
        else:
            kept.append(item)
    memory["open_items"] = kept[-50:]
    memory["closed_items"] = (closed_items + closed)[-200:]
    memory["updated_at"] = closed_at
    return {"closed_count": len(closed), "closed_items": closed}


def close_loop_memory_items(
    *,
    actor: str = "self_maintenance",
    branches: Optional[List[str]] = None,
    reasons: Optional[List[str]] = None,
    resolution_reason: str,
    run_ids: Optional[List[str]] = None,
    task_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Close resolved loop-memory risks without deleting audit history."""
    memory = store._load_loop_memory()
    result = _close_open_items_in_memory(
        memory,
        actor=actor,
        branches=branches,
        reasons=reasons,
        resolution_reason=resolution_reason,
        run_ids=run_ids,
        task_ids=task_ids,
    )
    store._write_loop_memory(memory)
    return {
        **result,
        "memory_path": str(store.loop_memory_path()),
        "open_items_remaining": len(memory.get("open_items") or []),
    }


def _evict_loop_memory_items(
    memory: Dict[str, Any],
    *,
    actor: str = "auto",
    note: str = "",
    admin_user_id: Optional[Any] = None,
) -> Dict[str, Any]:
    """Evict stale open_items so the loop can resume fresh runs.

    Rules (checked in order, first match wins):
      - any item with created_at > 7d  → evict (reason=aged_out_7d)
      - failed_steps item with created_at > 24h AND retry_count >= 3
        → evict (reason=stuck_24h_retry_3)
    Evicted items are appended to memory["evicted_items"] (capped at the last
    LOOP_EVICT_MAX_ITEMS entries) and a ``loop_evicted`` governance audit
    record is written so the action is visible in the governance UI.
    Returns a summary dict; never raises.
    """
    open_items = memory.get("open_items")
    if not isinstance(open_items, list):
        open_items = []
    evicted_items = memory.get("evicted_items")
    if not isinstance(evicted_items, list):
        evicted_items = []
    now = config._utc_now()
    kept: List[Dict[str, Any]] = []
    newly_evicted: List[Dict[str, Any]] = []
    for item in open_items:
        if not isinstance(item, dict):
            continue
        created_dt = config._parse_iso(item.get("created_at"))
        age_seconds = (now - created_dt).total_seconds() if created_dt else 0.0
        retry_count = int(item.get("retry_count") or 0)
        kind = str(item.get("kind") or "")
        evict_reason = ""
        if age_seconds >= config.LOOP_EVICT_AGE_OUT_SECONDS:
            evict_reason = "aged_out_7d"
        elif (
            kind == "failed_steps"
            and age_seconds >= config.LOOP_EVICT_STUCK_AGE_SECONDS
            and (retry_count >= config.LOOP_EVICT_STUCK_RETRY_THRESHOLD)
        ):
            evict_reason = "stuck_24h_retry_3"
        if evict_reason:
            evicted_entry: Dict[str, Any] = {
                "actor": actor,
                "evicted_at": config._iso(now),
                "evict_reason": evict_reason,
                "original_item": item,
            }
            if note:
                evicted_entry["note"] = str(note)[:1000]
            if admin_user_id is not None:
                evicted_entry["admin_user_id"] = admin_user_id
            newly_evicted.append(evicted_entry)
        else:
            kept.append(item)
    memory["open_items"] = kept
    memory["evicted_items"] = (evicted_items + newly_evicted)[
        -config.LOOP_EVICT_MAX_ITEMS :
    ]
    if not newly_evicted:
        return {
            "evicted_count": 0,
            "evicted_items": [],
            "reasons": {"aged_out_7d": 0, "stuck_24h_retry_3": 0},
        }
    reasons = {
        "aged_out_7d": sum(
            (1 for entry in newly_evicted if entry["evict_reason"] == "aged_out_7d")
        ),
        "stuck_24h_retry_3": sum(
            (
                1
                for entry in newly_evicted
                if entry["evict_reason"] == "stuck_24h_retry_3"
            )
        ),
    }
    summary_record = {
        "action": "loop_evicted",
        "actor": actor,
        "admin_user_id": admin_user_id,
        "created_at": config._iso(now),
        "evicted_count": len(newly_evicted),
        "evicted_items": newly_evicted,
        "note": str(note or "")[:1000],
        "ok": True,
        "reasons": reasons,
        "source": "self_maintenance_loop_runner",
        "status": "evicted",
    }
    try:
        store._append_governance_audit(summary_record)
    except RECOVERABLE_ERRORS:
        config.logger.exception("failed to write loop_evicted governance audit")
    return {
        "evicted_count": len(newly_evicted),
        "evicted_items": newly_evicted,
        "reasons": reasons,
    }


def evict_loop_memory_items(
    *,
    actor: str = "manual",
    note: str = "",
    admin_user_id: Optional[Any] = None,
) -> Dict[str, Any]:
    """Manually evict stale loop-memory open_items (veto channel).

    Exposed via POST /api/xcmax/admin/loop/memory/evict for human override when
    the loop is stuck resuming long-failed runs.
    """
    memory = store._load_loop_memory()
    result = _evict_loop_memory_items(
        memory, actor=actor, note=note, admin_user_id=admin_user_id
    )
    memory["updated_at"] = config._iso(config._utc_now())
    store._write_loop_memory(memory)
    return {
        **result,
        "memory_path": str(store.loop_memory_path()),
        "open_items_remaining": len(memory.get("open_items") or []),
    }
