# mypy: disable-error-code="arg-type, assignment"
"""Employee binding and fallback dispatch implementation for incident events."""

from __future__ import annotations

import os
from typing import Any, Dict, List

from modstore_server import incident_bus as facade
from modstore_server.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS


def _has_reviewed_duty_binding(event_id: int) -> bool:
    """Return whether this event has an active, unattended reviewed duty."""

    from modstore_server.duty_workforce_contracts import matching_duty_event_contract

    sf = facade.get_session_factory()
    with sf() as session:
        event = session.get(facade.IncidentEvent, event_id)
        if event is None:
            return False
        bindings = (
            session.query(facade.EmployeeTriggerBinding)
            .filter(facade.EmployeeTriggerBinding.is_active.is_(True))
            .all()
        )
        for binding in bindings:
            base, source_filter = facade._parse_binding_event_key(str(binding.event_type or ""))
            if base != str(event.event_type or ""):
                continue
            if source_filter and source_filter != str(event.source or ""):
                continue
            if matching_duty_event_contract(
                str(binding.employee_id or ""),
                str(event.event_type or ""),
                str(event.source or ""),
            ):
                return True
    return False


def _dispatch_intake_routing_plan(
    exec_result: Any,
    *,
    incident_payload: Dict[str, Any],
    event_type: str,
    source: str,
    admin_id: int,
    catalog_ids: set[str],
    skip_ids: set[str],
    brief: str,
) -> int:
    """Execute ``proposed_owner`` employees from intake routing_plan (real side effects)."""

    _extract_routing_plan = facade._extract_routing_plan
    execute_employee_task = facade.execute_employee_task
    _incident_employee_input = facade._incident_employee_input
    logger = facade.logger

    from modstore_server.duty_workforce_contracts import duty_event_execution_input

    # A persisted team already owns repair planning. A subscriber's routing
    # suggestion must not create a second set of side effects for that event.
    if _claimed_team_members(incident_payload):
        return 0
    extra = 0
    for row in _extract_routing_plan(exec_result):
        owner = str(row.get("proposed_owner") or "").strip()
        if not owner or owner in skip_ids or owner not in catalog_ids:
            continue
        try:
            duty_input = duty_event_execution_input(
                owner,
                event_type=event_type,
                source=source,
                incident=incident_payload,
            )
            owner_brief = (f"{brief} | route={owner} request_id={row.get('request_id') or ''}")[
                :500
            ]
            execute_employee_task(
                owner,
                owner_brief,
                duty_input
                or _incident_employee_input(
                    incident_payload=incident_payload,
                    event_type=event_type,
                    source=source,
                ),
                user_id=0 if duty_input else admin_id,
            )
            extra += 1
            skip_ids.add(owner)
            logger.info("incident_bus: intake routing_plan dispatched")
        except BOUNDARY_ERRORS:  # noqa: BLE001
            logger.warning("incident_bus: intake routing_plan dispatch failed")
    return extra


def _claimed_team_members(payload: Dict[str, Any]) -> set[str]:
    claim = payload.get("_team_claim")
    rows = claim.get("team") if isinstance(claim, dict) else None
    return {
        str(row["employee_id"])
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, dict)
        and row.get("employee_id")
        and row.get("role") in {"scout", "fix", "verify"}
    }


def _dispatch_incident_body(event_id: int) -> None:
    _incident_event_type = facade._incident_event_type
    _NON_DISPATCH_EVENT_TYPES = facade._NON_DISPATCH_EVENT_TYPES
    _BINDING_ONLY_EVENT_TYPES = facade._BINDING_ONLY_EVENT_TYPES
    logger = facade.logger
    get_session_factory = facade.get_session_factory
    _admin_user_id = facade._admin_user_id
    IncidentEvent = facade.IncidentEvent
    EmployeeTriggerBinding = facade.EmployeeTriggerBinding
    _parse_binding_event_key = facade._parse_binding_event_key
    _catalog_employee_ids = facade._catalog_employee_ids
    execute_employee_task = facade.execute_employee_task
    _incident_employee_input = facade._incident_employee_input
    _dispatch_intake_routing_plan = facade._dispatch_intake_routing_plan
    _routing_plan_owners = facade._routing_plan_owners

    event_type_pre = _incident_event_type(event_id)
    if event_type_pre in _NON_DISPATCH_EVENT_TYPES:
        logger.info(
            "incident_bus: lifecycle event_id=%s event_type=%s recorded without employee dispatch",
            event_id,
            event_type_pre,
        )
        return

    binding_only = event_type_pre in _BINDING_ONLY_EVENT_TYPES
    reviewed_duty_binding = _has_reviewed_duty_binding(event_id)
    reviewed_bindings_only = False
    team_claimed = False

    if not binding_only and (
        os.environ.get("MODSTORE_UNIFIED_ORCHESTRATOR_ENABLED", "1") or ""
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        try:
            from modstore_server.unified_autonomy_orchestrator import orchestrate_incident

            orchestration = orchestrate_incident(event_id)
            if not orchestration.get("should_dispatch", True):
                logger.info("incident_bus: unified orchestrator parked event_id=%s", event_id)
                return
        except RECOVERABLE_ERRORS:
            logger.warning(
                "unified incident orchestrator failed event_id=%s; fallback dispatch",
                event_id,
            )

    if not binding_only and (
        os.environ.get("MODSTORE_INCIDENT_TEAM_ENABLED", "1") or ""
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        try:
            from modstore_server.incident_team_orchestrator import dispatch_incident_team

            team = dispatch_incident_team(event_id)
            if team.get("requires_reconciliation") or team.get("outcome") == "unknown":
                logger.warning(
                    "incident team requires original-attempt readback event_id=%s",
                    event_id,
                )
                return
            if team.get("claimed"):
                team_claimed = True
                logger.info(
                    "incident_bus: team claimed event_id=%s ok=%s",
                    event_id,
                    team.get("ok"),
                )
                if team.get("reason") in {
                    "incident_scope_mismatch",
                    "shared_repair_reused",
                    "incident_not_active",
                }:
                    return
                # 客服订阅只能跟进原团队；终止或缺少持久计划的事件不再分派。
                if event_type_pre == "ops.intake.customer_ticket" or reviewed_duty_binding:
                    binding_only = True
                    reviewed_bindings_only = reviewed_duty_binding
                else:
                    return
            else:
                logger.info(
                    "incident_bus: team did not claim event_id=%s; fallback market",
                    event_id,
                )
        except RECOVERABLE_ERRORS:
            logger.warning(
                "incident team outcome unknown event_id=%s; stop fallback for readback",
                event_id,
            )
            return

    if not binding_only and (
        os.environ.get("MODSTORE_EMPLOYEE_TASK_MARKET_ENABLED", "1") or ""
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        try:
            from modstore_server.employee_task_market import dispatch_incident_via_market

            market = dispatch_incident_via_market(event_id)
            if market.get("ok") and market.get("claimed"):
                logger.info(
                    "incident_bus: market claimed event_id=%s score=%s",
                    event_id,
                    (
                        (market.get("winner") or {}).get("score")
                        if isinstance(market.get("winner"), dict)
                        else None
                    ),
                )
                if reviewed_duty_binding:
                    reviewed_bindings_only = True
                else:
                    return
            logger.info(
                "incident_bus: market did not claim event_id=%s; fallback binding dispatch",
                event_id,
            )
        except RECOVERABLE_ERRORS:
            logger.warning(
                "incident task market failed event_id=%s; fallback binding dispatch",
                event_id,
            )

    sf = get_session_factory()
    admin_id = _admin_user_id()
    if admin_id <= 0:
        logger.warning("incident_bus: no user in DB, skip dispatch event_id=%s", event_id)
        return

    binding_ids: List[str] = []
    catalog_ids: set[str] = set()
    payload: Dict[str, Any] = {}
    event_type = ""
    source = ""
    brief = ""

    # List of (priority, employee_id) tuples for ordered dispatch
    binding_list: List[tuple] = []
    with sf() as session:
        ev = session.query(IncidentEvent).filter(IncidentEvent.id == event_id).first()
        if not ev:
            return
        for b in (
            session.query(EmployeeTriggerBinding)
            .filter(EmployeeTriggerBinding.is_active.is_(True))
            .order_by(EmployeeTriggerBinding.priority.asc(), EmployeeTriggerBinding.id.asc())
            .all()
        ):
            eid_sub = str(b.employee_id or "").strip()
            if not eid_sub:
                continue
            base, filt = _parse_binding_event_key(str(b.event_type or ""))
            if base != ev.event_type:
                continue
            if filt and filt != str(ev.source or ""):
                continue
            if reviewed_bindings_only:
                from modstore_server.duty_workforce_contracts import matching_duty_event_contract

                if not matching_duty_event_contract(
                    eid_sub,
                    str(ev.event_type or ""),
                    str(ev.source or ""),
                ):
                    continue
            binding_list.append((int(b.priority or 5), eid_sub))
        binding_ids = [eid for _, eid in sorted(binding_list)]
        catalog_ids = _catalog_employee_ids(session)
        payload = facade._incident_payload(ev)
        event_type = str(ev.event_type or "")
        source = str(ev.source or "")
        summary = str(payload.get("summary") or source or "incident")
        brief = f"[{event_type}] {summary}"[:500]

    dispatched = 0
    team_members = (
        _claimed_team_members(payload) if event_type == "ops.intake.customer_ticket" else set()
    )
    if event_type == "ops.intake.customer_ticket" and team_claimed and not team_members:
        logger.warning(
            "incident claimed without persisted team event_id=%s; stop fallback", event_id
        )
        return
    already_ran: set[str] = set(team_members)
    for eid_emp in binding_ids:
        if not eid_emp or eid_emp not in catalog_ids:
            continue
        if team_members and (eid_emp == "intake-dispatcher" or eid_emp in team_members):
            continue
        try:
            from modstore_server.duty_workforce_contracts import (
                duty_event_execution_input,
                matching_duty_event_contract,
            )

            reviewed_contract = matching_duty_event_contract(
                eid_emp,
                event_type,
                source,
            )
            duty_input = duty_event_execution_input(
                eid_emp,
                event_type=event_type,
                source=source,
                incident=payload,
            )
            if reviewed_contract and duty_input.get("_duty_input_ready") is False:
                logger.info("incident_bus: reviewed duty input unavailable")
                continue
            duty_input.pop("_duty_input_ready", None)
            employee_input = duty_input or _incident_employee_input(
                incident_payload=payload,
                event_type=event_type,
                source=source,
            )
            if team_members:
                employee_input["reuse_incident_team_plan"] = True
            exec_result = execute_employee_task(
                eid_emp,
                brief
                + ("；沿用原团队，只跟进客户进度与阻塞，不另建修复计划。" if team_members else ""),
                employee_input,
                user_id=0 if duty_input else admin_id,
            )
            dispatched += 1
            already_ran.add(eid_emp)
            # intake-dispatcher: consume routing_plan → real downstream dispatch
            if eid_emp == "intake-dispatcher":
                extra = _dispatch_intake_routing_plan(
                    exec_result,
                    incident_payload=payload,
                    event_type=event_type,
                    source=source,
                    admin_id=admin_id,
                    catalog_ids=catalog_ids,
                    skip_ids=already_ran,
                    brief=brief,
                )
                dispatched += int(extra)
                already_ran.update(_routing_plan_owners(exec_result))
        except BOUNDARY_ERRORS:  # noqa: BLE001
            logger.warning("incident dispatch employee execution failed")

    with sf() as session:
        ev2 = session.query(IncidentEvent).filter(IncidentEvent.id == event_id).first()
        if ev2:
            # team/market 可能已写过 dispatched_count；binding 追加而非覆盖
            ev2.dispatched_count = int(ev2.dispatched_count or 0) + int(dispatched)
            session.commit()
