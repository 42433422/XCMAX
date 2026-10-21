# mypy: disable-error-code="arg-type, assignment, union-attr"
"""Primary dynamic-team incident dispatch workflow."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from modstore_server import incident_team_orchestrator as facade
from modstore_server.customer_issue_delivery_contract import (
    execution_pending,
    execution_succeeded,
    team_succeeded,
)
from modstore_server.incident_team_completion import persist_role_attempt
from modstore_server.incident_team_handler_digest import handler_output_digest
from modstore_server.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS


def dispatch_incident_team(event_id: int) -> Dict[str, Any]:
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


def _dispatch_incident_team_once(event_id: int) -> Dict[str, Any]:
    _env_bool = facade._env_bool
    build_incident_team = facade.build_incident_team
    get_session_factory = facade.get_session_factory
    IncidentEvent = facade.IncidentEvent
    _payload = facade._payload
    _admin_user_id = facade._admin_user_id
    _task_for_role = facade._task_for_role
    _execute_employee_task_with_timeout = facade._execute_employee_task_with_timeout
    _role_timeout_seconds = facade._role_timeout_seconds
    _is_role_timeout = facade._is_role_timeout
    _HANDLER_FAILED_FOLLOWUP_ENV = facade._HANDLER_FAILED_FOLLOWUP_ENV
    _follow_up_handler_failures = facade._follow_up_handler_failures
    logger = facade.logger

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
                str(payload.get("source") or source or "").strip().lower() == "customer_ticket"
                or event_type == "ops.intake.customer_ticket"
                or str(payload.get("ticket_no") or "").startswith("CS")
            )
            if has_team_claim or not customer_ticket:
                return {
                    "claimed": False,
                    "ok": True,
                    "reason": "incident_already_dispatched",
                }
        uid = _admin_user_id(session)

    recovery: Dict[str, Any] = {}
    try:
        from modstore_server.release_recovery_orchestrator import maybe_execute_recovery

        recovery = maybe_execute_recovery(event_id=event_id, event_type=event_type, payload=payload)
    except RECOVERABLE_ERRORS as exc:
        recovery = {"ok": False, "error": str(exc)[:500]}

    results: List[Dict[str, Any]] = []
    scout_result: Optional[Dict[str, Any]] = None
    fix_result: Optional[Dict[str, Any]] = None
    for member in team:
        role = str(member.get("role") or "")
        employee_id = str(member.get("employee_id") or "")
        if not role or not employee_id:
            continue
        if (
            role == "verify"
            and fix_result is not None
            and (not fix_result.get("ok") or _is_role_timeout(fix_result))
        ):
            # 修复岗未结束就验收必然假 FAIL（“无代码改动”）；记跳过，整单仍按失败闭环。
            results.append(
                {
                    "employee_id": employee_id,
                    "handler_outputs": handler_output_digest({}),
                    "ok": False,
                    "role": role,
                    "status": "skipped_fix_unfinished",
                    "verified_fix_attempt_id": "",
                    "result": {},
                }
            )
            continue
        route: Dict[str, Any] = {}
        bench_override = None
        try:
            from modstore_server.incident_model_router import (
                bench_override_for_route,
                route_for_incident,
            )

            route = route_for_incident(event_type=event_type, payload=payload, role=role)
            bench_override = bench_override_for_route(route)
        except RECOVERABLE_ERRORS:
            route = {"provider": "auto", "model": "auto", "reason": "router_error"}
        task = _task_for_role(
            code_ownership=(
                team_plan.get("code_owner_match")
                if role == "fix" and isinstance(team_plan.get("code_owner_match"), dict)
                else None
            ),
            event_type=event_type,
            fix_result=fix_result,
            payload=payload,
            role=role,
            scout_result=scout_result,
        )
        attempt_id = uuid.uuid4().hex
        runtime_input = member_runtime_input(
            employee_id=employee_id,
            role=role,
            event_id=event_id,
            team_plan=team_plan,
            payload=payload,
            event_type=event_type,
            source=source,
            route=route,
            attempt_id=attempt_id,
            fix_result=fix_result,
        )
        runtime_input["release_recovery"] = recovery
        intent = {
            "role": role,
            "employee_id": employee_id,
            "attempt_id": attempt_id,
            "event_id": int(event_id),
            "tenant_id": runtime_input.get("tenant_id"),
            "ok": False,
            "status": "dispatching",
            "outcome": "unknown",
            "verified_fix_attempt_id": (
                str((fix_result or {}).get("attempt_id") or "") if role == "verify" else ""
            ),
        }
        persist_role_attempt(event_id, intent)
        # 事故小组一律系统身份；用 admin uid 会把 monorepo 根误判为越权路径
        result = _execute_employee_task_with_timeout(
            employee_id,
            task,
            runtime_input,
            user_id=0,
            bench_llm_override=bench_override,
            timeout_seconds=_role_timeout_seconds(role),
        )
        result = {**result, "attempt_id": attempt_id, "event_id": int(event_id)}
        status = str(result.get("status") or result.get("execution_status") or "").strip().lower()
        risk_blocked = (
            status == "blocked_by_risk_gate"
            or bool(result.get("blocked_by_risk_gate"))
            or str(result.get("reason") or "").strip().lower() == "blocked_by_risk_gate"
        )
        succeeded = not risk_blocked and execution_succeeded(result)
        pending = not risk_blocked and execution_pending(result)
        row = {
            "employee_id": employee_id,
            "attempt_id": attempt_id,
            "event_id": int(event_id),
            "tenant_id": runtime_input.get("tenant_id"),
            "verified_fix_attempt_id": intent["verified_fix_attempt_id"],
            "handler_outputs": handler_output_digest(result),
            "ok": succeeded,
            "role": role,
            "route": route,
            "result": result,
            "status": "pending" if pending else status or ("completed" if succeeded else "failed"),
        }
        persist_role_attempt(
            event_id,
            {key: value for key, value in row.items() if key != "result"},
            expected_attempt=attempt_id,
        )
        results.append(row)
        if role == "scout":
            scout_result = row
        elif role == "fix":
            fix_result = row

    ok = team_succeeded(results)

    failed_roles = [
        str(row.get("role") or "")
        for row in results
        if (
            not bool(row.get("ok"))
            and row.get("status")
            not in {"pending", "skipped_fix_unfinished", "verification_invalidated"}
        )
        or bool((row.get("result") or {}).get("handler_failed"))
        or str(row.get("status") or "").strip().lower() == "handler_failed"
    ]
    handler_failed_count = len(failed_roles)
    if handler_failed_count:
        logger.warning(
            "incident_team: handler_failed_by_event_type event_type=%s event_id=%s "
            "handler_failed_count=%s roles=%s",
            event_type,
            event_id,
            handler_failed_count,
            failed_roles,
        )

    # ---- 失败闭环：分类 → 模型降级 / 代码回喂再修 / 环境退避重试，到上限升级终极员工 ----
    follow_ups: List[Dict[str, Any]] = []
    if _env_bool(_HANDLER_FAILED_FOLLOWUP_ENV, True):
        follow_ups = _follow_up_handler_failures(
            event_id=event_id,
            results=[
                row
                for row in results
                if row.get("status")
                not in {"pending", "skipped_fix_unfinished", "verification_invalidated"}
            ],
            team_plan=team_plan,
            payload=payload,
            event_type=event_type,
            source=source,
            uid=uid,
        )
        ok = team_succeeded(results)

    slim_rows = [{k: v for k, v in row.items() if k != "result"} for row in results]
    cs_progress: Dict[str, Any] = {}
    with sf() as session:
        ev2 = session.get(IncidentEvent, int(event_id))
        if ev2 is not None:
            from modstore_server.node_coordinator import assert_incident_claim

            assert_incident_claim(event_id, session=session)
            updated = _payload(ev2)
            latest_rows = (updated.get("_team_claim") or {}).get("team") or []
            for index, row in enumerate(slim_rows):
                latest = next(
                    (
                        item
                        for item in latest_rows
                        if item.get("role") == row.get("role")
                        and item.get("attempt_id") == row.get("attempt_id")
                    ),
                    None,
                )
                if (
                    latest
                    and latest.get("status") in {"completed", "failed"}
                    and row.get("status") == "pending"
                ):
                    slim_rows[index] = latest
            ok = team_succeeded(slim_rows)
            updated["_team_claim"] = {
                "claimed_at": datetime.now(UTC).isoformat(),
                "ok": ok,
                "recovery": recovery,
                "plan": team_plan,
                "team": slim_rows,
                "follow_ups": follow_ups,
                "handler_failed_count": handler_failed_count,
                "handler_failed_roles": failed_roles,
                "event_type": str(event_type or ""),
            }
            # 客服工单：复用现有 CS 消息/action，把员工进展回写到用户可见工单
            try:
                ticket_id = int(payload.get("ticket_id") or 0)
            except (TypeError, ValueError):
                ticket_id = 0
            source_hint = str(payload.get("source") or source or "").strip().lower()
            if ticket_id > 0 and (
                source_hint == "customer_ticket"
                or event_type == "ops.intake.customer_ticket"
                or str(payload.get("ticket_no") or "").startswith("CS")
            ):
                try:
                    from modstore_server.customer_service_orchestrator import (
                        apply_customer_ticket_incident_progress,
                    )

                    cs_progress = apply_customer_ticket_incident_progress(
                        session,
                        ticket_id=ticket_id,
                        event_id=int(event_id),
                        team_ok=bool(ok),
                        team_rows=slim_rows,
                        summary_hint=str(payload.get("summary") or "")[:200],
                    )
                    from modstore_server.customer_issue_shared_release import (
                        record_worker_repair,
                    )
                    from modstore_server.models_cs import CustomerServiceTicket

                    ticket = session.get(CustomerServiceTicket, ticket_id)
                    if ticket is not None and int(ticket.user_id) == int(
                        payload.get("user_id") or 0
                    ):
                        record_worker_repair(session, ticket, int(event_id), results)
                        if follow_ups:
                            _write_repair_loop(session, ticket, int(event_id), follow_ups)
                    updated["_cs_progress"] = {
                        k: cs_progress.get(k)
                        for k in (
                            "ok",
                            "lifecycle_stage",
                            "lifecycle_label",
                            "message_id",
                            "team_ok",
                        )
                    }
                except BOUNDARY_ERRORS as exc:  # noqa: BLE001
                    logger.exception(
                        "incident_team: CS ticket progress writeback failed event_id=%s ticket_id=%s",
                        event_id,
                        ticket_id,
                    )
                    cs_progress = {"ok": False, "error": str(exc)[:300]}
                    updated["_cs_progress"] = cs_progress
            ev2.payload_json = json.dumps(updated, ensure_ascii=False)
            ev2.dispatched_count = int(ev2.dispatched_count or 0) + 1
            session.commit()
    return {
        "claimed": True,
        "event_id": int(event_id),
        "ok": ok,
        "recovery": recovery,
        "results": results,
        "team": team_plan,
        "follow_ups": follow_ups,
        "cs_progress": cs_progress,
    }


def _write_repair_loop(session, ticket, event_id: int, follow_ups: List[Dict[str, Any]]) -> None:
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
        event_type="incident.repair_loop_escalated" if escalated else "incident.repair_loop",
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
        }
    )
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
