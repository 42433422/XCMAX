# mypy: disable-error-code="arg-type, assignment, union-attr"
"""Primary dynamic-team incident dispatch workflow."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

from modstore_server import incident_team_orchestrator as facade
from modstore_server.incident_team_handler_digest import handler_output_digest
from modstore_server.operational_errors import RECOVERABLE_ERRORS


def dispatch_incident_team(event_id: int) -> dict[str, Any]:
    from modstore_server.node_coordinator import incident_claim_scope

    try:
        with incident_claim_scope(event_id):
            return _dispatch_incident_team_once(event_id)
    except RECOVERABLE_ERRORS as exc:
        # A partial dispatch may already exist. Never send it to a fallback executor.
        return {
            "claimed": True,
            "ok": False,
            "event_id": event_id,
            "status": "unknown",
            "outcome": "unknown",
            "requires_reconciliation": True,
            "retryable": False,
            "error": f"incident dispatch requires readback: {type(exc).__name__}",
        }


def _dispatch_incident_team_once(event_id: int) -> dict[str, Any]:
    _env_bool = facade._env_bool
    build_incident_team = facade.build_incident_team
    get_session_factory = facade.get_session_factory
    IncidentEvent = facade.IncidentEvent
    _payload = facade._payload

    if not _env_bool("MODSTORE_INCIDENT_TEAM_ENABLED", True):
        return {"claimed": False, "ok": False, "reason": "incident_team_disabled"}
    with get_session_factory()() as session:
        saved = session.get(IncidentEvent, int(event_id))
        if saved is not None and isinstance(_payload(saved).get("_team_claim"), dict):
            from modstore_server.incident_team_completion import reconcile_pending_teams

            reconcile_pending_teams(event_id=int(event_id))
            session.expire(saved)
            return {
                "claimed": True,
                "ok": bool(_payload(saved)["_team_claim"].get("ok")),
                "reason": "incident_completion_readback",
            }
    team_plan = build_incident_team(event_id)
    team = team_plan.get("team") if isinstance(team_plan.get("team"), list) else []
    if len(team) < 2:
        return {
            **team_plan,
            "claimed": False,
            "ok": False,
            "reason": "insufficient_team",
        }

    sf = get_session_factory()
    with sf() as session:
        ev = session.get(IncidentEvent, int(event_id))
        if ev is None:
            return {"claimed": False, "ok": False, "reason": "incident_not_found"}
        payload = _payload(ev)
        event_type = str(ev.event_type or "")
        source = str(ev.source or "")
        if int(ev.dispatched_count or 0) > 0 and not _env_bool(
            "MODSTORE_INCIDENT_TEAM_REDISPATCH", False
        ):
            # website_runner 等可能先自增 dispatched_count；客服工单在尚无
            # _team_claim 时仍应跑事故小组，否则用户侧永远「没人去」。
            has_team_claim = isinstance(payload.get("_team_claim"), dict)
            try:
                ticket_id_hint = int(payload.get("ticket_id") or 0)
            except (TypeError, ValueError):
                ticket_id_hint = 0
            customer_ticket = ticket_id_hint > 0 and (
                str(payload.get("source") or source or "").strip().lower()
                == "customer_ticket"
                or event_type == "ops.intake.customer_ticket"
                or str(payload.get("ticket_no") or "").startswith("CS")
            )
            if has_team_claim or not customer_ticket:
                return {
                    "claimed": False,
                    "ok": True,
                    "reason": "incident_already_dispatched",
                }

    from modstore_server.incident_team_execution import _write_payload, advance_team
    from modstore_server.node_coordinator import assert_incident_claim

    # Freeze server-selected check scopes before the first external side effect.
    checks = team_plan.get("independent_checks")
    if checks is None:
        try:
            checks = json.loads(
                os.environ.get("MODSTORE_INCIDENT_TEAM_CHECKS_JSON") or "{}"
            )
        except (TypeError, ValueError):
            checks = {}
    team_plan = {
        **team_plan,
        "execution_schema": 2,
        "independent_checks": checks if isinstance(checks, dict) else {},
    }
    with sf() as session:
        assert_incident_claim(event_id, session=session)
        ev = session.get(IncidentEvent, int(event_id))
        updated = _payload(ev)
        ticket_id = int(updated.get("ticket_id") or 0)
        if ticket_id:
            from modstore_server.customer_issue_shared_repairs import (
                active_shared_repair,
            )
            from modstore_server.models_cs import CustomerServiceTicket

            ticket = session.get(CustomerServiceTicket, ticket_id, with_for_update=True)
            if ticket is None or ticket.user_id != int(updated.get("user_id") or 0):
                return {
                    "claimed": True,
                    "ok": False,
                    "reason": "incident_scope_mismatch",
                }
            if active_shared_repair(session, ticket):
                return {"claimed": True, "ok": False, "reason": "shared_repair_reused"}
            evidence = json.loads(ticket.evidence_json or "{}")
            resolution = evidence.get("resolution") or {}
            original_resolution = updated.get("resolution") or {}
            if (
                resolution.get("state") == "reopened"
                and ticket.status == "processing"
                and not ticket.closed_at
                and original_resolution.get("reopened_at")
                and original_resolution.get("reopened_at")
                == resolution.get("reopened_at")
            ):
                # A fresh reopen owns a new event; an old event keeps its old timestamp.
                resolution.update(state="processing", incident_event_id=int(event_id))
                evidence["resolution"] = resolution
                ticket.evidence_json = json.dumps(evidence, ensure_ascii=False)
        if not isinstance(updated.get("_team_claim"), dict):
            updated["_team_claim"] = {
                "schema_version": 2,
                "claimed_at": datetime.now(UTC).isoformat(),
                "ok": False,
                "recovery": {},
                "plan": team_plan,
                "event_type": event_type,
                "continuation_pending": True,
                "follow_ups": [],
                "handler_failed_roles": [],
                "handler_failed_count": 0,
                "team": [
                    {
                        "role": member["role"],
                        "employee_id": member["employee_id"],
                        "event_id": int(event_id),
                        "status": "planned",
                        "ok": False,
                        "handler_outputs": handler_output_digest({}),
                    }
                    for member in team
                    if member.get("role") and member.get("employee_id")
                ],
            }
            ev.payload_json = json.dumps(updated, ensure_ascii=False)
            ev.dispatched_count = int(ev.dispatched_count or 0) + 1
            session.commit()
    try:
        from modstore_server.release_recovery_orchestrator import maybe_execute_recovery

        recovery = maybe_execute_recovery(
            event_id=event_id, event_type=event_type, payload=payload
        )
    except RECOVERABLE_ERRORS as exc:
        recovery = {"ok": False, "error": str(exc)[:500]}
    with sf() as session:
        assert_incident_claim(event_id, session=session)
        ev = session.get(IncidentEvent, int(event_id))
        updated = _payload(ev)
        updated["_team_claim"]["recovery"] = recovery
        _write_payload(session, ev, updated)
        session.commit()
    return advance_team(int(event_id))


def _write_repair_loop(
    session, ticket, event_id: int, follow_ups: list[dict[str, Any]]
) -> None:
    """把失败分类、处置次数、原因、是否升级回写工单（仅管理端证据与审计，客户视图白名单不含）。"""
    from modstore_server.customer_service_tools import audit
    from modstore_server.incident_team_failure_loop import loop_summary

    summary = loop_summary(follow_ups)
    evidence = json.loads(ticket.evidence_json or "{}")
    evidence = evidence if isinstance(evidence, dict) else {}
    evidence["repair_loop"] = {"event_id": event_id, "items": summary}
    ticket.evidence_json = json.dumps(evidence, ensure_ascii=False)
    escalated = [item for item in summary if item.get("escalated_to")]
    audit(
        session,
        event_type="incident.repair_loop_escalated"
        if escalated
        else "incident.repair_loop",
        detail={"event_id": event_id, "items": summary},
        ticket_id=int(ticket.id),
        actor_type="system",
    )


def member_runtime_input(
    *,
    employee_id,
    role,
    event_id,
    team_plan,
    payload,
    event_type,
    source,
    route,
    attempt_id,
    fix_result=None,
):
    """The first call and recovery use the same trusted scope and execution lineage."""
    from modstore_server.duty_workforce_contracts import duty_event_execution_input
    from modstore_server.incident_team_handoff import role_handoff

    runtime = (
        duty_event_execution_input(
            employee_id, event_type=event_type, source=source, incident=payload
        )
        or {}
    )
    runtime.update(
        {
            "allow_high_risk_real_run": role in {"fix", "verify"},
            "allow_medium_risk": True,
            "incident": payload,
            "incident_team": team_plan,
            "model_route": route,
            "role": role,
            "source": source,
            "suppress_lifecycle_events": True,
            "unified_incident_bus": True,
            "_trusted_incident_team_execution": True,
            "event_type": event_type,
            "event_id": int(event_id),
            "tenant_id": payload.get("tenant_id") or payload.get("user_id"),
            "user_id": payload.get("user_id"),
            "attempt_id": attempt_id,
            "request_id": attempt_id,
            "revision": str((fix_result or {}).get("attempt_id") or ""),
            # A server-owned selector, never a copy of the customer's prompt.
            # Dot reloads predecessors under the live incident claim. The old
            # fix receipt must be captured before persist_role_attempt replaces it.
            "_incident_handoff": {
                "schema": "incident-team-runtime/v1",
                "event_id": int(event_id),
                "role": role,
                "attempt_id": attempt_id,
                "previous_fix": (
                    role_handoff(fix_result, "fix")
                    if role == "fix" and fix_result
                    else None
                ),
            },
        }
    )
    if team_plan.get("execution_schema") == 2:
        # Only a durable incident plan can opt out of synchronous Para waiting.
        runtime["wait_for_para"] = False
        runtime["_incident_continuation"] = True
        if role in {"scout", "verify"}:
            runtime["report_only"] = True
            checks = (team_plan.get("independent_checks") or {}).get(role)
            if checks:
                runtime["independent_checks"] = checks
    if not str(runtime.get("project_root") or "").strip():
        roots = [
            str(os.environ.get(name) or "").strip()
            for name in (
                "MODSTORE_DUTY_PROJECT_ROOT",
                "XCMAX_MONOREPO_ROOT",
                "MODSTORE_REPO_ROOT",
                "MODSTORE_SELF_MAINTENANCE_PROJECT_ROOT",
            )
        ]
        for root in [*roots, "/opt/xcmax/current", "/root/XCMAX"]:
            if root and os.path.isdir(root):
                runtime["project_root"] = root
                break
    return runtime
