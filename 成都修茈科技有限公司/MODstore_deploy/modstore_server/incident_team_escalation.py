"""Durable escalation receipts on the original IncidentEvent, using Para dispatch.

Persist intent before I/O. An interrupted POST is reconciled by its original task
ID; it is never submitted again. Acceptance is independent of repair success.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from modstore_server.incident_team_escalation_contract import (
    active_context,
    dispatch_receipt,
    object_json,
    review_input,
    safe_text,
    task_receipt,
)
from modstore_server.models import IncidentEvent, get_session_factory
from modstore_server.node_coordinator import (
    IncidentClaimLost,
    assert_incident_claim,
    incident_claim_scope,
)
from modstore_server.operational_errors import RECOVERABLE_ERRORS

_CURSOR = 0
_TERMINAL = frozenset({"failed", "completed", "cancelled"})


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _receipts(payload: dict) -> dict:
    return (payload.get("_team_claim") or {}).get("escalations") or {}


def _write(db, event, payload: dict) -> None:
    assert_incident_claim(event.id, session=db)
    won = (
        db.query(IncidentEvent)
        .filter(IncidentEvent.id == event.id, IncidentEvent.payload_json == event.payload_json)
        .update(
            {"payload_json": json.dumps(payload, ensure_ascii=False)}, synchronize_session=False
        )
    )
    if not won:
        raise IncidentClaimLost("escalation_event_changed")
    db.commit()


def _save(event_id: int, key: str, changes: dict) -> dict:
    with get_session_factory()() as db:
        event = db.get(IncidentEvent, event_id)
        if event is None:
            raise ValueError("incident_missing")
        payload = object_json(event.payload_json)
        receipt = _receipts(payload)[key]
        _, blocked = active_context(db, event, receipt=receipt)
        receipt.update(changes, updated_at=_now())
        if blocked:
            receipt.update(state="cancelled", requires_reconciliation=False, error=blocked)
        _write(db, event, payload)
        return dict(receipt)


def _dispatch_review(data: dict) -> dict:
    from modstore_server.para_delegate_handler import dispatch_para_delegate

    result = dispatch_para_delegate(
        task=data["prompt"], input_data=data, employee_id="ultimate-incident-reviewer"
    )
    if not isinstance(result, dict):
        raise ValueError("invalid_escalation_response")
    return result


def _dispatch_requested(event_id: int, receipt: dict) -> dict:
    key = receipt["key"]
    with get_session_factory()() as db:
        event = db.get(IncidentEvent, event_id)
        payload, blocked = active_context(db, event, receipt=receipt)
    if blocked:
        return _save(event_id, key, {"state": "cancelled", "error": blocked})
    try:
        data = review_input(event_id, payload, receipt)
    except (ValueError, TypeError) as exc:
        return _save(event_id, key, {"state": "failed", "error": safe_text(exc)})
    receipt = _save(
        event_id,
        key,
        {
            "state": "dispatching",
            "dispatch_started_at": _now(),
            "target_tool": data["tool_name"],
            "target_device": data["device_id"],
            "requires_reconciliation": True,
        },
    )
    if receipt["state"] != "dispatching":
        return receipt
    assert_incident_claim(event_id)
    try:
        result = _dispatch_review(data)
        if not isinstance(result, dict):
            raise ValueError("invalid_escalation_response")
        changes = dispatch_receipt(result)
    except RECOVERABLE_ERRORS as exc:
        changes = {
            "state": "unknown",
            "accepted": False,
            "requires_reconciliation": True,
            "error": f"dispatch_receipt_unavailable:{type(exc).__name__}",
        }
    return _save(event_id, key, changes)


def request_incident_escalation(
    *, event_id: int, role: str, category: str, reason: str, attempted_actions: dict | None = None
) -> dict:
    """Request one read-only ultimate review for the persisted failed attempt."""
    try:
        with incident_claim_scope(event_id):
            with get_session_factory()() as db:
                event = db.get(IncidentEvent, event_id)
                payload, blocked = active_context(db, event)
                if blocked:
                    return {"state": "cancelled", "accepted": False, "error": blocked}
                claim = payload.get("_team_claim") or {}
                row: dict[str, Any] = next(
                    (r for r in claim.get("team") or [] if r.get("role") == role), {}
                )
                attempt = str(row.get("attempt_id") or "")
                if not attempt:
                    return {"state": "failed", "accepted": False, "error": "role_attempt_missing"}
                if row.get("ok") is True:
                    return {"state": "cancelled", "accepted": False, "error": "attempt_recovered"}
                identity = [
                    event_id,
                    payload.get("ticket_id"),
                    payload.get("user_id"),
                    role,
                    attempt,
                ]
                key = "escalation-" + hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:32]
                receipt = _receipts(payload).get(key)
                if receipt is None:
                    receipt = {
                        "key": key,
                        "event_id": event_id,
                        "role": role,
                        "attempt_id": attempt,
                        "state": "requested",
                        "accepted": False,
                        "task_id": "",
                        "completed": False,
                        "requires_reconciliation": False,
                        "category": category,
                        "reason": safe_text(reason),
                        "attempted_actions": {
                            name: value if isinstance(value, (bool, int)) else safe_text(value, 150)
                            for name, value in (attempted_actions or {}).items()
                            if name in {"action", "attempts", "max_rounds", "last_category"}
                        },
                        "requested_at": _now(),
                        "updated_at": _now(),
                    }
                    claim.setdefault("escalations", {})[key] = receipt
                    _write(db, event, payload)
                receipt = dict(receipt)
            if receipt["state"] == "requested":
                return _dispatch_requested(event_id, receipt)
            if receipt["state"] == "dispatching":
                return _save(
                    event_id,
                    key,
                    {
                        "state": "unknown",
                        "requires_reconciliation": True,
                        "error": "dispatch_interrupted_reconcile_original_attempt",
                    },
                )
            return receipt
    except RECOVERABLE_ERRORS as exc:
        # No replacement POST, including after a receipt-storage or claim failure.
        return {
            "state": "unknown",
            "accepted": False,
            "requires_reconciliation": True,
            "error": f"escalation_unavailable:{type(exc).__name__}",
        }


def _reconcile_one(event_id: int, key: str, *, base: str, fetcher) -> bool:
    with incident_claim_scope(event_id):
        with get_session_factory()() as db:
            event = db.get(IncidentEvent, event_id)
            payload, blocked = active_context(db, event)
            receipt = _receipts(payload).get(key)
            if not receipt or receipt["state"] in _TERMINAL:
                return False
            receipt = dict(receipt)
        if blocked:
            _save(event_id, key, {"state": "cancelled", "error": blocked})
        elif receipt["state"] == "requested":
            _dispatch_requested(event_id, receipt)
        elif receipt.get("task_id"):
            try:
                changes = task_receipt(receipt, fetcher(base, receipt["task_id"]))
            except RECOVERABLE_ERRORS as exc:
                changes = {"poll_error": f"original_task_unavailable:{type(exc).__name__}"}
            _save(event_id, key, changes)
        else:
            _save(
                event_id,
                key,
                {
                    "state": "unknown",
                    "requires_reconciliation": True,
                    "error": "original_task_id_missing_manual_review",
                },
            )
        return True


def reconcile_incident_escalations(*, event_id=None, limit=20, fetcher=None) -> dict:
    """Called by the existing team completion job, including settled team events."""
    from modstore_server.maintenance_loop.para_client import _fetch_para_task_state
    from modstore_server.para_delegate_handler import _api_base

    global _CURSOR
    fetcher = fetcher or _fetch_para_task_state
    base = _api_base()
    with get_session_factory()() as db:
        query = db.query(IncidentEvent).filter(IncidentEvent.payload_json.contains('"escalations"'))
        if event_id is not None:
            query = query.filter(IncidentEvent.id == event_id)
        after = _CURSOR if event_id is None else 0
        events = (
            query.filter(IncidentEvent.id > after).order_by(IncidentEvent.id).limit(limit).all()
        )
        if not events and event_id is None:
            events = query.order_by(IncidentEvent.id).limit(limit).all()
        items = [(int(ev.id), list(_receipts(object_json(ev.payload_json)))) for ev in events]
        if event_id is None:
            _CURSOR = int(events[-1].id) if events else 0
    changed = 0
    for eid, keys in items:
        for key in keys:
            try:
                changed += _reconcile_one(eid, key, base=base, fetcher=fetcher)
            except RECOVERABLE_ERRORS:
                continue  # Another owner or unavailable storage; next existing-job tick retries.
    return {"checked": len(items), "changed": changed}
