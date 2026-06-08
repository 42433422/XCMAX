"""incident-bus：事件入队并按 EmployeeTriggerBinding 派发员工任务。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from modstore_server.employee_executor import execute_employee_task
from modstore_server.integrations.ops_action_handlers import EVENT_TYPES
from modstore_server.models import (
    CatalogItem,
    EmployeeTriggerBinding,
    IncidentEvent,
    User,
    get_session_factory,
)

logger = logging.getLogger(__name__)


def _parse_binding_event_key(stored: str) -> tuple[str, str]:
    """binding.event_type 可为 ``on_error`` 或 ``employee.task.done:upstream-id``（首段 `:` 后为上事件源过滤）。"""
    s = (stored or "").strip()
    if ":" in s:
        base, filt = s.split(":", 1)
        return base.strip(), filt.strip()
    return s, ""


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
        from modstore_server.eventing.redis_stream_bus import publish_event as publish_stream_event

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
    except Exception:
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
) -> bool:
    """发布事件；近 10 分钟内相同 fingerprint 去重。返回是否新写入并派发。

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
    sf = get_session_factory()
    with sf() as session:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
        old = (
            session.query(IncidentEvent)
            .filter(
                IncidentEvent.event_type == event_type,
                IncidentEvent.fingerprint == fp,
                IncidentEvent.created_at >= cutoff,
            )
            .first()
        )
        if old:
            return False
        ev = IncidentEvent(
            event_type=event_type,
            source=source,
            payload_json=json.dumps(payload, ensure_ascii=False)[:8000],
            fingerprint=fp,
            dispatched_count=0,
        )
        session.add(ev)
        session.commit()
        eid = int(ev.id)
    _publish_stream_shadow(
        event_type,
        payload if isinstance(payload, dict) else {},
        source=source,
        incident_id=eid,
        event_fingerprint=fp,
    )
    if event_type == "employee.suggestion.created":
        try:
            from modstore_server.employee_autonomy_service import ingest_suggestion_event_payload

            ingest_suggestion_event_payload(
                source_employee_id=source,
                payload=payload if isinstance(payload, dict) else {},
                auto_dispatch=True,
            )
        except Exception:
            logger.exception("employee suggestion ingest failed")
    if event_type == "consistency_check.completed":
        try:
            if not bool((payload or {}).get("autofix_triggered")):
                from modstore_server.employee_autonomy_service import (
                    trigger_doc_autofix_from_report,
                )

                report = payload.get("report") if isinstance(payload.get("report"), dict) else None
                if not isinstance(report, dict):
                    report = payload if isinstance(payload, dict) else {}
                trigger_doc_autofix_from_report(
                    report,
                    source=source or "consistency_checker",
                    source_ref=str((payload or {}).get("source_ref") or "")[:128],
                )
        except Exception:
            logger.exception("consistency_check.completed autofix trigger failed")
    try:
        _dispatch_incident(eid)
    except Exception:  # noqa: BLE001
        logger.exception("dispatch incident id=%s failed", eid)
    return True


def _admin_user_id() -> int:
    sf = get_session_factory()
    with sf() as session:
        u = (
            session.query(User).filter(User.is_admin == True).order_by(User.id.asc()).first()
        )  # noqa: E712
        if u:
            return int(u.id)
        u2 = session.query(User).order_by(User.id.asc()).first()
        return int(u2.id) if u2 else 0


def _catalog_employee_ids(session) -> set[str]:
    rows = session.query(CatalogItem.pkg_id).filter(CatalogItem.artifact == "employee_pack").all()
    return {str(r[0]) for r in rows if r[0]}


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


def _dispatch_incident(event_id: int) -> None:
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
    for eid_emp in binding_ids:
        if not eid_emp or eid_emp not in catalog_ids:
            continue
        try:
            execute_employee_task(
                eid_emp,
                brief,
                _incident_employee_input(
                    incident_payload=payload,
                    event_type=event_type,
                    source=source,
                ),
                user_id=admin_id,
            )
            dispatched += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("incident dispatch employee=%s: %s", eid_emp, exc)

    with sf() as session:
        ev2 = session.query(IncidentEvent).filter(IncidentEvent.id == event_id).first()
        if ev2:
            ev2.dispatched_count = int(dispatched)
            session.commit()


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
            except Exception:  # noqa: BLE001
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
