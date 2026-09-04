# mypy: disable-error-code="arg-type, assignment"
"""Employee binding and fallback dispatch implementation for incident events."""

from __future__ import annotations

import json
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
            base, source_filter = facade._parse_binding_event_key(
                str(binding.event_type or "")
            )
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
            owner_brief = (
                f"{brief} | route={owner} request_id={row.get('request_id') or ''}"
            )[:500]
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

    if not binding_only and (
        os.environ.get("MODSTORE_UNIFIED_ORCHESTRATOR_ENABLED", "1") or ""
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        try:
            from modstore_server.unified_autonomy_orchestrator import (
                orchestrate_incident,
            )

            orchestration = orchestrate_incident(event_id)
            if not orchestration.get("should_dispatch", True):
                logger.info(
                    "incident_bus: unified orchestrator parked event_id=%s", event_id
                )
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
            from modstore_server.incident_team_orchestrator import (
                dispatch_incident_team,
            )

            team = dispatch_incident_team(event_id)
            if team.get("claimed"):
                logger.info(
                    "incident_bus: team claimed event_id=%s ok=%s",
                    event_id,
                    team.get("ok"),
                )
                # 客服工单：团队抢单后仍走 binding，让 intake-dispatcher /
                # user-customer-service-officer 按既有订阅接单（跳过 market 防双派）。
                if (
                    event_type_pre == "ops.intake.customer_ticket"
                    or reviewed_duty_binding
                ):
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
                "incident team failed event_id=%s; fallback market", event_id
            )

    if not binding_only and (
        os.environ.get("MODSTORE_EMPLOYEE_TASK_MARKET_ENABLED", "1") or ""
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        try:
            from modstore_server.employee_task_market import (
                dispatch_incident_via_market,
            )

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
        logger.warning(
            "incident_bus: no user in DB, skip dispatch event_id=%s", event_id
        )
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
            .order_by(
                EmployeeTriggerBinding.priority.asc(), EmployeeTriggerBinding.id.asc()
            )
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
                from modstore_server.duty_workforce_contracts import (
                    matching_duty_event_contract,
                )

                if not matching_duty_event_contract(
                    eid_sub,
                    str(ev.event_type or ""),
                    str(ev.source or ""),
                ):
                    continue
            binding_list.append((int(b.priority or 5), eid_sub))
        binding_ids = [eid for _, eid in sorted(binding_list)]
        catalog_ids = _catalog_employee_ids(session)
        try:
            payload = json.loads(ev.payload_json or "{}")
        except json.JSONDecodeError:
            payload = {}
        event_type = str(ev.event_type or "")
        source = str(ev.source or "")
        summary = str(payload.get("summary") or source or "incident")
        brief = f"[{event_type}] {summary}"[:500]

    dispatched = 0
    already_ran: set[str] = set()
    for eid_emp in binding_ids:
        if not eid_emp or eid_emp not in catalog_ids:
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
            exec_result = execute_employee_task(
                eid_emp,
                brief,
                duty_input
                or _incident_employee_input(
                    incident_payload=payload,
                    event_type=event_type,
                    source=source,
                ),
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
