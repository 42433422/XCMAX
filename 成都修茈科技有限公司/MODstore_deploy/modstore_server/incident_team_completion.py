"""Resume persisted Para tasks through authenticated reads, without dispatching new work."""

from __future__ import annotations

import json
from copy import deepcopy

from modstore_server.codex_model_attempts import parse_codex_models_tried
from modstore_server.customer_issue_delivery_contract import (
    execution_pending,
    execution_succeeded,
    team_succeeded,
)
from modstore_server.incident_team_handler_digest import handler_output_digest, redact_text
from modstore_server.models import IncidentEvent, get_session_factory
from modstore_server.models_cs import CustomerServiceTicket
from modstore_server.operational_errors import RECOVERABLE_ERRORS

_PENDING_CURSOR = 0


def reconcile_pending_teams(*, event_id=None, limit=20, fetcher=None):
    from modstore_server.customer_issue_shared_release import record_worker_repair
    from modstore_server.customer_service_orchestrator import (
        apply_customer_ticket_incident_progress,
    )
    from modstore_server.para_delegate_handler import (
        _api_base,
        _first_para_error,
        _task_result_snapshot,
    )
    from modstore_server.self_maintenance_loop_runner import _fetch_para_task_state

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
                if o.get("handler") == "para_delegate"
                and o.get("accepted") is True
                and o.get("completed") is False
                and (row.get("status") == "pending" or o.get("status") == "para_task_accepted")
            ]
            for output in pending:
                task_id = str(output.get("para_task_id") or output.get("task_id") or "")
                if not task_id:
                    output.update(
                        ok=False, status="para_task_missing_id", error="缺少原任务号，需人工核对"
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
                        ok = status in {"completed", "merged"}
                        snapshot = _task_result_snapshot({"task": task})
                        output.update(
                            ok=ok,
                            completed=ok,
                            status="para_task_" + status,
                            summary=redact_text(task.get("summary") or ""),
                            para_result=snapshot,
                        )
                        if not ok:
                            output["error"] = redact_text(
                                task.get("error") or _first_para_error(snapshot) or "Para任务失败"
                            )
                        tried = parse_codex_models_tried(
                            task.get("error"), _first_para_error(snapshot), task.get("summary")
                        )
                        if tried:
                            output["codex_models_tried"] = tried
                    digest.pop("poll_error", None)
                except RECOVERABLE_ERRORS as exc:
                    code = getattr(getattr(exc, "response", None), "status_code", "")
                    digest["poll_error"] = redact_text(
                        f"原任务 {task_id} 读取失败 {code or ('API 未配置' if not base else '')} ({type(exc).__name__})"
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
            ticket_id = int(payload.get("ticket_id") or 0)
            ticket = db.get(CustomerServiceTicket, ticket_id, with_for_update=True)
            if ticket is not None:
                evidence = json.loads(ticket.evidence_json or "{}")
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
                and ticket.status not in {"resolved", "closed", "reopened"}
                and not ticket.closed_at
                and resolution.get("state") != "reopened"
            ):
                apply_customer_ticket_incident_progress(
                    db, ticket_id=ticket.id, event_id=eid, team_ok=claim["ok"], team_rows=rows
                )
                record_worker_repair(db, ticket, eid, rows)
            db.commit()
            changed += 1
    return {"changed": changed}


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
