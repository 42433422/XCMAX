"""Read original task receipts and advance durable dependency-ready incident roles."""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from typing import Any

from modstore_server.codex_model_attempts import parse_codex_models_tried
from modstore_server.customer_issue_delivery_contract import (
    execution_pending,
    execution_requires_reconciliation,
    execution_succeeded,
    para_task_succeeded,
    team_succeeded,
)
from modstore_server.incident_team_handler_digest import (
    handler_output_digest,
    redact_text,
)
from modstore_server.models import IncidentEvent, get_session_factory
from modstore_server.operational_errors import RECOVERABLE_ERRORS

_PENDING_CURSOR = 0


def reconcile_pending_teams(*, event_id=None, limit=20, fetcher=None):
    from modstore_server.customer_issue_shared_release import record_worker_repair
    from modstore_server.customer_service_orchestrator import (
        apply_customer_ticket_incident_progress,
    )
    from modstore_server.incident_team_execution import locked_ticket_repair
    from modstore_server.maintenance_loop.para_client import _fetch_para_task_state
    from modstore_server.para_delegate_handler import (
        _api_base,
        _first_para_error,
        _task_result_snapshot,
    )

    global _PENDING_CURSOR
    fetcher = fetcher or _fetch_para_task_state
    base = _api_base()
    sf = get_session_factory()
    changed = 0
    with sf() as db:
        query = db.query(IncidentEvent)
        if event_id is not None:
            query = query.filter(IncidentEvent.id == event_id)
        else:
            query = query.filter(
                IncidentEvent.payload_json.contains('"status": "pending"')
                | IncidentEvent.payload_json.contains('"status": "para_task_accepted"')
                | IncidentEvent.payload_json.contains('"requires_reconciliation": true')
                | IncidentEvent.payload_json.contains('"status": "unknown"')
                | IncidentEvent.payload_json.contains('"status": "dispatching"')
                | IncidentEvent.payload_json.contains('"continuation_pending": true')
            )

        def page(after=0):
            return [
                (ev.id, ev.payload_json)
                for ev in query.filter(IncidentEvent.id > after)
                .order_by(IncidentEvent.id)
                .limit(limit)
            ]

        events = page(_PENDING_CURSOR if event_id is None else 0)
        if event_id is None:
            if not events:
                events = page()
            _PENDING_CURSOR = events[-1][0] if events else 0
    for eid, original in events:
        payload = json.loads(original or "{}")
        claim = payload.get("_team_claim")
        if not isinstance(claim, dict):
            continue
        rows = deepcopy(claim.get("team") or [])
        for row in rows:
            digest = row.get("handler_outputs") or {}
            outputs = digest.get("outputs") or []
            pending = [
                o
                for o in outputs
                if o.get("handler") == "para_delegate" and execution_requires_reconciliation(o)
            ]
            for output in pending:
                task_id = str(output.get("para_task_id") or output.get("task_id") or "")
                if not task_id:
                    output.update(
                        ok=False,
                        status="para_task_missing_id",
                        error="缺少原任务号，需人工核对",
                    )
                    row["status"] = "manual_review"
                    continue
                try:
                    if not base and fetcher is _fetch_para_task_state:
                        raise ValueError("Para API 未配置")
                    task = fetcher(base, task_id)
                    if str(task.get("id") or "") != task_id:
                        raise ValueError("Para返回任务号不一致")
                    status = str(task.get("status") or "")
                    if status in {"completed", "merged", "failed", "merge_conflict"}:
                        ok = para_task_succeeded(
                            task,
                            task_id,
                            output.get("required_subtask_ids"),
                            output.get("planned_devices"),
                        ) and not output.get("partial")
                        snapshot = _task_result_snapshot({"task": task})
                        output.update(
                            ok=ok,
                            completed=ok,
                            status=(
                                "para_task_" + status
                                if ok or status in {"failed", "merge_conflict"}
                                else "partial"
                            ),
                            summary=redact_text(task.get("summary") or ""),
                            para_result=snapshot,
                            outcome=(
                                "terminal"
                                if ok or status in {"failed", "merge_conflict"}
                                else "unknown"
                            ),
                            requires_reconciliation=not ok
                            and status not in {"failed", "merge_conflict"},
                        )
                        output.pop("error", None)
                        if not ok:
                            output["error"] = redact_text(
                                task.get("error") or _first_para_error(snapshot) or "Para任务失败"
                            )
                        tried = parse_codex_models_tried(
                            task.get("error"),
                            _first_para_error(snapshot),
                            task.get("summary"),
                        )
                        if tried:
                            output["codex_models_tried"] = tried
                    digest.pop("poll_error", None)
                except RECOVERABLE_ERRORS as exc:
                    code = getattr(getattr(exc, "response", None), "status_code", "")
                    digest["poll_error"] = redact_text(
                        f"原任务 {task_id} 读取失败 {code or ('API 未配置' if not base else '')} ({type(exc).__name__})"
                    )
            if row.get("status") == "dispatching" and not pending:
                row.update(ok=False, status="manual_review", outcome="unknown")
                digest["poll_error"] = (
                    "Dispatch intent has no durable receipt; reconcile original attempt, never resubmit"
                )
            if pending:
                row["handler_outputs"] = handler_output_digest(
                    {**digest, "result": {**digest, "outputs": outputs}}
                )
                row["ok"] = execution_succeeded({"result": {"outputs": outputs}})
                if row.get("status") != "manual_review":
                    row["status"] = (
                        "pending"
                        if execution_pending({"result": {"outputs": outputs}})
                        else "completed" if row["ok"] else "failed"
                    )
        if rows == claim.get("team"):
            _resume_pending_verify(eid)
            continue
        claim.update(
            team=rows,
            ok=team_succeeded(rows),
            handler_failed_roles=[
                r.get("role") for r in rows if r.get("status") in {"failed", "manual_review"}
            ],
        )
        claim["handler_failed_count"] = len(claim["handler_failed_roles"])
        with sf() as db:
            ticket, shared_repair = locked_ticket_repair(db, payload)
            if ticket is not None:
                evidence = json.loads(str(ticket.evidence_json or "{}"))
                resolution = evidence.get("resolution") or {}
                if ticket.user_id != int(payload.get("user_id") or 0) or resolution.get(
                    "incident_event_id"
                ) not in (None, eid):
                    continue
            updated = json.dumps(payload, ensure_ascii=False)
            won = (
                db.query(IncidentEvent)
                .filter(IncidentEvent.id == eid, IncidentEvent.payload_json == original)
                .update({"payload_json": updated}, synchronize_session=False)
            )
            if not won:
                continue
            if (
                ticket is not None
                and not shared_repair
                and ticket.status not in {"resolved", "closed", "reopened"}
                and not ticket.closed_at
                and resolution.get("state") != "reopened"
            ):
                apply_customer_ticket_incident_progress(
                    db,
                    ticket_id=ticket.id,
                    event_id=eid,
                    team_ok=claim["ok"],
                    team_rows=rows,
                )
                record_worker_repair(db, ticket, eid, rows)
            db.commit()
            changed += 1
        _resume_pending_verify(eid)
    from modstore_server.incident_team_escalation import reconcile_incident_escalations

    escalations = reconcile_incident_escalations(event_id=event_id, limit=limit, fetcher=fetcher)
    return {"changed": changed, "escalations": escalations}


def _resume_pending_verify(event_id: int) -> None:
    """Compatibility entry point: every unstarted role resumes from the saved plan."""
    from modstore_server.incident_team_execution import advance_team

    try:
        advance_team(event_id)
    except RECOVERABLE_ERRORS:
        # Existing dispatch intents remain fenced; recovery never replays them.
        logging.getLogger(__name__).warning("incident continuation deferred event=%s", event_id)


def register_completion_job(scheduler, *, track_job):
    scheduler.add_job(
        lambda: track_job("incident_team_completion", reconcile_pending_teams),
        "interval",
        seconds=30,
        id="incident_team_completion",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    from modstore_server.para_task_events import start_task_event_listener

    listener = start_task_event_listener()
    if listener is not None and hasattr(scheduler, "add_listener"):
        from apscheduler.events import EVENT_SCHEDULER_SHUTDOWN

        scheduler.add_listener(lambda event: listener.stop(), EVENT_SCHEDULER_SHUTDOWN)


def reconcile_task_notification(task_id=None, *, fetcher=None):
    """A live hint only selects persisted task IDs; status in the event is never proof."""
    if task_id is None:
        return reconcile_pending_teams(fetcher=fetcher)
    with get_session_factory()() as db:
        candidates = [
            (event.id, json.loads(event.payload_json or "{}"))
            for event in db.query(IncidentEvent)
            .filter(IncidentEvent.payload_json.contains(task_id, autoescape=True))
            .order_by(IncidentEvent.id)
            .limit(100)
        ]
    matched = []
    for event_id, payload in candidates:
        claim = payload.get("_team_claim") or {}
        receipts = [
            output
            for row in claim.get("team") or []
            for output in (row.get("handler_outputs") or {}).get("outputs") or []
            if output.get("handler") == "para_delegate"
        ]
        receipts += list((claim.get("escalations") or {}).values())
        if any(
            isinstance(receipt, dict)
            and str(receipt.get("task_id") or receipt.get("para_task_id") or "") == task_id
            for receipt in receipts
        ):
            reconcile_pending_teams(event_id=event_id, fetcher=fetcher)
            matched.append(event_id)
    return {"matched_events": matched}


def persist_role_attempt(event_id: int, row: dict[str, Any], *, expected_attempt: str = "") -> None:
    """Commit intent before execution and its receipt only under current ownership."""
    from modstore_server.incident_team_execution import locked_ticket_repair
    from modstore_server.node_coordinator import assert_incident_claim

    with get_session_factory()() as db:
        assert_incident_claim(event_id, session=db)
        event = db.get(IncidentEvent, int(event_id))
        if event is None:
            raise ValueError("incident not found")
        original = event.payload_json
        payload = json.loads(str(event.payload_json or "{}"))
        if not expected_attempt and locked_ticket_repair(db, payload)[1]:
            raise ValueError("shared_repair_reused")
        claim = payload.setdefault("_team_claim", {"ok": False, "team": []})
        rows = claim.setdefault("team", [])
        previous = next((item for item in rows if item.get("role") == row.get("role")), None)
        if expected_attempt and (
            previous is None or previous.get("attempt_id") != expected_attempt
        ):
            raise ValueError("incident attempt was superseded")
        if (
            previous is not None
            and expected_attempt
            and previous.get("status") in {"completed", "failed"}
            and row.get("status") in {"pending", "dispatching"}
        ):
            return  # A late terminal receipt must not be replaced by its earlier timeout.
        if previous is not None and expected_attempt:
            row = {
                **{
                    key: previous.get(key)
                    for key in (
                        "verified_fix_attempt_id",
                        "event_id",
                        "tenant_id",
                        "route",
                        "check_units",
                    )
                },
                **row,
            }
        if previous is not None:
            rows[rows.index(previous)] = row
        else:
            rows.append(row)
        claim["ok"] = team_succeeded(rows)
        won = (
            db.query(IncidentEvent)
            .filter(
                IncidentEvent.id == event_id,
                IncidentEvent.payload_json == original,
            )
            .update(
                {"payload_json": json.dumps(payload, ensure_ascii=False)},
                synchronize_session=False,
            )
        )
        if not won:
            raise ValueError("incident progress changed concurrently")
        db.commit()


def persist_late_role_result(
    event_id: int, role: str, employee_id: str, attempt_id: str, result: dict[str, Any]
) -> None:
    from contextvars import Context

    from modstore_server.node_coordinator import IncidentClaimLost, incident_claim_scope

    def save():
        with incident_claim_scope(event_id):
            receipt = {**result, "attempt_id": attempt_id, "event_id": event_id}
            row = {
                "role": role,
                "employee_id": employee_id,
                "attempt_id": attempt_id,
                "ok": execution_succeeded(receipt),
                "status": (
                    "pending"
                    if execution_requires_reconciliation(receipt)
                    else "completed" if execution_succeeded(receipt) else "failed"
                ),
                "handler_outputs": handler_output_digest(receipt),
            }
            persist_role_attempt(event_id, row, expected_attempt=attempt_id)

    try:
        try:
            save()
        except IncidentClaimLost:
            Context().run(save)  # receipt-only reconciliation under a new live owner
        # A late worker must not share its original owner token to dispatch new work.
        Context().run(_resume_pending_verify, event_id)
    except RECOVERABLE_ERRORS:
        logging.getLogger(__name__).warning(
            "incident late receipt requires external readback event=%s role=%s",
            event_id,
            role,
        )
