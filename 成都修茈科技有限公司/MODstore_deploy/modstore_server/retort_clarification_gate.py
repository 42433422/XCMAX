"""Retort clarification gate: blocking questions with TTL anti-backlog.

Flow:
1. Intent missing / misaligned → open a clarification session (deduped).
2. Human answers → enrich strategy_intent → re-assess alignment.
3. TTL / max-pending sweep → expire stale sessions so queues never pile up.

Persistence is a rewriteable JSON ledger (not append-only) so expired rows can
be pruned. Council receipts remain the immutable audit trail.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

_LOCK = threading.RLock()
_SCHEMA = "xcmax.retort_clarification_session/v1"
_STATUS_OPEN = "open"
_STATUS_ANSWERED = "answered"
_STATUS_EXPIRED = "expired"
_STATUS_CANCELLED = "cancelled"
_STATUS_RESOLVED = "resolved"
_TERMINAL = {_STATUS_ANSWERED, _STATUS_EXPIRED, _STATUS_CANCELLED, _STATUS_RESOLVED}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _text(value: Any, limit: int = 4000) -> str:
    return str(value or "").strip()[:limit]


def _runtime_dir() -> Path:
    return Path(os.environ.get("MODSTORE_RUNTIME_DIR") or "/tmp/modstore_runtime").expanduser()


def clarification_ledger_path() -> Path:
    configured = _text(os.environ.get("MODSTORE_RETORT_CLARIFICATION_LEDGER"), 4096)
    if configured:
        return Path(configured).expanduser()
    return _runtime_dir() / "retort_clarification_sessions.json"


def ttl_seconds() -> int:
    try:
        return max(30, int(os.environ.get("MODSTORE_RETORT_CLARIFICATION_TTL_SECONDS") or "1800"))
    except ValueError:
        return 1800


def max_open_sessions() -> int:
    try:
        return max(1, int(os.environ.get("MODSTORE_RETORT_CLARIFICATION_MAX_OPEN") or "50"))
    except ValueError:
        return 50


def expire_fallback() -> str:
    """fail_closed | cancel | degrade_intent"""
    raw = _text(os.environ.get("MODSTORE_RETORT_CLARIFICATION_EXPIRE_FALLBACK") or "fail_closed", 32)
    return raw if raw in {"fail_closed", "cancel", "degrade_intent"} else "fail_closed"


def gate_enabled() -> bool:
    return _text(os.environ.get("MODSTORE_RETORT_CLARIFICATION_ENABLED") or "1", 16).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _subject_key(
    *,
    change_request_id: int | None = None,
    proposal_id: str = "",
    run_id: str = "",
    package_id: str = "",
) -> str:
    if change_request_id and int(change_request_id) > 0:
        return f"cr:{int(change_request_id)}"
    parts = [p for p in (_text(proposal_id, 128), _text(run_id, 128), _text(package_id, 128)) if p]
    return "council:" + "|".join(parts) if parts else f"anon:{uuid.uuid4().hex[:12]}"


def _fingerprint(subject: str, strategy_intent: str, paths: Sequence[str]) -> str:
    raw = json.dumps(
        {"subject": subject, "intent": strategy_intent, "paths": list(paths)[:20]},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _load_store_unlocked() -> dict[str, Any]:
    path = clarification_ledger_path()
    if not path.is_file():
        return {"schema": _SCHEMA, "sessions": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": _SCHEMA, "sessions": {}}
    if not isinstance(data, dict):
        return {"schema": _SCHEMA, "sessions": {}}
    sessions = data.get("sessions")
    if not isinstance(sessions, dict):
        sessions = {}
    return {"schema": _SCHEMA, "sessions": sessions}


def _save_store_unlocked(store: Mapping[str, Any]) -> None:
    path = clarification_ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "schema": _SCHEMA,
        "updated_at": _now_iso(),
        "sessions": dict(store.get("sessions") or {}),
    }
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _parse_iso(value: str) -> Optional[datetime]:
    text = _text(value, 64)
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _paths_from_changed(changed_files: Sequence[Any] | None) -> list[str]:
    out: list[str] = []
    for item in changed_files or []:
        if isinstance(item, str):
            path = item.strip()
        elif isinstance(item, Mapping):
            path = _text(item.get("path"), 1024)
        else:
            path = ""
        if path and path not in out:
            out.append(path)
    return out


def _load_clarification_builder():
    try:
        from retort_engine.clarification import (
            build_clarification_questions,
            clarification_needed,
            enrich_strategy_intent,
        )

        return build_clarification_questions, clarification_needed, enrich_strategy_intent
    except ImportError:
        root = Path(__file__).resolve().parents[3] / "packages" / "retort_engine"
        import sys

        if root.is_dir() and str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from retort_engine.clarification import (
            build_clarification_questions,
            clarification_needed,
            enrich_strategy_intent,
        )

        return build_clarification_questions, clarification_needed, enrich_strategy_intent


def _load_alignment():
    try:
        from retort_engine.intent_alignment import assess_change_intent_alignment

        return assess_change_intent_alignment
    except ImportError:
        root = Path(__file__).resolve().parents[3] / "packages" / "retort_engine"
        import sys

        if root.is_dir() and str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from retort_engine.intent_alignment import assess_change_intent_alignment

        return assess_change_intent_alignment


def _normalize_changed_for_alignment(changed_files: Sequence[Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in changed_files or []:
        if isinstance(item, str):
            path = item.strip()
            if path:
                rows.append({"path": path, "hunks": []})
        elif isinstance(item, Mapping):
            path = _text(item.get("path"), 1024)
            if path:
                rows.append(
                    {
                        "path": path,
                        "hunks": item.get("hunks") if isinstance(item.get("hunks"), list) else [],
                    }
                )
    return rows


def sweep_expired_clarifications(*, now: Optional[datetime] = None) -> dict[str, Any]:
    """Expire open sessions past TTL and prune terminal backlog beyond cap."""

    moment = now or _now()
    expired_ids: list[str] = []
    pruned_ids: list[str] = []
    with _LOCK:
        store = _load_store_unlocked()
        sessions: dict[str, Any] = dict(store.get("sessions") or {})
        for sid, row in list(sessions.items()):
            if not isinstance(row, dict):
                continue
            if row.get("status") != _STATUS_OPEN:
                continue
            expires_at = _parse_iso(str(row.get("expires_at") or ""))
            if expires_at and expires_at <= moment:
                row["status"] = _STATUS_EXPIRED
                row["expired_at"] = moment.isoformat()
                row["expire_fallback"] = expire_fallback()
                row["updated_at"] = moment.isoformat()
                sessions[sid] = row
                expired_ids.append(sid)

        # Keep at most 200 terminal sessions (answered/expired/cancelled/resolved).
        terminals = sorted(
            (
                (sid, row)
                for sid, row in sessions.items()
                if isinstance(row, dict) and row.get("status") in _TERMINAL
            ),
            key=lambda item: str(item[1].get("updated_at") or item[1].get("created_at") or ""),
        )
        overflow = max(0, len(terminals) - 200)
        for sid, _row in terminals[:overflow]:
            sessions.pop(sid, None)
            pruned_ids.append(sid)

        # Hard cap open sessions: expire oldest first.
        opens = sorted(
            (
                (sid, row)
                for sid, row in sessions.items()
                if isinstance(row, dict) and row.get("status") == _STATUS_OPEN
            ),
            key=lambda item: str(item[1].get("created_at") or ""),
        )
        max_open = max_open_sessions()
        while len(opens) > max_open:
            sid, row = opens.pop(0)
            row["status"] = _STATUS_EXPIRED
            row["expired_at"] = moment.isoformat()
            row["expire_reason"] = "max_open_cap"
            row["expire_fallback"] = expire_fallback()
            row["updated_at"] = moment.isoformat()
            sessions[sid] = row
            expired_ids.append(sid)

        store = {"schema": _SCHEMA, "sessions": sessions}
        _save_store_unlocked(store)
    return {
        "ok": True,
        "expired_count": len(expired_ids),
        "expired_ids": expired_ids,
        "pruned_count": len(pruned_ids),
        "pruned_ids": pruned_ids,
        "open_count": sum(
            1
            for row in (_load_store_unlocked().get("sessions") or {}).values()
            if isinstance(row, dict) and row.get("status") == _STATUS_OPEN
        ),
    }


def list_clarifications(
    *,
    include_terminal: bool = False,
    subject: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    sweep_expired_clarifications()
    with _LOCK:
        sessions = _load_store_unlocked().get("sessions") or {}
    rows = []
    for sid, row in sessions.items():
        if not isinstance(row, dict):
            continue
        if subject and row.get("subject") != subject:
            continue
        if not include_terminal and row.get("status") != _STATUS_OPEN:
            continue
        rows.append({"session_id": sid, **row})
    rows.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    bounded = max(1, min(int(limit or 50), 200))
    open_count = sum(1 for row in rows if row.get("status") == _STATUS_OPEN)
    return {
        "ok": True,
        "count": min(len(rows), bounded),
        "open_count": open_count,
        "items": rows[:bounded],
        "ttl_seconds": ttl_seconds(),
        "max_open": max_open_sessions(),
        "expire_fallback": expire_fallback(),
    }


def get_clarification(session_id: str) -> Optional[dict[str, Any]]:
    sweep_expired_clarifications()
    with _LOCK:
        row = (_load_store_unlocked().get("sessions") or {}).get(_text(session_id, 128))
    if not isinstance(row, dict):
        return None
    return {"session_id": _text(session_id, 128), **row}


def answer_clarification(
    session_id: str,
    *,
    answers: Mapping[str, Any] | Sequence[Any] | str,
    answered_by: str = "admin",
) -> dict[str, Any]:
    sweep_expired_clarifications()
    sid = _text(session_id, 128)
    if not sid:
        return {"ok": False, "error": "session_id_missing"}

    if isinstance(answers, str):
        answer_map: dict[str, Any] = {"freeform": answers.strip()}
    elif isinstance(answers, Mapping):
        answer_map = {str(k): v for k, v in answers.items() if str(v or "").strip()}
    else:
        answer_map = {}
        for index, item in enumerate(answers or [], start=1):
            if isinstance(item, Mapping):
                key = _text(item.get("id") or item.get("question_id") or f"q{index}", 64)
                value = _text(item.get("answer") or item.get("text"), 2000)
            else:
                key = f"q{index}"
                value = _text(item, 2000)
            if value:
                answer_map[key] = value
    if not answer_map:
        return {"ok": False, "error": "answers_empty"}

    _, _, enrich = _load_clarification_builder()
    with _LOCK:
        store = _load_store_unlocked()
        sessions = dict(store.get("sessions") or {})
        row = sessions.get(sid)
        if not isinstance(row, dict):
            return {"ok": False, "error": "session_not_found"}
        if row.get("status") != _STATUS_OPEN:
            return {
                "ok": False,
                "error": f"session_not_open:{row.get('status')}",
                "session": {"session_id": sid, **row},
            }
        enriched = enrich(str(row.get("strategy_intent") or ""), answer_map)
        row = {
            **row,
            "status": _STATUS_ANSWERED,
            "answers": answer_map,
            "answered_by": _text(answered_by, 128),
            "answered_at": _now_iso(),
            "enriched_strategy_intent": enriched,
            "updated_at": _now_iso(),
        }
        sessions[sid] = row
        _save_store_unlocked({"schema": _SCHEMA, "sessions": sessions})
    return {"ok": True, "session": {"session_id": sid, **row}}


def cancel_clarification(session_id: str, *, reason: str = "cancelled") -> dict[str, Any]:
    sweep_expired_clarifications()
    sid = _text(session_id, 128)
    with _LOCK:
        store = _load_store_unlocked()
        sessions = dict(store.get("sessions") or {})
        row = sessions.get(sid)
        if not isinstance(row, dict):
            return {"ok": False, "error": "session_not_found"}
        if row.get("status") != _STATUS_OPEN:
            return {"ok": False, "error": f"session_not_open:{row.get('status')}"}
        row = {
            **row,
            "status": _STATUS_CANCELLED,
            "cancel_reason": _text(reason, 500),
            "cancelled_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        sessions[sid] = row
        _save_store_unlocked({"schema": _SCHEMA, "sessions": sessions})
    return {"ok": True, "session": {"session_id": sid, **row}}


def mark_clarification_resolved(session_id: str) -> dict[str, Any]:
    sid = _text(session_id, 128)
    with _LOCK:
        store = _load_store_unlocked()
        sessions = dict(store.get("sessions") or {})
        row = sessions.get(sid)
        if not isinstance(row, dict):
            return {"ok": False, "error": "session_not_found"}
        if row.get("status") not in {_STATUS_ANSWERED, _STATUS_RESOLVED}:
            return {"ok": False, "error": f"session_not_answerable:{row.get('status')}"}
        row = {**row, "status": _STATUS_RESOLVED, "resolved_at": _now_iso(), "updated_at": _now_iso()}
        sessions[sid] = row
        _save_store_unlocked({"schema": _SCHEMA, "sessions": sessions})
    return {"ok": True, "session": {"session_id": sid, **row}}


def open_clarification_session(
    *,
    strategy_intent: str,
    changed_files: Sequence[Any] | None = None,
    change_request_id: int | None = None,
    proposal_id: str = "",
    run_id: str = "",
    package_id: str = "",
    source: str = "retort_gate",
    force: bool = False,
) -> dict[str, Any]:
    """Open or reuse a clarification session. Always sweeps first."""

    if not gate_enabled():
        return {"ok": True, "opened": False, "reason": "disabled"}

    sweep = sweep_expired_clarifications()
    paths = _paths_from_changed(changed_files)
    subject = _subject_key(
        change_request_id=change_request_id,
        proposal_id=proposal_id,
        run_id=run_id,
        package_id=package_id,
    )
    intent = _text(strategy_intent, 4000)
    assess = _load_alignment()
    assessment = assess(_normalize_changed_for_alignment(changed_files), issue_context=intent)
    build_questions, needed, _enrich = _load_clarification_builder()
    if not force and not needed(assessment, intent):
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
    fp = _fingerprint(subject, intent, paths)
    expires = _now() + timedelta(seconds=ttl_seconds())

    with _LOCK:
        store = _load_store_unlocked()
        sessions = dict(store.get("sessions") or {})
        # Reuse open session for same subject+fingerprint.
        for sid, row in sessions.items():
            if not isinstance(row, dict):
                continue
            if row.get("status") != _STATUS_OPEN:
                continue
            if row.get("subject") == subject and row.get("fingerprint") == fp:
                return {
                    "ok": True,
                    "opened": False,
                    "reused": True,
                    "session": {"session_id": sid, **row},
                    "sweep": sweep,
                }
        # Supersede older open sessions for the same subject.
        for sid, row in list(sessions.items()):
            if (
                isinstance(row, dict)
                and row.get("status") == _STATUS_OPEN
                and row.get("subject") == subject
            ):
                row = {
                    **row,
                    "status": _STATUS_CANCELLED,
                    "cancel_reason": "superseded",
                    "cancelled_at": _now_iso(),
                    "updated_at": _now_iso(),
                }
                sessions[sid] = row

        sid = f"rcl-{uuid.uuid4().hex[:16]}"
        row = {
            "schema": _SCHEMA,
            "status": _STATUS_OPEN,
            "subject": subject,
            "fingerprint": fp,
            "source": _text(source, 64),
            "strategy_intent": intent,
            "changed_files": paths[:40],
            "change_request_id": int(change_request_id or 0) or None,
            "proposal_id": _text(proposal_id, 128),
            "run_id": _text(run_id, 128),
            "package_id": _text(package_id, 128),
            "assessment_status": assessment.get("status"),
            "missing_keywords": list(assessment.get("missing_keywords") or [])[:12],
            "questions": questions,
            "answers": {},
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "expires_at": expires.isoformat(),
            "ttl_seconds": ttl_seconds(),
        }
        sessions[sid] = row
        _save_store_unlocked({"schema": _SCHEMA, "sessions": sessions})

    # Soft notify via uncertainty queue (non-blocking, deduped).
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
    except Exception:
        pass

    return {
        "ok": True,
        "opened": True,
        "reused": False,
        "session": {"session_id": sid, **row},
        "sweep": sweep,
    }


def open_clarification_for_change_request(
    change_request_id: int,
    *,
    strategy_intent: str = "",
    changed_files: Sequence[Any] | None = None,
    source_employee_id: str = "",
) -> dict[str, Any]:
    intent = _text(strategy_intent, 4000)
    if not intent:
        intent = f"审批变更请求 CR#{int(change_request_id)}"
        if source_employee_id:
            intent = f"{intent}（来源员工 {source_employee_id}）"
    return open_clarification_session(
        strategy_intent=intent,
        changed_files=changed_files,
        change_request_id=int(change_request_id),
        package_id="change-request",
        source="change_request.created",
        force=False,
    )


def _latest_session_for_subject(subject: str) -> Optional[dict[str, Any]]:
    with _LOCK:
        sessions = _load_store_unlocked().get("sessions") or {}
    rows = [
        {"session_id": sid, **row}
        for sid, row in sessions.items()
        if isinstance(row, dict) and row.get("subject") == subject
    ]
    if not rows:
        return None
    rows.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
    return rows[0]


def evaluate_retort_clarification_gate(
    *,
    strategy_intent: str,
    changed_files: Sequence[Any] | None = None,
    change_request_id: int | None = None,
    proposal_id: str = "",
    run_id: str = "",
    package_id: str = "",
    auto_open: bool = True,
) -> dict[str, Any]:
    """Evaluate Retort seat with clarification loop.

    Returns effective strategy_intent, alignment assessment, blockers, and
    clarification session summary. Never leaves stale open sessions un-swept.
    """

    sweep = sweep_expired_clarifications()
    if not gate_enabled():
        assess = _load_alignment()
        assessment = assess(
            _normalize_changed_for_alignment(changed_files),
            issue_context=_text(strategy_intent, 4000),
        )
        return {
            "ok": True,
            "enabled": False,
            "effective_strategy_intent": _text(strategy_intent, 4000),
            "assessment": assessment,
            "blockers": [],
            "clarification": None,
            "sweep": sweep,
        }

    subject = _subject_key(
        change_request_id=change_request_id,
        proposal_id=proposal_id,
        run_id=run_id,
        package_id=package_id,
    )
    session = _latest_session_for_subject(subject)
    intent = _text(strategy_intent, 4000)
    blockers: list[str] = []

    if session and session.get("status") == _STATUS_ANSWERED:
        intent = _text(session.get("enriched_strategy_intent") or intent, 4000)
    elif session and session.get("status") == _STATUS_OPEN:
        blockers.append("retort_clarification_pending")
    elif session and session.get("status") == _STATUS_EXPIRED:
        fallback = _text(session.get("expire_fallback") or expire_fallback(), 32)
        if fallback == "degrade_intent":
            # Proceed with original intent; still re-assess below.
            pass
        elif fallback == "cancel":
            blockers.append("retort_clarification_cancelled")
        else:
            blockers.append("retort_clarification_expired")

    assess = _load_alignment()
    assessment = assess(_normalize_changed_for_alignment(changed_files), issue_context=intent)
    _, needed, _ = _load_clarification_builder()

    if (
        auto_open
        and "retort_clarification_pending" not in blockers
        and "retort_clarification_expired" not in blockers
        and "retort_clarification_cancelled" not in blockers
        and needed(assessment, intent)
        and not (session and session.get("status") == _STATUS_ANSWERED)
    ):
        opened = open_clarification_session(
            strategy_intent=intent,
            changed_files=changed_files,
            change_request_id=change_request_id,
            proposal_id=proposal_id,
            run_id=run_id,
            package_id=package_id,
            source="council_evaluate",
        )
        session = opened.get("session") if isinstance(opened.get("session"), dict) else session
        if opened.get("opened") or opened.get("reused"):
            blockers.append("retort_clarification_pending")

    # Re-assess after answered enrichment path.
    if session and session.get("status") == _STATUS_ANSWERED:
        assessment = assess(_normalize_changed_for_alignment(changed_files), issue_context=intent)
        if assessment.get("status") == "aligned" and session.get("session_id"):
            mark_clarification_resolved(str(session.get("session_id")))
            session = get_clarification(str(session.get("session_id"))) or session

    aligned = assessment.get("status") == "aligned" and "retort_clarification_pending" not in blockers
    if assessment.get("status") == "misaligned" and "retort_clarification_pending" not in blockers:
        blockers.append("retort_intent_misaligned")

    return {
        "ok": True,
        "enabled": True,
        "aligned": aligned,
        "effective_strategy_intent": intent,
        "assessment": assessment,
        "blockers": list(dict.fromkeys(blockers)),
        "clarification": session,
        "sweep": sweep_expired_clarifications() if sweep.get("expired_count") else sweep,
    }


def clarification_blocks_auto_approve(change_request_id: int) -> dict[str, Any]:
    """Return blocking info for maybe_auto_approve."""

    sweep_expired_clarifications()
    subject = _subject_key(change_request_id=int(change_request_id))
    session = _latest_session_for_subject(subject)
    if not session:
        return {"blocked": False, "reason": "no_session"}
    status = str(session.get("status") or "")
    if status == _STATUS_OPEN:
        return {
            "blocked": True,
            "reason": "retort_clarification_pending",
            "session_id": session.get("session_id"),
            "expires_at": session.get("expires_at"),
        }
    if status == _STATUS_EXPIRED and expire_fallback() != "degrade_intent":
        return {
            "blocked": True,
            "reason": "retort_clarification_expired",
            "session_id": session.get("session_id"),
        }
    if status == _STATUS_CANCELLED and str(session.get("cancel_reason") or "") != "superseded":
        return {
            "blocked": True,
            "reason": "retort_clarification_cancelled",
            "session_id": session.get("session_id"),
        }
    return {"blocked": False, "reason": f"status={status}", "session_id": session.get("session_id")}


__all__ = [
    "answer_clarification",
    "cancel_clarification",
    "clarification_blocks_auto_approve",
    "clarification_ledger_path",
    "evaluate_retort_clarification_gate",
    "gate_enabled",
    "get_clarification",
    "list_clarifications",
    "mark_clarification_resolved",
    "open_clarification_for_change_request",
    "open_clarification_session",
    "sweep_expired_clarifications",
    "ttl_seconds",
]
