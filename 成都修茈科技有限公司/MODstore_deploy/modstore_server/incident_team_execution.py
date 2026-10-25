"""Durable incident roles: reuse completed evidence and start each dependency once."""

from __future__ import annotations

import json
import uuid
from copy import deepcopy
from typing import Any, cast

from modstore_server.customer_issue_delivery_contract import (
    execution_pending,
    execution_succeeded,
    team_succeeded,
)
from modstore_server.incident_team_handler_digest import handler_output_digest
from modstore_server.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

_ROLES = ("scout", "fix", "verify")
_READY = {"planned", "skipped_fix_unfinished", "verification_invalidated"}


def locked_ticket_repair(db, payload):
    """Serialize shared reuse with new intents and customer progress, not receipt history."""
    from modstore_server.customer_issue_shared_repairs import active_shared_repair
    from modstore_server.models_cs import CustomerServiceTicket

    ticket = db.get(
        CustomerServiceTicket, int(payload.get("ticket_id") or 0), with_for_update=True
    )
    return ticket, active_shared_repair(db, ticket)


def _write_payload(db, event, payload):
    """Readback also writes progress, so the lease alone does not fence this projection."""
    from modstore_server.models import IncidentEvent

    won = (
        db.query(IncidentEvent)
        .filter(
            IncidentEvent.id == event.id,
            IncidentEvent.payload_json == event.payload_json,
        )
        .update(
            {"payload_json": json.dumps(payload, ensure_ascii=False)},
            synchronize_session=False,
        )
    )
    if not won:
        raise ValueError("incident progress changed concurrently")


def _context(event_id):
    from modstore_server import incident_team_orchestrator as facade

    with facade.get_session_factory()() as db:
        event = db.get(facade.IncidentEvent, event_id)
        if event is None:
            return None
        payload = facade._payload(event)
        claim = payload.get("_team_claim")
        if not isinstance(claim, dict):
            return None
        ticket, shared_repair = locked_ticket_repair(db, payload)
        if ticket is not None:
            resolution = (
                json.loads(ticket.evidence_json or "{}").get("resolution") or {}
            )
            if (
                ticket.user_id != int(payload.get("user_id") or 0)
                or ticket.status in {"resolved", "closed", "reopened"}
                or ticket.closed_at
                or resolution.get("state") in {"closed", "reopened"}
                or resolution.get("incident_event_id") not in (None, event_id)
                or shared_repair
            ):
                return None
        return payload, claim, str(event.event_type or ""), str(event.source or "")


def _complete_plan(claim):
    rows = {row.get("role"): row for row in claim.get("team") or []}
    members = {
        member.get("role"): member.get("employee_id")
        for member in (claim.get("plan") or {}).get("team") or []
    }
    return not any(
        not members.get(role) or rows.get(role, {}).get("employee_id") != members[role]
        for role in _ROLES
    )


def _next_member(claim):
    if not _complete_plan(claim):
        return (
            None  # Legacy receipts without a complete saved plan only permit readback.
        )
    rows = {row.get("role"): row for row in claim.get("team") or []}
    for role in _ROLES:
        row = rows.get(role)
        if row is None:
            return None  # An old, incomplete plan cannot authorize a new employee.
        if (
            role == "verify"
            and row.get("ok") is True
            and rows.get("fix", {}).get("attempt_id")
            and row.get("verified_fix_attempt_id") != rows["fix"]["attempt_id"]
        ):
            return {**row, "ok": False, "status": "verification_invalidated"}
        if row.get("ok") is True:
            continue
        if row.get("status") not in _READY or not row.get("employee_id"):
            return None
        if row.get("status") == "planned" and row.get("attempt_id"):
            return None  # Intent with an attempt is not an unstarted role.
        return row
    return None


def execute_member(event_id, member, plan, payload, event_type, source, rows):
    from modstore_server import incident_team_orchestrator as facade
    from modstore_server.incident_team_completion import persist_role_attempt
    from modstore_server.incident_team_dispatch import member_runtime_input

    role, employee = member["role"], member["employee_id"]
    previous = {row.get("role"): row for row in rows}
    try:
        from modstore_server.incident_model_router import (
            bench_override_for_route,
            route_for_incident,
        )

        route = route_for_incident(event_type=event_type, payload=payload, role=role)
        override = bench_override_for_route(route)
    except RECOVERABLE_ERRORS:
        route, override = (
            {"provider": "auto", "model": "auto", "reason": "router_error"},
            None,
        )
    task = facade._task_for_role(
        code_ownership=plan.get("code_owner_match") if role == "fix" else None,
        event_type=event_type,
        payload=payload,
        role=role,
        scout_result=previous.get("scout"),
        fix_result=previous.get("fix"),
    )
    attempt = uuid.uuid4().hex
    runtime = member_runtime_input(
        employee_id=employee,
        role=role,
        event_id=event_id,
        team_plan=plan,
        payload=payload,
        event_type=event_type,
        source=source,
        route=route,
        attempt_id=attempt,
        fix_result=previous.get("fix"),
    )
    runtime["release_recovery"] = (payload.get("_team_claim") or {}).get(
        "recovery"
    ) or {}
    row = {
        "role": role,
        "employee_id": employee,
        "attempt_id": attempt,
        "event_id": event_id,
        "tenant_id": runtime.get("tenant_id"),
        "status": "dispatching",
        "outcome": "unknown",
        "ok": False,
        "verified_fix_attempt_id": runtime["revision"] if role == "verify" else "",
    }
    if runtime.get("independent_checks"):
        row["check_units"] = deepcopy(runtime["independent_checks"])
    persist_role_attempt(event_id, row)
    result = facade._execute_employee_task_with_timeout(
        employee,
        task,
        runtime,
        user_id=0,
        bench_llm_override=override,
        timeout_seconds=facade._role_timeout_seconds(role),
    )
    result = {**result, "attempt_id": attempt, "event_id": event_id}
    succeeded, pending = execution_succeeded(result), execution_pending(result)
    status = str(result.get("status") or result.get("execution_status") or "")
    row.update(
        ok=succeeded,
        handler_outputs=handler_output_digest(result),
        route=route,
        status="pending"
        if pending
        else "completed"
        if succeeded
        else status or "failed",
    )
    row.pop("outcome", None)
    persist_role_attempt(event_id, row, expected_attempt=attempt)


def _follow_up(event_id, context):
    """Persist follow-up intent; an interrupted decision is not proof of completion."""
    from modstore_server import incident_team_orchestrator as facade
    from modstore_server.node_coordinator import assert_incident_claim

    payload, claim, event_type, source = context
    if not _complete_plan(claim) or not facade._env_bool(
        facade._HANDLER_FAILED_FOLLOWUP_ENV, True
    ):
        return
    handled = list(claim.get("failure_handled_attempts") or [])
    interrupted = {
        attempt: intent
        for attempt, intent in (claim.get("follow_up_intents") or {}).items()
        if intent.get("state") == "dispatching"
    }
    if interrupted:
        with facade.get_session_factory()() as db:
            assert_incident_claim(event_id, session=db)
            event = db.get(facade.IncidentEvent, event_id)
            current = facade._payload(event)
            if locked_ticket_repair(db, current)[1]:
                return
            saved = current["_team_claim"]
            for attempt, intent in interrupted.items():
                row = next(
                    (r for r in saved["team"] if r.get("role") == intent["role"]), {}
                )
                evidence = row.get("attempt_id") not in (None, attempt) or any(
                    receipt.get("attempt_id") == attempt
                    for receipt in (saved.get("escalations") or {}).values()
                )
                if evidence:
                    handled.append(attempt)
                    saved["follow_up_intents"][attempt]["state"] = "receipt_recorded"
                else:
                    row.update(ok=False, status="manual_review", outcome="unknown")
                    row.setdefault("handler_outputs", {})["poll_error"] = (
                        "Follow-up interrupted before a durable retry or handoff receipt; do not replay"
                    )
                    saved["follow_up_intents"][attempt]["state"] = "unknown"
            saved["failure_handled_attempts"] = handled
            _write_payload(db, event, current)
            db.commit()
        return
    failures = [
        row
        for row in claim.get("team") or []
        if row.get("status") in {"failed", "handler_failed"}
        and row.get("attempt_id")
        and row["attempt_id"] not in handled
    ]
    if not failures:
        return
    with facade.get_session_factory()() as db:
        assert_incident_claim(event_id, session=db)
        event = db.get(facade.IncidentEvent, event_id)
        current = facade._payload(event)
        if locked_ticket_repair(db, current)[1]:
            return
        saved = current["_team_claim"]
        saved["continuation_pending"] = True
        intents = saved.setdefault("follow_up_intents", {})
        for row in failures:
            intents[row["attempt_id"]] = {"role": row["role"], "state": "dispatching"}
        _write_payload(db, event, current)
        db.commit()
    results = deepcopy(claim.get("team") or [])
    failure_ids = {row["attempt_id"] for row in failures}
    for row in results:
        digest = row.get("handler_outputs") or {}
        row["result"] = {**digest, "result": digest}
        if row.get("attempt_id") in failure_ids:
            row["result"]["handler_failed"] = True
        else:
            row["result"].pop("handler_failed", None)
            if row["result"].get("status") == "handler_failed":
                row["result"]["status"] = "failed"
    follow_ups = facade._follow_up_handler_failures(
        event_id=event_id,
        results=results,
        team_plan=claim.get("plan") or {},
        payload=payload,
        event_type=event_type,
        source=source,
        uid=0,
    )
    with facade.get_session_factory()() as db:
        assert_incident_claim(event_id, session=db)
        event = db.get(facade.IncidentEvent, event_id)
        current = facade._payload(event)
        saved = current["_team_claim"]
        saved["failure_handled_attempts"] = list(
            dict.fromkeys(
                [
                    *(saved.get("failure_handled_attempts") or []),
                    *failure_ids,
                ]
            )
        )
        for attempt in failure_ids:
            saved["follow_up_intents"][attempt]["state"] = "completed"
        saved.setdefault("follow_ups", []).extend(follow_ups)
        # Retry execution persists its own attempts. Retain the latest DB receipts.
        _write_payload(db, event, current)
        db.commit()


def project_team(event_id: int) -> dict[str, Any]:
    from modstore_server import incident_team_orchestrator as facade
    from modstore_server.customer_issue_shared_release import record_worker_repair
    from modstore_server.customer_service_orchestrator import (
        apply_customer_ticket_incident_progress,
    )
    from modstore_server.node_coordinator import assert_incident_claim

    progress: dict[str, Any] = {}
    with facade.get_session_factory()() as db:
        assert_incident_claim(event_id, session=db)
        event = db.get(facade.IncidentEvent, event_id)
        if event is None:
            return {"claimed": False, "ok": False, "reason": "incident_not_found"}
        payload = facade._payload(event)
        claim = payload.get("_team_claim") or {}
        rows = claim.get("team") or []
        claim.update(
            ok=team_succeeded(rows),
            continuation_pending=bool(_next_member(claim)),
            handler_failed_roles=[
                row.get("role")
                for row in rows
                if row.get("status") in {"failed", "handler_failed", "manual_review"}
            ],
        )
        claim["handler_failed_count"] = len(claim["handler_failed_roles"])
        ticket, shared_repair = locked_ticket_repair(db, payload)
        resolution = (
            json.loads(str(ticket.evidence_json or "{}")).get("resolution") or {}
            if ticket
            else {}
        )
        if ticket and (
            not shared_repair
            and ticket.user_id == int(payload.get("user_id") or 0)
            and ticket.status not in {"resolved", "closed", "reopened"}
            and not ticket.closed_at
            and resolution.get("state") not in {"closed", "reopened"}
            and resolution.get("incident_event_id") in (None, event_id)
        ):
            try:
                progress = apply_customer_ticket_incident_progress(
                    db,
                    ticket_id=cast(int, ticket.id),
                    event_id=event_id,
                    team_ok=claim["ok"],
                    team_rows=rows,
                    summary_hint=str(payload.get("summary") or "")[:200],
                )
                record_worker_repair(db, ticket, event_id, rows)
                if claim.get("follow_ups"):
                    from modstore_server.incident_team_dispatch import (
                        _write_repair_loop,
                    )

                    _write_repair_loop(db, ticket, event_id, claim["follow_ups"])
                payload["_cs_progress"] = {
                    key: progress.get(key)
                    for key in (
                        "ok",
                        "lifecycle_stage",
                        "lifecycle_label",
                        "message_id",
                        "team_ok",
                    )
                }
            except BOUNDARY_ERRORS as exc:
                facade.logger.exception(
                    "incident team progress failed event_id=%s", event_id
                )
                progress = {"ok": False, "error": str(exc)[:300]}
        _write_payload(db, event, payload)
        db.commit()
    return {
        "claimed": True,
        "event_id": event_id,
        "ok": claim["ok"],
        "results": rows,
        "team": claim.get("plan") or {},
        "recovery": claim.get("recovery") or {},
        "follow_ups": claim.get("follow_ups") or [],
        "cs_progress": progress,
    }


def advance_team(event_id: int) -> dict[str, Any]:
    """Run only unstarted dependency-ready roles under the original incident lease."""
    from modstore_server.node_coordinator import incident_claim_scope

    with incident_claim_scope(event_id):
        for _ in _ROLES:
            context = _context(event_id)
            if context is None:
                return {"claimed": True, "ok": False, "reason": "incident_not_active"}
            _follow_up(event_id, context)
            context = _context(event_id)
            if context is None:
                break
            payload, claim, event_type, source = context
            member = _next_member(claim)
            if member is None:
                break
            execute_member(
                event_id,
                member,
                claim.get("plan") or {},
                payload,
                event_type,
                source,
                claim.get("team") or [],
            )
        context = _context(event_id)
        if context is not None:
            _follow_up(event_id, context)
        return project_team(event_id)
