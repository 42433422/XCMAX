# mypy: disable-error-code="assignment, attr-defined, no-any-return, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.retort_clarification_gate")


def answer_clarification(
    session_id: str,
    *,
    answers: _facade().Mapping[str, _facade().Any] | _facade().Sequence[_facade().Any] | str,
    answered_by: str = "admin",
) -> dict[str, _facade().Any]:
    _facade().sweep_expired_clarifications()
    sid = _facade()._text(session_id, 128)
    if not sid:
        return {"ok": False, "error": "session_id_missing"}
    if isinstance(answers, str):
        freeform = answers.strip()
        answer_map: dict[str, _facade().Any] = {"freeform": freeform} if freeform else {}
    elif isinstance(answers, _facade().Mapping):
        answer_map = {str(k): str(v).strip() for (k, v) in answers.items() if str(v or "").strip()}
        freeform = str(answer_map.get("freeform") or "").strip()
    else:
        answer_map = {}
        freeform = ""
        for index, item in enumerate(answers or [], start=1):
            if isinstance(item, _facade().Mapping):
                key = _facade()._text(item.get("id") or item.get("question_id") or f"q{index}", 64)
                value = _facade()._text(item.get("answer") or item.get("text"), 2000)
            else:
                key = f"q{index}"
                value = _facade()._text(item, 2000)
            if value:
                answer_map[key] = value
        freeform = str(answer_map.get("freeform") or "").strip()
    if not answer_map:
        return {"ok": False, "error": "answers_empty"}
    _, _, enrich = _facade()._load_clarification_builder()
    with _facade()._LOCK:
        store = _facade()._load_store_unlocked()
        sessions = dict(store.get("sessions") or {})
        row = sessions.get(sid)
        if not isinstance(row, dict):
            return {"ok": False, "error": "session_not_found"}
        if row.get("status") != _facade()._STATUS_OPEN:
            return {
                "ok": False,
                "error": f"session_not_open:{row.get('status')}",
                "session": _facade()._public_session(sid, row),
            }
        question_ids = [
            _facade()._text(item.get("id"), 64)
            for item in row.get("questions") or []
            if isinstance(item, _facade().Mapping) and _facade()._text(item.get("id"), 64)
        ]
        if freeform:
            for qid in question_ids:
                answer_map.setdefault(qid, freeform)
        missing = [qid for qid in question_ids if not str(answer_map.get(qid) or "").strip()]
        if missing and (not freeform):
            return {
                "ok": False,
                "error": "answers_incomplete",
                "missing_question_ids": missing,
                "session": _facade()._public_session(sid, row),
            }
        enriched = enrich(str(row.get("strategy_intent") or ""), answer_map)
        row = {
            **row,
            "status": _facade()._STATUS_ANSWERED,
            "answers": answer_map,
            "answered_by": _facade()._text(answered_by, 128),
            "answered_at": _facade()._now_iso(),
            "enriched_strategy_intent": enriched,
            "updated_at": _facade()._now_iso(),
        }
        sessions[sid] = row
        _facade()._save_store_unlocked({"schema": _facade()._SCHEMA, "sessions": sessions})
    try:
        boss_qid = int(row.get("boss_question_id") or 0)
    except (TypeError, ValueError):
        boss_qid = 0
    if boss_qid > 0:
        try:
            from modstore_server.models import PendingHumanQuestion, get_session_factory

            sf = get_session_factory()
            with sf() as session:
                pending = session.get(PendingHumanQuestion, boss_qid)
                if pending and pending.status == "pending":
                    pending.status = "answered"
                    pending.answer = (
                        freeform or _facade().json.dumps(answer_map, ensure_ascii=False)[:4000]
                    )
                    pending.answered_at = _facade()._now()
                    session.commit()
        except RECOVERABLE_ERRORS:
            pass
    return {"ok": True, "session": _facade()._public_session(sid, row)}


def cancel_clarification(session_id: str, *, reason: str = "cancelled") -> dict[str, _facade().Any]:
    _facade().sweep_expired_clarifications()
    sid = _facade()._text(session_id, 128)
    with _facade()._LOCK:
        store = _facade()._load_store_unlocked()
        sessions = dict(store.get("sessions") or {})
        row = sessions.get(sid)
        if not isinstance(row, dict):
            return {"ok": False, "error": "session_not_found"}
        if row.get("status") != _facade()._STATUS_OPEN:
            return {"ok": False, "error": f"session_not_open:{row.get('status')}"}
        row = {
            **row,
            "status": _facade()._STATUS_CANCELLED,
            "cancel_reason": _facade()._text(reason, 500),
            "cancelled_at": _facade()._now_iso(),
            "updated_at": _facade()._now_iso(),
        }
        sessions[sid] = row
        _facade()._save_store_unlocked({"schema": _facade()._SCHEMA, "sessions": sessions})
    return {"ok": True, "session": {"session_id": sid, **row}}


def mark_clarification_resolved(session_id: str) -> dict[str, _facade().Any]:
    sid = _facade()._text(session_id, 128)
    with _facade()._LOCK:
        store = _facade()._load_store_unlocked()
        sessions = dict(store.get("sessions") or {})
        row = sessions.get(sid)
        if not isinstance(row, dict):
            return {"ok": False, "error": "session_not_found"}
        if row.get("status") not in {
            _facade()._STATUS_ANSWERED,
            _facade()._STATUS_RESOLVED,
        }:
            return {"ok": False, "error": f"session_not_answerable:{row.get('status')}"}
        row = {
            **row,
            "status": _facade()._STATUS_RESOLVED,
            "resolved_at": _facade()._now_iso(),
            "updated_at": _facade()._now_iso(),
        }
        sessions[sid] = row
        _facade()._save_store_unlocked({"schema": _facade()._SCHEMA, "sessions": sessions})
    return {"ok": True, "session": {"session_id": sid, **row}}


def _mirror_to_boss_inbox(
    session_id: str, row: _facade().Mapping[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """Surface Retort clarification in the existing Phase-D boss Q&A inbox."""
    try:
        from modstore_server.incident_bus import _admin_user_id
        from modstore_server.models import PendingHumanQuestion, get_session_factory
        from modstore_server.notification_service import notify_human_question

        admin_id = int(_admin_user_id() or 0)
        if admin_id <= 0:
            return {"mirrored": False, "reason": "no_admin_user"}
        questions = row.get("questions") if isinstance(row.get("questions"), list) else []
        primary = ""
        for item in questions:
            if isinstance(item, _facade().Mapping) and _facade()._text(item.get("question"), 500):
                primary = _facade()._text(item.get("question"), 500)
                break
        if not primary:
            primary = "Retort 需要你确认本次变更的战略意图与风险边界。"
        fp = (
            _facade()
            .hashlib.sha256(f"retort-clarification:{session_id}".encode("utf-8"))
            .hexdigest()[:32]
        )
        now = _facade()._now()
        expires = _facade()._parse_iso(
            str(row.get("expires_at") or "")
        ) or now + _facade().timedelta(seconds=_facade().ttl_seconds())
        context = {
            "kind": "retort_clarification",
            "session_id": session_id,
            "subject": row.get("subject"),
            "change_request_id": row.get("change_request_id"),
            "proposal_id": row.get("proposal_id"),
            "run_id": row.get("run_id"),
            "question_ids": [
                _facade()._text(item.get("id"), 64)
                for item in questions
                if isinstance(item, _facade().Mapping) and _facade()._text(item.get("id"), 64)
            ],
        }
        sf = get_session_factory()
        with sf() as session:
            existing = (
                session.query(PendingHumanQuestion)
                .filter(PendingHumanQuestion.fingerprint == fp)
                .filter(PendingHumanQuestion.status == "pending")
                .first()
            )
            if existing:
                return {
                    "mirrored": True,
                    "reused": True,
                    "question_id": int(existing.id),
                }
            record = PendingHumanQuestion(
                user_id=admin_id,
                employee_id="retort-clarification",
                task=_facade()._text(row.get("source") or "retort_clarification", 256),
                question=primary,
                context_json=_facade().json.dumps(context, ensure_ascii=False),
                status="pending",
                asked_at=now,
                expires_at=expires,
                fingerprint=fp,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            question_id = int(record.id)
        try:
            notify_human_question(
                user_id=admin_id,
                question_id=question_id,
                employee_id="retort-clarification",
                question=primary,
                task=str(context.get("subject") or "retort_clarification"),
            )
        except RECOVERABLE_ERRORS:
            pass
        return {"mirrored": True, "reused": False, "question_id": question_id}
    except RECOVERABLE_ERRORS as exc:
        return {"mirrored": False, "reason": type(exc).__name__}


def open_clarification_session(
    *,
    strategy_intent: str,
    changed_files: _facade().Sequence[_facade().Any] | None = None,
    change_request_id: int | None = None,
    proposal_id: str = "",
    run_id: str = "",
    package_id: str = "",
    source: str = "retort_gate",
    risk_level: str = "",
    force: bool = False,
) -> dict[str, _facade().Any]:
    """Open or reuse a clarification session. Always sweeps first."""
    if not _facade().gate_enabled():
        return {"ok": True, "opened": False, "reason": "disabled"}
    sweep = _facade().sweep_expired_clarifications()
    paths = _facade()._paths_from_changed(changed_files)
    subject = _facade()._subject_key(
        change_request_id=change_request_id,
        proposal_id=proposal_id,
        run_id=run_id,
        package_id=package_id,
    )
    intent = _facade()._text(strategy_intent, 4000)
    assess = _facade()._load_alignment()
    assessment = assess(
        _facade()._normalize_changed_for_alignment(changed_files), issue_context=intent
    )
    build_questions, needed, _enrich = _facade()._load_clarification_builder()
    if not force and (
        not needed(assessment, intent, changed_files=changed_files, risk_level=risk_level)
    ):
        return {
            "ok": True,
            "opened": False,
            "reason": "not_needed",
            "assessment_status": assessment.get("status"),
            "sweep": sweep,
        }
    questions = build_questions(
        assessment,
        strategy_intent=intent,
        changed_files=changed_files,
        max_questions=3,
        risk_level=risk_level,
    )
    if not questions:
        questions = [
            {
                "id": "intent_confirm",
                "priority": "P0",
                "question": "请确认本次变更的战略意图、范围与验收标准。",
                "reason": "retort_clarification_required",
                "blocking": True,
            }
        ]
    fp = _facade()._fingerprint(subject, intent, paths)
    expires = _facade()._now() + _facade().timedelta(seconds=_facade().ttl_seconds())
    with _facade()._LOCK:
        store = _facade()._load_store_unlocked()
        sessions = dict(store.get("sessions") or {})
        for sid, row in sessions.items():
            if not isinstance(row, dict):
                continue
            if row.get("status") != _facade()._STATUS_OPEN:
                continue
            if row.get("subject") == subject and row.get("fingerprint") == fp:
                return {
                    "ok": True,
                    "opened": False,
                    "reused": True,
                    "session": {"session_id": sid, **row},
                    "sweep": sweep,
                }
        for sid, row in list(sessions.items()):
            if (
                isinstance(row, dict)
                and row.get("status") == _facade()._STATUS_OPEN
                and (row.get("subject") == subject)
            ):
                row = {
                    **row,
                    "status": _facade()._STATUS_CANCELLED,
                    "cancel_reason": "superseded",
                    "cancelled_at": _facade()._now_iso(),
                    "updated_at": _facade()._now_iso(),
                }
                sessions[sid] = row
        sid = f"rcl-{_facade().uuid.uuid4().hex[:16]}"
        row = {
            "schema": _facade()._SCHEMA,
            "status": _facade()._STATUS_OPEN,
            "subject": subject,
            "fingerprint": fp,
            "source": _facade()._text(source, 64),
            "strategy_intent": intent,
            "changed_files": paths[:40],
            "change_request_id": int(change_request_id or 0) or None,
            "proposal_id": _facade()._text(proposal_id, 128),
            "run_id": _facade()._text(run_id, 128),
            "package_id": _facade()._text(package_id, 128),
            "assessment_status": assessment.get("status"),
            "missing_keywords": list(assessment.get("missing_keywords") or [])[:12],
            "risk_level": _facade()._text(risk_level, 32),
            "questions": questions,
            "answers": {},
            "created_at": _facade()._now_iso(),
            "updated_at": _facade()._now_iso(),
            "expires_at": expires.isoformat(),
            "ttl_seconds": _facade().ttl_seconds(),
        }
        sessions[sid] = row
        _facade()._save_store_unlocked({"schema": _facade()._SCHEMA, "sessions": sessions})
    mirror = _facade()._mirror_to_boss_inbox(sid, row)
    if mirror.get("question_id"):
        with _facade()._LOCK:
            store = _facade()._load_store_unlocked()
            sessions = dict(store.get("sessions") or {})
            current = dict(sessions.get(sid) or row)
            current["boss_question_id"] = int(mirror["question_id"])
            current["updated_at"] = _facade()._now_iso()
            sessions[sid] = current
            _facade()._save_store_unlocked({"schema": _facade()._SCHEMA, "sessions": sessions})
            row = current
    try:
        from modstore_server.human_uncertainty_queue import enqueue_uncertain_item

        enqueue_uncertain_item(
            context={
                "subject": subject,
                "session_id": sid,
                "change_request_id": change_request_id,
                "run_id": run_id,
            },
            decision={"action": "retort_clarification", "session_id": sid},
            reason=str(questions[0].get("question") or "Retort 需要澄清意图"),
            source="retort_clarification_gate",
        )
    except RECOVERABLE_ERRORS:
        pass
    return {
        "ok": True,
        "opened": True,
        "reused": False,
        "session": {"session_id": sid, **row},
        "boss_inbox": mirror,
        "sweep": sweep,
    }


def open_clarification_for_change_request(
    change_request_id: int,
    *,
    strategy_intent: str = "",
    changed_files: _facade().Sequence[_facade().Any] | None = None,
    source_employee_id: str = "",
    risk_level: str = "",
) -> dict[str, _facade().Any]:
    intent = _facade()._text(strategy_intent, 4000)
    if not intent:
        intent = f"审批变更请求 CR#{int(change_request_id)}"
        if source_employee_id:
            intent = f"{intent}（来源员工 {source_employee_id}）"
    return _facade().open_clarification_session(
        strategy_intent=intent,
        changed_files=changed_files,
        change_request_id=int(change_request_id),
        package_id="change-request",
        source="change_request.created",
        risk_level=risk_level,
        force=False,
    )


def _latest_session_for_subject(
    subject: str,
) -> _facade().Optional[dict[str, _facade().Any]]:
    with _facade()._LOCK:
        sessions = _facade()._load_store_unlocked().get("sessions") or {}
    rows = [
        {"session_id": sid, **row}
        for (sid, row) in sessions.items()
        if isinstance(row, dict) and row.get("subject") == subject
    ]
    if not rows:
        return None
    rows.sort(
        key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
        reverse=True,
    )
    return rows[0]
