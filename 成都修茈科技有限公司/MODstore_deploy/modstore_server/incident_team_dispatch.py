# mypy: disable-error-code="arg-type, assignment, union-attr"
"""Primary dynamic-team incident dispatch workflow."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from modstore_server import incident_team_orchestrator as facade
from modstore_server.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS


def dispatch_incident_team(event_id: int) -> Dict[str, Any]:
    _env_bool = facade._env_bool
    build_incident_team = facade.build_incident_team
    get_session_factory = facade.get_session_factory
    IncidentEvent = facade.IncidentEvent
    _payload = facade._payload
    _admin_user_id = facade._admin_user_id
    _task_for_role = facade._task_for_role
    _execute_employee_task_with_timeout = facade._execute_employee_task_with_timeout
    _role_timeout_seconds = facade._role_timeout_seconds
    _HANDLER_FAILED_FOLLOWUP_ENV = facade._HANDLER_FAILED_FOLLOWUP_ENV
    _follow_up_handler_failures = facade._follow_up_handler_failures
    logger = facade.logger

    if not _env_bool("MODSTORE_INCIDENT_TEAM_ENABLED", True):
        return {"claimed": False, "ok": False, "reason": "incident_team_disabled"}
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
        from modstore_server.duty_workforce_contracts import duty_event_execution_input

        duty_input = duty_event_execution_input(
            employee_id,
            event_type=event_type,
            source=source,
            incident=payload,
        )
        runtime_input = duty_input or {
            "allow_high_risk_real_run": role in {"fix", "verify"},
            "allow_medium_risk": True,
            "incident": payload,
            "source": source,
            "suppress_lifecycle_events": True,
            "unified_incident_bus": True,
        }
        # agent/直接分析岗需要仓库根；复用现有 env，避免「缺 project_root」空转失败
        if not str(runtime_input.get("project_root") or "").strip():
            candidates = [
                str(os.environ.get("MODSTORE_DUTY_PROJECT_ROOT") or "").strip(),
                str(os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip(),
                str(os.environ.get("MODSTORE_REPO_ROOT") or "").strip(),
                str(os.environ.get("MODSTORE_SELF_MAINTENANCE_PROJECT_ROOT") or "").strip(),
                "/opt/xcmax/current",
                "/root/XCMAX",
            ]
            for root in candidates:
                if root and os.path.isdir(root):
                    runtime_input["project_root"] = root
                    break
        runtime_input.update(
            {
                "incident_team": team_plan,
                "model_route": route,
                "release_recovery": recovery,
                "role": role,
                # 系统事故小组：允许 monorepo project_root（含写），勿落入租户 workspace 校验
                "_trusted_incident_team_execution": True,
                "unified_incident_bus": True,
                "event_type": str(event_type or ""),
            }
        )
        # 事故小组一律系统身份；用 admin uid 会把 monorepo 根误判为越权路径
        result = _execute_employee_task_with_timeout(
            employee_id,
            task,
            runtime_input,
            user_id=0,
            bench_llm_override=bench_override,
            timeout_seconds=_role_timeout_seconds(),
        )
        status = str(result.get("status") or result.get("execution_status") or "").strip().lower()
        risk_blocked = (
            status == "blocked_by_risk_gate"
            or bool(result.get("blocked_by_risk_gate"))
            or str(result.get("reason") or "").strip().lower() == "blocked_by_risk_gate"
        )
        row = {
            "employee_id": employee_id,
            "ok": (
                not risk_blocked
                and not bool(result.get("handler_failed"))
                and not bool(result.get("error"))
                and status not in {"handler_failed", "orchestrator_failed", "failed"}
            ),
            "role": role,
            "route": route,
            "result": result,
            "status": status or ("blocked_by_risk_gate" if risk_blocked else "unknown"),
        }
        results.append(row)
        if role == "scout":
            scout_result = row
        elif role == "fix":
            fix_result = row

    ok = bool(results) and all(bool(row.get("ok")) for row in results if row.get("role") != "fix")

    failed_roles = [
        str(row.get("role") or "")
        for row in results
        if not bool(row.get("ok"))
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

    # ---- 闭环：handler_failed → 按 failure_kind 自动 follow-up ----
    # 旧版：handler_failed 仅写 _team_claim 后 return，184 个 handler_failed 全靠人工接手。
    # 新版：transient 自动重试 1 次；quota 标记 quota_blocked 不重试（避免 403 死亡螺旋）；
    # prompt 走 fallback 到 task market（让 self-evolution 重写 prompt）。
    follow_ups: List[Dict[str, Any]] = []
    if _env_bool(_HANDLER_FAILED_FOLLOWUP_ENV, True):
        follow_ups = _follow_up_handler_failures(
            event_id=event_id,
            results=results,
            team_plan=team_plan,
            payload=payload,
            event_type=event_type,
            source=source,
            uid=uid,
        )

    slim_rows = [{k: v for k, v in row.items() if k != "result"} for row in results]
    cs_progress: Dict[str, Any] = {}
    with sf() as session:
        ev2 = session.get(IncidentEvent, int(event_id))
        if ev2 is not None:
            updated = _payload(ev2)
            updated["_team_claim"] = {
                "claimed_at": datetime.now(UTC).isoformat(),
                "ok": ok,
                "recovery": recovery,
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
            ev2.payload_json = json.dumps(updated, ensure_ascii=False)[:8000]
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
