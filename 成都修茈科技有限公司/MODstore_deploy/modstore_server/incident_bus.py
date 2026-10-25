# mypy: disable-error-code="assignment"
"""incident-bus：事件入队并按 EmployeeTriggerBinding 派发员工任务。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List

from modstore_server.customer_issue_intake import _persist_incident
from modstore_server.employee_executor import (
    execute_employee_task as execute_employee_task,
)
from modstore_server.incident_dispatch import (
    _dispatch_incident_body as _dispatch_incident_body,
)
from modstore_server.incident_dispatch import (
    _dispatch_intake_routing_plan as _dispatch_intake_routing_plan,
)
from modstore_server.integrations.ops_action_handlers import EVENT_TYPES
from modstore_server.models import (
    CatalogItem,
    EmployeeTriggerBinding,
    IncidentClaim,
    IncidentEvent,
    User,
    get_session_factory,
)
from modstore_server.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS
from modstore_server.platform_llm_scope import platform_llm_scoped

logger = logging.getLogger(__name__)

_NON_DISPATCH_EVENT_TYPES = frozenset(
    {
        "employee.suggestion.created",
        "employee.suggestion.approved",
        "employee.suggestion.rejected",
        "employee.suggestion.dispatched",
        "employee.collab.thread_created",
        "employee.collab.message_created",
        "employee.brief_todo.created",
        "employee.brief_todo.dispatched",
        "employee.evolution.suggested",
        "employee.execution.recovery",
    }
)

# Workflow lifecycle signals are not generic incidents.  They may still drive
# an explicit ``EmployeeTriggerBinding`` (for example
# ``employee.task.done:intent-analyst`` -> ``employee-planner`` or
# ``ops.change_request.submitted`` -> ``change-request-auditor``), but must not
# enter the generic incident team or task market.  Treating healthy task,
# scheduler, backup, or planned change-request signals as incidents creates
# recursive scout/fix/verify teams and disposable workspaces for normal work.
_BINDING_ONLY_EVENT_TYPES = frozenset(
    {
        "backup.completed",
        "backup.dr_guard.cleared",
        "backup.ondemand_completed",
        "employee.task.assigned",
        "employee.task.done",
        "ops.change_request.submitted",
        "schedule.tick",
    }
)


def _parse_binding_event_key(stored: str) -> tuple[str, str]:
    """binding.event_type 可为 ``on_error`` 或 ``employee.task.done:upstream-id``（首段 `:` 后为上事件源过滤）。"""
    s = (stored or "").strip()
    if ":" in s:
        base, filt = s.split(":", 1)
        return base.strip(), filt.strip()
    return s, ""


def _incident_payload(row: IncidentEvent) -> Dict[str, Any]:
    """Reject damaged event data before routing or replacing durable evidence."""
    data = json.loads(str(row.payload_json or "{}"))
    if not isinstance(data, dict):
        raise ValueError(f"incident {row.id}: payload must be a JSON object")
    return data


def _fingerprint(payload: Dict[str, Any], source: str) -> str:
    raw = json.dumps({"s": source, "p": payload}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:64]


def _publish_stream_shadow(
    event_type: str,
    payload: Dict[str, Any],
    *,
    source: str,
    incident_id: int,
    event_fingerprint: str,
) -> None:
    """Best-effort dual-write into Redis Streams (for real-time subscribers)."""
    try:
        from modstore_server.eventing.redis_stream_bus import (
            publish_event as publish_stream_event,
        )

        out = publish_stream_event(
            event_type=event_type,
            payload=payload if isinstance(payload, dict) else {},
            source=source or "system",
            incident_id=int(incident_id or 0),
            fingerprint=event_fingerprint or "",
        )
        if not out.get("ok"):
            reason = str(out.get("reason") or out.get("error") or "").strip().lower()
            if reason and "disabled" not in reason and "unavailable" not in reason:
                logger.warning(
                    "incident_bus: redis stream publish failed event=%s incident_id=%s reason=%s",
                    event_type,
                    incident_id,
                    reason[:200],
                )
    except RECOVERABLE_ERRORS:
        logger.exception(
            "incident_bus: redis stream shadow publish crashed event=%s incident_id=%s",
            event_type,
            incident_id,
        )


def publish(
    event_type: str,
    payload: Dict[str, Any],
    *,
    source: str,
    fingerprint: str | None = None,
    dedupe_minutes: int = 10,
    inbox_key: str = "",
) -> bool:
    """发布事件；在指定分钟窗口内按 fingerprint 去重。返回是否新写入并派发。

    2026-05 起：未注册的 ``event_type`` 不再被静默丢弃，而是被记入
    ``incident.unknown``（并在 payload 中保留原始 ``event_type``），从而让
    监控/调度可以追溯并补登记。
    """
    raw_event_type = event_type
    if event_type not in EVENT_TYPES:
        logger.warning(
            "incident_bus: unknown event_type=%s (recording as incident.unknown for triage)",
            event_type,
        )
        payload = {**(payload or {}), "_unregistered_event_type": raw_event_type}
        event_type = "incident.unknown"
    fp = fingerprint or _fingerprint(payload, source)
    eid, created = _persist_incident(
        event_type, payload, source, fp, dedupe_minutes, inbox_key
    )
    if not created:
        if inbox_key:
            _schedule_incident(
                eid
            )  # Recover a crash between SQL commit and initial scheduling.
        return False
    _publish_stream_shadow(
        event_type,
        payload if isinstance(payload, dict) else {},
        source=source,
        incident_id=eid,
        event_fingerprint=fp,
    )
    if event_type == "employee.suggestion.created":
        try:
            from modstore_server.employee_autonomy_service import (
                ingest_suggestion_event_payload,
            )

            ingest_suggestion_event_payload(
                source_employee_id=source,
                payload=payload if isinstance(payload, dict) else {},
                auto_dispatch=True,
            )
        except RECOVERABLE_ERRORS:
            logger.exception("employee suggestion ingest failed")
    if event_type == "consistency_check.completed":
        try:
            if not bool((payload or {}).get("autofix_triggered")):
                from modstore_server.employee_autonomy_service import (
                    trigger_doc_autofix_from_report,
                )

                report = (
                    payload.get("report")
                    if isinstance(payload.get("report"), dict)
                    else None
                )
                if not isinstance(report, dict):
                    report = payload if isinstance(payload, dict) else {}
                trigger_doc_autofix_from_report(
                    report,
                    source=source or "consistency_checker",
                    source_ref=str((payload or {}).get("source_ref") or "")[:128],
                )
        except RECOVERABLE_ERRORS:
            logger.exception("consistency_check.completed autofix trigger failed")
    _schedule_incident(eid)
    return True


def _schedule_incident(event_id: int) -> None:
    def run():
        try:
            _dispatch_incident(event_id)
        except BOUNDARY_ERRORS:  # noqa: BLE001
            logger.exception("dispatch incident id=%s failed", event_id)

    if (os.environ.get("MODSTORE_INCIDENT_SYNC_DISPATCH") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        run()
    else:
        threading.Thread(
            target=run, daemon=True, name=f"incident-dispatch-{event_id}"
        ).start()


def publish_unified_incident(
    *,
    scope: str,
    summary: str,
    source: str,
    event_type: str = "on_error",
    payload: Dict[str, Any] | None = None,
    priority: int | None = None,
    fingerprint: str | None = None,
) -> bool:
    """Standard cross-repo incident entrypoint.

    FHD, MODstore and the public website should all publish here instead of
    creating separate loops. The payload keeps scope/priority so the employee
    task market can arbitrate one shared queue.
    """

    normalized_scope = (scope or "global").strip().lower() or "global"
    body = dict(payload or {})
    body.update(
        {
            "priority": priority,
            "scope": normalized_scope,
            "summary": str(summary or body.get("summary") or "")[:1000],
            "unified_incident_bus": True,
        }
    )
    if body.get("priority") is None:
        body.pop("priority", None)
    return publish(
        event_type,
        body,
        source=(source or normalized_scope or "unified_incident")[:64],
        fingerprint=fingerprint,
    )


def _admin_user_id() -> int:
    sf = get_session_factory()
    with sf() as session:
        u = (
            session.query(User)
            .filter(User.is_admin.is_(True))
            .order_by(User.id.asc())
            .first()
        )  # noqa: E712
        if u:
            return int(u.id)
        u2 = session.query(User).order_by(User.id.asc()).first()
        return int(u2.id) if u2 else 0


def _catalog_employee_ids(session) -> set[str]:
    rows = (
        session.query(CatalogItem.pkg_id)
        .filter(CatalogItem.artifact == "employee_pack")
        .all()
    )
    return {str(r[0]) for r in rows if r[0]}


def _incident_event_type(event_id: int) -> str:
    with get_session_factory()() as session:
        ev = session.get(IncidentEvent, int(event_id))
        if ev:
            _incident_payload(ev)
        return str(ev.event_type or "") if ev else ""


def _incident_employee_input(
    *,
    incident_payload: Dict[str, Any],
    event_type: str,
    source: str,
) -> Dict[str, Any]:
    """Build executor input for incident dispatch.

    Employees such as ``security-secrets-guard`` use ``shell_exec`` (high risk);
    without ``allow_high_risk_real_run`` the risk middleware records
    ``blocked_by_risk_gate`` and produces no audit output.
    """
    inp: Dict[str, Any] = {
        "incident": incident_payload,
        "event_type": event_type,
        "source": source,
        "allow_high_risk_real_run": True,
    }
    gate = (os.environ.get("MODSTORE_RISK_HIGH_GATE_TOKEN") or "").strip()
    if gate:
        inp["high_risk_gate_token"] = gate
    return inp


@platform_llm_scoped
def _dispatch_incident(event_id: int) -> None:
    from modstore_server.node_coordinator import (
        IncidentClaimLost,
        assert_incident_claim,
        incident_claim_scope,
    )

    try:
        with incident_claim_scope(event_id):
            with get_session_factory()() as session:
                assert_incident_claim(event_id, session=session)
                row = session.get(IncidentClaim, int(event_id), populate_existing=True)
                if row is None:
                    raise IncidentClaimLost("claim row unavailable")
                reconcile = str(row.dispatch_state) in {
                    "dispatching",
                    "unknown",
                    "completed",
                }
                if str(row.dispatch_state) in {"dispatching", "unknown"}:
                    row.dispatch_state = "unknown"
                    row.last_error = "interrupted dispatch; reconcile original execution before any replay"
                elif not reconcile:
                    row.dispatch_state = "dispatching"
                session.commit()
            if reconcile:
                from modstore_server.incident_team_completion import (
                    reconcile_pending_teams,
                )

                reconcile_pending_teams(event_id=int(event_id))
                return
            try:
                _dispatch_incident_body(event_id)
            except BOUNDARY_ERRORS:  # noqa: BLE001
                with get_session_factory()() as session:
                    assert_incident_claim(event_id, session=session)
                    row = session.get(
                        IncidentClaim, int(event_id), populate_existing=True
                    )
                    if row is None:
                        raise IncidentClaimLost("claim row unavailable")
                    row.dispatch_state, row.last_error = (
                        "unknown",
                        "dispatch raised; original attempt requires reconciliation",
                    )
                    session.commit()
                raise
            with get_session_factory()() as session:
                assert_incident_claim(event_id, session=session)
                row = session.get(IncidentClaim, int(event_id), populate_existing=True)
                if row is None:
                    raise IncidentClaimLost("claim row unavailable")
                row.dispatch_state, row.last_error = "completed", ""
                session.commit()
    except IncidentClaimLost:
        logger.info(
            "incident_bus: no live claim event_id=%s; dispatch stopped", event_id
        )


def _extract_routing_plan(exec_result: Any) -> List[Dict[str, Any]]:
    """Pull intake-dispatcher ``routing_plan`` out of execute_employee_task result."""

    if not isinstance(exec_result, dict):
        return []
    result = exec_result.get("result")
    if not isinstance(result, dict):
        return []
    out = result.get("output")
    if isinstance(out, dict) and isinstance(out.get("routing_plan"), list):
        return [row for row in out["routing_plan"] if isinstance(row, dict)]
    outputs = result.get("outputs")
    if isinstance(outputs, list):
        for item in outputs:
            if not isinstance(item, dict):
                continue
            nested = item.get("output")
            if isinstance(nested, dict) and isinstance(
                nested.get("routing_plan"), list
            ):
                return [row for row in nested["routing_plan"] if isinstance(row, dict)]
    return []


def _routing_plan_owners(exec_result: Any) -> set[str]:
    return {
        str(row.get("proposed_owner") or "").strip()
        for row in _extract_routing_plan(exec_result)
        if str(row.get("proposed_owner") or "").strip()
    }


def sync_employee_trigger_bindings_from_yuangon(yuangon_dir: Path) -> int:
    """扫描 ``yuangon/**/employee.yaml``，按 ``triggers`` upsert :class:`EmployeeTriggerBinding`。"""
    try:
        import yaml
    except ImportError:
        return 0

    ydir = Path(yuangon_dir).resolve()
    if not ydir.is_dir():
        return 0
    yaml_keys = ("on_error", "on_quality_fail", "on_coverage_miss")
    n = 0
    sf = get_session_factory()
    with sf() as session:
        for f in sorted(ydir.glob("**/employee.yaml")):
            try:
                data = yaml.safe_load(f.read_text(encoding="utf-8"))
            except BOUNDARY_ERRORS:  # noqa: BLE001
                continue
            if not isinstance(data, dict):
                continue
            pack_id = str(data.get("id") or "").strip()
            if not pack_id:
                continue
            trig = data.get("triggers")
            if not isinstance(trig, dict):
                continue
            for yk in yaml_keys:
                if yk not in EVENT_TYPES:
                    continue
                if not bool(trig.get(yk)):
                    continue
                row = (
                    session.query(EmployeeTriggerBinding)
                    .filter(
                        EmployeeTriggerBinding.employee_id == pack_id,
                        EmployeeTriggerBinding.event_type == yk,
                    )
                    .first()
                )
                if row:
                    row.is_active = True
                else:
                    session.add(
                        EmployeeTriggerBinding(
                            employee_id=pack_id,
                            event_type=yk,
                            is_active=True,
                        )
                    )
                n += 1

            subs = trig.get("subscribes")
            if isinstance(subs, list):
                for raw in subs:
                    ev_key = str(raw or "").strip()
                    if not ev_key:
                        continue
                    base, _f = _parse_binding_event_key(ev_key)
                    if base not in EVENT_TYPES:
                        continue
                    row = (
                        session.query(EmployeeTriggerBinding)
                        .filter(
                            EmployeeTriggerBinding.employee_id == pack_id,
                            EmployeeTriggerBinding.event_type == ev_key,
                        )
                        .first()
                    )
                    if row:
                        row.is_active = True
                    else:
                        session.add(
                            EmployeeTriggerBinding(
                                employee_id=pack_id,
                                event_type=ev_key,
                                is_active=True,
                            )
                        )
                    n += 1
        session.commit()
    return n
