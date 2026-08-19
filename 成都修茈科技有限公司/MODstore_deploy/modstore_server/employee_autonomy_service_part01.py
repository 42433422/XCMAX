# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_autonomy_service")


def _jloads(text: str, default: _facade().Any) -> _facade().Any:
    raw = (text or "").strip()
    if not raw:
        return default
    try:
        return _facade().json.loads(raw)
    except Exception:
        return default


def _jdumps(obj: _facade().Any, *, max_chars: int = 0) -> str:
    text = _facade().json.dumps(obj, ensure_ascii=False)
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars] + "…"
    return text


def _dedupe_strs(items: _facade().Iterable[_facade().Any]) -> _facade().List[str]:
    out: _facade().List[str] = []
    seen: set[str] = set()
    for it in items:
        s = str(it or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _resolve_actor_user_id(session, fallback_user_id: int = 0) -> int:
    uid = int(fallback_user_id or 0)
    if uid > 0:
        return uid
    u = (
        session.query(_facade().User)
        .filter(_facade().User.is_admin == True)
        .order_by(_facade().User.id.asc())
        .first()
    )
    if u:
        return int(u.id)
    u2 = session.query(_facade().User).order_by(_facade().User.id.asc()).first()
    return int(u2.id) if u2 else 0


def _publish_event(
    event_type: str,
    payload: _facade().Dict[str, _facade().Any],
    *,
    source: str,
    fingerprint: str | None = None,
) -> None:
    try:
        from modstore_server.incident_bus import publish

        publish(event_type, payload, source=source, fingerprint=fingerprint)
    except Exception:
        _facade().logger.exception(
            "publish event failed event_type=%s source=%s", event_type, source
        )


def _suggestion_auto_dispatch_enabled() -> bool:
    return (
        _facade().os.environ.get("MODSTORE_SUGGESTION_AUTO_DISPATCH", "1") or ""
    ).strip().lower() in ("1", "true", "yes", "on")


def _brief_auto_dispatch_enabled() -> bool:
    return (
        _facade().os.environ.get("MODSTORE_DAILY_BRIEF_TODO_DISPATCH_ENABLED", "1") or ""
    ).strip().lower() in ("1", "true", "yes", "on")


def _doc_autofix_enabled() -> bool:
    return (
        _facade().os.environ.get("MODSTORE_DOC_CONSISTENCY_AUTOFIX_ENABLED", "1") or ""
    ).strip().lower() in ("1", "true", "yes", "on")


def _evolution_enabled() -> bool:
    return (
        _facade().os.environ.get("MODSTORE_EMPLOYEE_EVOLUTION_ENABLED", "1") or ""
    ).strip().lower() in ("1", "true", "yes", "on")


def _infer_suggestion_targets(
    source_employee_id: str,
    payload: _facade().Dict[str, _facade().Any],
    explicit_targets: _facade().Sequence[str] | None = None,
) -> _facade().List[str]:
    direct = _facade()._dedupe_strs(explicit_targets or payload.get("target_employee_ids") or [])
    if direct:
        return direct
    target_one = str(payload.get("target_employee_id") or "").strip()
    if target_one:
        return [target_one]
    kind = str(payload.get("kind") or "").strip().lower()
    if kind in {"doc_consistency_fix", "doc_fix", "doc_change"}:
        return ["doc-knowledge-curator"]
    if kind in {"collab_mention"}:
        mentions = _facade()._dedupe_strs(payload.get("mentioned_employee_ids") or [])
        if mentions:
            return mentions
    if kind in {"scope_violation"}:
        return ["daily-orchestrator"]
    source = str(source_employee_id or "").strip()
    if source and source != "daily-orchestrator":
        return [source]
    return ["daily-orchestrator"]


def create_collab_thread(
    *,
    title: str,
    participants: _facade().Sequence[str],
    created_by_employee_id: str,
    context: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    emit_event: bool = True,
) -> _facade().Dict[str, _facade().Any]:
    pids = _facade()._dedupe_strs(participants)
    if created_by_employee_id and created_by_employee_id not in pids:
        pids.insert(0, created_by_employee_id)
    sf = _facade().get_session_factory()
    with sf() as session:
        row = _facade().EmployeeCollabThread(
            title=(title or "协作线程")[:256],
            participants_json=_facade()._jdumps(pids),
            context_json=_facade()._jdumps(context or {}),
            status="open",
            created_by_employee_id=(created_by_employee_id or "")[:128],
        )
        session.add(row)
        session.commit()
        tid = int(row.id)
    if emit_event:
        _facade()._publish_event(
            "employee.collab.thread_created",
            {"thread_id": tid, "participants": pids, "title": (title or "")[:256]},
            source=created_by_employee_id or "system",
        )
    return {"ok": True, "thread_id": tid, "participants": pids}


def post_collab_message(
    *,
    thread_id: int,
    sender_employee_id: str,
    content: str,
    mentions: _facade().Optional[_facade().Sequence[str]] = None,
    payload: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    emit_event: bool = True,
) -> _facade().Dict[str, _facade().Any]:
    """向协作线程投递一条消息。

    ``emit_event=False`` 时跳过 ``employee.collab.message_created`` 事件发布——
    供自动化「工作汇报」批量投递使用，避免每条汇报都触发 incident 编排/派单。
    """
    if int(thread_id or 0) <= 0:
        return {"ok": False, "error": "invalid thread_id"}
    text = str(content or "").strip()
    if not text:
        return {"ok": False, "error": "content empty"}
    mention_ids = _facade()._dedupe_strs(mentions or [])
    sf = _facade().get_session_factory()
    with sf() as session:
        thread = session.get(_facade().EmployeeCollabThread, int(thread_id))
        if not thread:
            return {"ok": False, "error": "thread not found"}
        row = _facade().EmployeeCollabMessage(
            thread_id=int(thread_id),
            sender_employee_id=(sender_employee_id or "")[:128],
            content=text[:20000],
            mentions_json=_facade()._jdumps(mention_ids),
            payload_json=_facade()._jdumps(payload or {}, max_chars=30000),
        )
        session.add(row)
        thread.updated_at = _facade().datetime.now(_facade().timezone.utc)
        session.commit()
        mid = int(row.id)
    if emit_event:
        _facade()._publish_event(
            "employee.collab.message_created",
            {
                "thread_id": int(thread_id),
                "message_id": mid,
                "sender_employee_id": sender_employee_id,
                "mentions": mention_ids,
                "content_excerpt": text[:500],
            },
            source=sender_employee_id or "system",
        )
    mention_suggestion_id: _facade().Optional[int] = None
    if mention_ids:
        out = _facade().create_employee_suggestion(
            source_employee_id=sender_employee_id or "system",
            summary=f"协作提及：{sender_employee_id} @ {'/'.join(mention_ids)}",
            detail=text[:4000],
            payload={
                "kind": "collab_mention",
                "thread_id": int(thread_id),
                "message_id": mid,
                "mentioned_employee_ids": mention_ids,
            },
            target_employee_ids=mention_ids,
            kind="collab_mention",
            risk_level="low",
            thread_id=int(thread_id),
            emit_event=True,
            auto_dispatch=True,
        )
        if out.get("ok"):
            mention_suggestion_id = int(out.get("suggestion_id") or 0)
    return {
        "ok": True,
        "thread_id": int(thread_id),
        "message_id": mid,
        "mentions": mention_ids,
        "suggestion_id": mention_suggestion_id,
    }


def create_employee_suggestion(
    *,
    source_employee_id: str,
    summary: str,
    detail: str = "",
    payload: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    target_employee_ids: _facade().Optional[_facade().Sequence[str]] = None,
    kind: str = "general",
    risk_level: str = "medium",
    thread_id: _facade().Optional[int] = None,
    emit_event: bool = True,
    auto_dispatch: bool = False,
) -> _facade().Dict[str, _facade().Any]:
    src = str(source_employee_id or "").strip() or "system"
    pl = dict(payload or {})
    targets = _facade()._infer_suggestion_targets(src, pl, explicit_targets=target_employee_ids)
    targets = _facade()._dedupe_strs(targets)
    risk = str(risk_level or "medium").strip().lower()
    if risk not in ("low", "medium", "high"):
        risk = "medium"
    knd = str(kind or pl.get("kind") or "general").strip().lower()[:64] or "general"
    sf = _facade().get_session_factory()
    with sf() as session:
        row = _facade().EmployeeSuggestion(
            source_employee_id=src[:128],
            target_employee_ids_json=_facade()._jdumps(targets),
            kind=knd,
            summary=(summary or "")[:8000],
            detail=(detail or "")[:30000],
            payload_json=_facade()._jdumps(pl, max_chars=100000),
            risk_level=risk,
            status="pending",
            thread_id=int(thread_id) if thread_id else None,
        )
        session.add(row)
        session.commit()
        sid = int(row.id)
        boss_uid = _facade()._resolve_actor_user_id(session)
    payload_evt = {
        "suggestion_id": sid,
        "source_employee_id": src,
        "target_employee_ids": targets,
        "kind": knd,
        "summary": (summary or "")[:500],
        "risk_level": risk,
        "thread_id": int(thread_id) if thread_id else None,
        **{k: v for (k, v) in pl.items() if k not in ("summary", "target_employee_ids")},
    }
    if emit_event:
        _facade()._publish_event("employee.suggestion.created", payload_evt, source=src)
    if auto_dispatch and _facade()._suggestion_auto_dispatch_enabled():
        _facade().dispatch_suggestion(sid, approved_by_user_id=0, force_approve_if_needed=True)
    try:
        from modstore_server.notification_service import employee_message_to_boss

        if boss_uid:
            msg = f"💡 我有个建议：{(summary or '').strip()[:600]}"
            d = (detail or "").strip()
            if d:
                msg += f"\n\n{d[:800]}"
            employee_message_to_boss(boss_uid, src, msg)
    except Exception as exc:
        _facade().logger.warning("employee suggestion IM DM failed: %s", exc)
    return {"ok": True, "suggestion_id": sid, "target_employee_ids": targets}


def ingest_suggestion_event_payload(
    *,
    source_employee_id: str,
    payload: _facade().Dict[str, _facade().Any],
    auto_dispatch: bool = True,
) -> _facade().Dict[str, _facade().Any]:
    """把已有 ``employee.suggestion.created`` 负载落库为 EmployeeSuggestion。"""
    pl = dict(payload or {})
    sid_raw = pl.get("suggestion_id")
    try:
        sid_existing = int(sid_raw) if sid_raw is not None else 0
    except Exception:
        sid_existing = 0
    if sid_existing > 0:
        sf = _facade().get_session_factory()
        with sf() as session:
            row = session.get(_facade().EmployeeSuggestion, sid_existing)
            if row:
                if auto_dispatch and _facade()._suggestion_auto_dispatch_enabled():
                    _facade().dispatch_suggestion(
                        sid_existing, approved_by_user_id=0, force_approve_if_needed=False
                    )
                return {"ok": True, "suggestion_id": sid_existing, "existing": True}
    summary = str(pl.get("summary") or pl.get("detail") or pl.get("kind") or "员工建议").strip()
    detail = str(pl.get("detail") or "").strip()
    kind = str(pl.get("kind") or "general").strip() or "general"
    risk = str(pl.get("risk_level") or "medium").strip() or "medium"
    thread_id_raw = pl.get("thread_id")
    try:
        tid = int(thread_id_raw) if thread_id_raw is not None else None
    except Exception:
        tid = None
    out = _facade().create_employee_suggestion(
        source_employee_id=source_employee_id,
        summary=summary,
        detail=detail,
        payload=pl,
        target_employee_ids=(
            pl.get("target_employee_ids")
            if isinstance(pl.get("target_employee_ids"), list)
            else None
        ),
        kind=kind,
        risk_level=risk,
        thread_id=tid,
        emit_event=False,
        auto_dispatch=auto_dispatch,
    )
    sid = int(out.get("suggestion_id") or 0)
    return {"ok": True, "suggestion_id": sid}


def approve_suggestion(
    suggestion_id: int, *, approved_by_user_id: int, dispatch_now: bool = True
) -> _facade().Dict[str, _facade().Any]:
    sid = int(suggestion_id or 0)
    if sid <= 0:
        return {"ok": False, "error": "invalid suggestion id"}
    sf = _facade().get_session_factory()
    with sf() as session:
        row = session.get(_facade().EmployeeSuggestion, sid)
        if not row:
            return {"ok": False, "error": "not found"}
        if (row.status or "") == "rejected":
            return {"ok": False, "error": "already rejected"}
        row.status = "approved"
        row.approved_by_user_id = int(approved_by_user_id or 0) or None
        row.approved_at = _facade().datetime.now(_facade().timezone.utc)
        session.commit()
    _facade()._publish_event(
        "employee.suggestion.approved",
        {"suggestion_id": sid, "approved_by_user_id": int(approved_by_user_id or 0)},
        source="admin",
    )
    if dispatch_now:
        return _facade().dispatch_suggestion(sid, approved_by_user_id=approved_by_user_id)
    return {"ok": True, "suggestion_id": sid}


def reject_suggestion(
    suggestion_id: int, *, rejected_reason: str, rejected_by_user_id: int
) -> _facade().Dict[str, _facade().Any]:
    sid = int(suggestion_id or 0)
    if sid <= 0:
        return {"ok": False, "error": "invalid suggestion id"}
    sf = _facade().get_session_factory()
    with sf() as session:
        row = session.get(_facade().EmployeeSuggestion, sid)
        if not row:
            return {"ok": False, "error": "not found"}
        row.status = "rejected"
        row.rejected_reason = (rejected_reason or "")[:4000]
        row.approved_by_user_id = int(rejected_by_user_id or 0) or None
        row.approved_at = _facade().datetime.now(_facade().timezone.utc)
        session.commit()
    _facade()._publish_event(
        "employee.suggestion.rejected",
        {"suggestion_id": sid, "reason": (rejected_reason or "")[:500]},
        source="admin",
    )
    return {"ok": True, "suggestion_id": sid}


def _build_subtask_text(
    summary: str, detail: str, payload: _facade().Dict[str, _facade().Any]
) -> str:
    lines = [str(summary or "").strip()]
    if detail:
        lines.append(f"详情：{detail.strip()[:2000]}")
    kind = str(payload.get("kind") or "").strip()
    if kind:
        lines.append(f"建议类型：{kind}")
    if payload:
        tiny = {
            k: payload.get(k)
            for k in ("path", "thread_id", "message_id", "employee_id", "issue_count")
        }
        tiny = {k: v for (k, v) in tiny.items() if v is not None and str(v) != ""}
        if tiny:
            lines.append(f"上下文：{_facade()._jdumps(tiny, max_chars=1200)}")
    return "\n".join((x for x in lines if x)).strip()[:4000]


@_facade().platform_llm_scoped
def dispatch_suggestion(
    suggestion_id: int, *, approved_by_user_id: int = 0, force_approve_if_needed: bool = False
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
    except Exception as exc:
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
        from modstore_server.employee_collab_reporter import report_suggestion_dispatched

        report_suggestion_dispatched(suggestion_id=sid)
    except Exception:
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
