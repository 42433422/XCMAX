# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_autonomy_service")


@_facade().platform_llm_scoped
def dispatch_suggestion(
    suggestion_id: int,
    *,
    approved_by_user_id: int = 0,
    force_approve_if_needed: bool = False,
) -> _facade().Dict[str, _facade().Any]:
    sid = int(suggestion_id or 0)
    if sid <= 0:
        return {"ok": False, "error": "invalid suggestion id"}
    sf = _facade().get_session_factory()
    with sf() as session:
        row = session.get(_facade().EmployeeSuggestion, sid)
        if not row:
            return {"ok": False, "error": "not found"}
        status = str(row.status or "")
        if status == "rejected":
            return {"ok": False, "error": "suggestion rejected"}
        if status == "done":
            return {"ok": True, "suggestion_id": sid, "status": "done"}
        if status == "pending":
            if force_approve_if_needed:
                row.status = "approved"
                row.approved_by_user_id = int(approved_by_user_id or 0) or None
                row.approved_at = _facade().datetime.now(_facade().timezone.utc)
                session.commit()
            elif str(row.risk_level or "medium") != "low":
                return {
                    "ok": False,
                    "error": "pending medium/high risk suggestion requires approval",
                }
        payload = _facade()._jloads(row.payload_json or "{}", {})
        if not isinstance(payload, dict):
            payload = {}
        targets = _facade()._dedupe_strs(
            _facade()._jloads(row.target_employee_ids_json or "[]", [])
        )
        if not targets:
            targets = _facade()._infer_suggestion_targets(
                str(row.source_employee_id or ""), payload
            )
        actor_uid = _facade()._resolve_actor_user_id(
            session, fallback_user_id=int(approved_by_user_id or 0)
        )
        summary = str(row.summary or "")
        detail = str(row.detail or "")
    from modstore_server.employee_orchestrator import dispatch_subtasks
    from modstore_server.task_router import SubTask

    task_brief = _facade()._build_subtask_text(summary, detail, payload)
    subtasks = [
        SubTask(
            employee_id=tid,
            task_brief=task_brief,
            input_data={
                "source_suggestion_id": sid,
                "source_employee_id": str(payload.get("source_employee_id") or ""),
                "suggestion_payload": payload,
            },
            depends_on=[],
            priority=3,
        )
        for tid in targets
    ]
    result: _facade().Dict[str, _facade().Any]
    try:
        result = dispatch_subtasks(
            subtasks,
            created_by_user_id=actor_uid,
            max_concurrency=min(max(1, len(subtasks)), 4),
            allow_high_risk_real_run=False,
        )
    except RECOVERABLE_ERRORS as exc:
        result = {"ok": False, "error": str(exc)}
    with sf() as session:
        row = session.get(_facade().EmployeeSuggestion, sid)
        if not row:
            return {"ok": False, "error": "suggestion disappeared"}
        row.created_task_ids_json = _facade()._jdumps(targets)
        ok = bool(result.get("ok"))
        row.status = "done" if ok else "dispatched"
        session.commit()
    _facade()._publish_event(
        "employee.suggestion.dispatched",
        {
            "suggestion_id": sid,
            "target_employee_ids": targets,
            "ok": bool(result.get("ok")),
            "error": str(result.get("error") or "")[:500],
        },
        source="suggestion_dispatcher",
    )
    try:
        from modstore_server.employee_collab_reporter import (
            report_suggestion_dispatched,
        )

        report_suggestion_dispatched(suggestion_id=sid)
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("collab report (suggestion) failed sid=%s", sid)
    return {"ok": True, "suggestion_id": sid, "dispatch_result": result}


@_facade().platform_llm_scoped
def dispatch_pending_suggestions(limit: int = 20) -> _facade().Dict[str, _facade().Any]:
    lim = max(1, min(int(limit or 20), 100))
    sf = _facade().get_session_factory()
    with sf() as session:
        rows = (
            session.query(_facade().EmployeeSuggestion)
            .filter(
                (_facade().EmployeeSuggestion.status == "approved")
                | (_facade().EmployeeSuggestion.status == "pending")
                & (_facade().EmployeeSuggestion.risk_level == "low")
            )
            .order_by(_facade().EmployeeSuggestion.id.asc())
            .limit(lim)
            .all()
        )
        ids = [(int(r.id), str(r.status or ""), str(r.risk_level or "")) for r in rows]
    processed = 0
    ok_count = 0
    skipped = 0
    errors: _facade().List[str] = []
    for sid, status, risk in ids:
        force = status == "pending" and risk == "low"
        out = _facade().dispatch_suggestion(
            sid, approved_by_user_id=0, force_approve_if_needed=force
        )
        processed += 1
        if out.get("ok"):
            ok_count += 1
        else:
            skipped += 1
            errors.append(str(out.get("error") or "unknown")[:200])
    return {
        "ok": True,
        "processed": processed,
        "ok_count": ok_count,
        "skipped": skipped,
        "errors": errors[:20],
    }
