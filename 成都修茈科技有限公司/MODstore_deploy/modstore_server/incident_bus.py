"""incident-bus：事件入队并按 EmployeeTriggerBinding 派发员工任务。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
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
from modstore_server.platform_llm_scope import platform_llm_scoped

logger = logging.getLogger(__name__)

# 2026-07-31 修复：uvicorn --workers 4 + uvloop 下，裸 threading.Thread(daemon=True)
# 会被 asyncio 事件循环干扰，导致 daemon thread 不执行（dispatched_count 停在 0）。
# 用模块级 ThreadPoolExecutor 替代，线程池有任务队列和线程管理，更稳健。
_DISPATCH_EXECUTOR = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="incident-dispatch",
)

# dispatch_pending_incidents 的并发限制（避免 PG 连接池耗尽）
_PENDING_DISPATCH_EXECUTOR = ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="incident-pending",
)

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
            from modstore_server.employee_autonomy_service import (
                ingest_suggestion_event_payload,
            )

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
    # 默认异步派发：同步跑员工编排/LLM 会拖死 HTTP（如 AI 客服 /chat → 处理中卡住）。
    # 测试或显式需要可设 MODSTORE_INCIDENT_SYNC_DISPATCH=1。
    sync_dispatch = (os.environ.get("MODSTORE_INCIDENT_SYNC_DISPATCH") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    def _run_dispatch() -> None:
        try:
            logger.info("incident_bus: dispatch thread started event_id=%s", eid)
            _dispatch_incident(eid)
            logger.info("incident_bus: dispatch thread completed event_id=%s", eid)
        except Exception:  # noqa: BLE001
            logger.exception("dispatch incident id=%s failed", eid)

    if sync_dispatch:
        _run_dispatch()
    else:
        # 2026-07-31 修复：改用 ThreadPoolExecutor 替代裸 threading.Thread(daemon=True)。
        # 旧实现在 uvicorn --workers 4 + uvloop 下 daemon thread 不执行（dispatched_count 停在 0）。
        _DISPATCH_EXECUTOR.submit(_run_dispatch)
    return True


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
            session.query(User).filter(User.is_admin.is_(True)).order_by(User.id.asc()).first()
        )  # noqa: E712
        if u:
            return int(u.id)
        u2 = session.query(User).order_by(User.id.asc()).first()
        return int(u2.id) if u2 else 0


def _catalog_employee_ids(session) -> set[str]:
    rows = session.query(CatalogItem.pkg_id).filter(CatalogItem.artifact == "employee_pack").all()
    return {str(r[0]) for r in rows if r[0]}


def _incident_event_type(event_id: int) -> str:
    sf = get_session_factory()
    with sf() as session:
        ev = (
            session.query(IncidentEvent.event_type)
            .filter(IncidentEvent.id == int(event_id))
            .first()
        )
        return str(ev[0] or "") if ev else ""


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
    claimed_here = False
    try:
        from modstore_server.node_coordinator import claim_incident_for_node

        claim = claim_incident_for_node(event_id)
        if not claim.get("claimed"):
            logger.info(
                "incident_bus: event_id=%s already claimed by node=%s",
                event_id,
                claim.get("owner"),
            )
            return
        claimed_here = True
    except Exception:
        logger.debug("incident cluster claim skipped event_id=%s", event_id, exc_info=True)

    try:
        _dispatch_incident_body(event_id)
    finally:
        if claimed_here:
            try:
                from modstore_server.node_coordinator import release_incident_claim

                release_incident_claim(event_id)
            except Exception:
                logger.debug(
                    "incident cluster claim release failed event_id=%s",
                    event_id,
                    exc_info=True,
                )


def dispatch_pending_incidents(*, max_age_seconds: int = 3600, limit: int = 5) -> int:
    """扫描 dispatched_count=0 的 incident_events 并补派发。

    2026-07-31 修复：uvicorn --workers 4 + uvloop 下 daemon thread/ThreadPoolExecutor
    不执行，导致 incident_event 写入后 dispatched_count 停在 0。此函数由
    modstore-scheduler.service 定期调用（每 30 秒），作为 dispatch 的兜底机制。

    只处理创建超过 30 秒但仍未派发的事件（避免和 publish 里的异步 dispatch 竞争）。
    用 thread 异步执行 dispatch，避免阻塞 scheduler（dispatch 可能跑 15 分钟）。
    _dispatch_incident 内部有 claim_incident_for_node 机制避免重复 dispatch。
    """
    sf = get_session_factory()
    pending_ids: list[int] = []
    with sf() as session:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        grace = datetime.now(timezone.utc) - timedelta(seconds=30)
        rows = (
            session.query(IncidentEvent.id, IncidentEvent.event_type)
            .filter(
                IncidentEvent.dispatched_count == 0,
                IncidentEvent.created_at >= cutoff,
                IncidentEvent.created_at < grace,
                IncidentEvent.event_type.notin_(_NON_DISPATCH_EVENT_TYPES),
            )
            .order_by(IncidentEvent.id.asc())
            .limit(limit)
            .all()
        )
        pending_ids = [int(r[0]) for r in rows]
    if not pending_ids:
        return 0
    logger.info(
        "incident_bus: dispatch_pending_incidents found %d pending events: %s",
        len(pending_ids),
        pending_ids,
    )
    submitted = 0
    for eid in pending_ids:
        # 用 ThreadPoolExecutor 限制并发（max_workers=2），避免 PG 连接池耗尽
        # _dispatch_incident 内部有 claim_incident_for_node 机制避免重复 dispatch
        _PENDING_DISPATCH_EXECUTOR.submit(_safe_dispatch_incident, eid)
        submitted += 1
    logger.info(
        "incident_bus: dispatch_pending_incidents submitted %d/%d async dispatch threads",
        submitted,
        len(pending_ids),
    )
    return submitted


def _safe_dispatch_incident(event_id: int) -> None:
    """_dispatch_incident 的安全包装，捕获所有异常并记录日志。"""
    try:
        logger.info("incident_bus: pending dispatch thread started event_id=%s", event_id)
        _dispatch_incident(event_id)
        logger.info("incident_bus: pending dispatch thread completed event_id=%s", event_id)
    except Exception:  # noqa: BLE001
        logger.exception("dispatch_pending_incidents event_id=%s failed", event_id)


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
            if isinstance(nested, dict) and isinstance(nested.get("routing_plan"), list):
                return [row for row in nested["routing_plan"] if isinstance(row, dict)]
    return []


def _routing_plan_owners(exec_result: Any) -> set[str]:
    return {
        str(row.get("proposed_owner") or "").strip()
        for row in _extract_routing_plan(exec_result)
        if str(row.get("proposed_owner") or "").strip()
    }


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
            logger.info(
                "incident_bus: intake routing_plan dispatched owner=%s request_id=%s",
                owner,
                row.get("request_id"),
            )
        except Exception:  # noqa: BLE001
            logger.exception("incident_bus: intake routing_plan dispatch failed owner=%s", owner)
    return extra


def _dispatch_incident_body(event_id: int) -> None:
    event_type_pre = _incident_event_type(event_id)
    if event_type_pre in _NON_DISPATCH_EVENT_TYPES:
        logger.info(
            "incident_bus: lifecycle event_id=%s event_type=%s recorded without employee dispatch",
            event_id,
            event_type_pre,
        )
        return

    binding_only = event_type_pre in _BINDING_ONLY_EVENT_TYPES

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
                    "incident_bus: unified orchestrator parked event_id=%s reason=%s",
                    event_id,
                    orchestration.get("reason"),
                )
                return
        except Exception:
            logger.exception(
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
                    "incident_bus: team claimed event_id=%s ok=%s team=%s",
                    event_id,
                    team.get("ok"),
                    (
                        (team.get("team") or {}).get("team")
                        if isinstance(team.get("team"), dict)
                        else None
                    ),
                )
                # 客服工单：团队抢单后仍走 binding，让 intake-dispatcher /
                # user-customer-service-officer 按既有订阅接单（跳过 market 防双派）。
                if event_type_pre == "ops.intake.customer_ticket":
                    binding_only = True
                else:
                    return
            else:
                logger.info(
                    "incident_bus: team did not claim event_id=%s reason=%s; fallback market",
                    event_id,
                    team.get("reason"),
                )
        except Exception:
            logger.exception("incident team failed event_id=%s; fallback market", event_id)

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
                    "incident_bus: market claimed event_id=%s employee=%s score=%s",
                    event_id,
                    market.get("employee_id"),
                    (
                        (market.get("winner") or {}).get("score")
                        if isinstance(market.get("winner"), dict)
                        else None
                    ),
                )
                return
            logger.info(
                "incident_bus: market did not claim event_id=%s reason=%s; fallback binding dispatch",
                event_id,
                market.get("reason"),
            )
        except Exception:
            logger.exception(
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
            from modstore_server.duty_workforce_contracts import duty_event_execution_input

            duty_input = duty_event_execution_input(
                eid_emp,
                event_type=event_type,
                source=source,
                incident=payload,
            )
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
        except Exception as exc:  # noqa: BLE001
            logger.exception("incident dispatch employee=%s: %s", eid_emp, exc)

    with sf() as session:
        ev2 = session.query(IncidentEvent).filter(IncidentEvent.id == event_id).first()
        if ev2:
            # team/market 可能已写过 dispatched_count；binding 追加而非覆盖
            ev2.dispatched_count = int(ev2.dispatched_count or 0) + int(dispatched)
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
