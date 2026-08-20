# mypy: disable-error-code="assignment, union-attr"
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
from datetime import UTC, datetime
from datetime import timedelta as timedelta
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.retort_clarification_operations import (
    _latest_session_for_subject as _latest_session_for_subject,
)
from modstore_server.retort_clarification_operations import (
    _mirror_to_boss_inbox as _mirror_to_boss_inbox,
)
from modstore_server.retort_clarification_operations import (
    answer_clarification as answer_clarification,
)
from modstore_server.retort_clarification_operations import (
    cancel_clarification as cancel_clarification,
)
from modstore_server.retort_clarification_operations import (
    clarification_blocks_auto_approve as clarification_blocks_auto_approve,
)
from modstore_server.retort_clarification_operations import (
    evaluate_retort_clarification_gate as evaluate_retort_clarification_gate,
)
from modstore_server.retort_clarification_operations import (
    mark_clarification_resolved as mark_clarification_resolved,
)
from modstore_server.retort_clarification_operations import (
    open_clarification_for_change_request as open_clarification_for_change_request,
)
from modstore_server.retort_clarification_operations import (
    open_clarification_session as open_clarification_session,
)

_LOCK = threading.RLock()
_SCHEMA = "xcmax.retort_clarification_session/v1"
_STATUS_OPEN = "open"
_STATUS_ANSWERED = "answered"
_STATUS_EXPIRED = "expired"
_STATUS_CANCELLED = "cancelled"
_STATUS_RESOLVED = "resolved"
_TERMINAL = {_STATUS_ANSWERED, _STATUS_EXPIRED, _STATUS_CANCELLED, _STATUS_RESOLVED}


def _now() -> datetime:
    return datetime.now(UTC)


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
        return max(
            30,
            int(os.environ.get("MODSTORE_RETORT_CLARIFICATION_TTL_SECONDS") or "1800"),
        )
    except ValueError:
        return 1800


def max_open_sessions() -> int:
    try:
        return max(1, int(os.environ.get("MODSTORE_RETORT_CLARIFICATION_MAX_OPEN") or "50"))
    except ValueError:
        return 50


def expire_fallback() -> str:
    """fail_closed | cancel | degrade_intent"""
    raw = _text(
        os.environ.get("MODSTORE_RETORT_CLARIFICATION_EXPIRE_FALLBACK") or "fail_closed",
        32,
    )
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
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
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
        dt = dt.replace(tzinfo=UTC)
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

        return (
            build_clarification_questions,
            clarification_needed,
            enrich_strategy_intent,
        )
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

        return (
            build_clarification_questions,
            clarification_needed,
            enrich_strategy_intent,
        )


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


def _normalize_changed_for_alignment(
    changed_files: Sequence[Any] | None,
) -> list[dict[str, Any]]:
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


def _public_session(
    session_id: str, row: Mapping[str, Any], *, now: Optional[datetime] = None
) -> dict[str, Any]:
    moment = now or _now()
    expires_at = _parse_iso(str(row.get("expires_at") or ""))
    seconds_remaining = None
    urgency = "none"
    if row.get("status") == _STATUS_OPEN and expires_at is not None:
        seconds_remaining = max(0, int((expires_at - moment).total_seconds()))
        if seconds_remaining <= 0:
            urgency = "expired"
        elif seconds_remaining <= 300:
            urgency = "critical"
        elif seconds_remaining <= 900:
            urgency = "soon"
        else:
            urgency = "normal"
    questions = row.get("questions") if isinstance(row.get("questions"), list) else []
    return {
        "session_id": session_id,
        **dict(row),
        "questions": questions,
        "seconds_remaining": seconds_remaining,
        "urgency": urgency,
        "blocking_question_ids": [
            _text(item.get("id"), 64)
            for item in questions
            if isinstance(item, Mapping)
            and item.get("blocking") is not False
            and _text(item.get("id"), 64)
        ],
    }


def _expire_boss_inbox_for_sessions(session_ids: Sequence[str]) -> int:
    """Mark mirrored Phase-D questions expired when clarification sessions expire."""

    ids = [str(sid).strip() for sid in session_ids if str(sid).strip()]
    if not ids:
        return 0
    try:
        from modstore_server.models import PendingHumanQuestion, get_session_factory
    except RECOVERABLE_ERRORS:
        return 0
    fingerprints = [
        hashlib.sha256(f"retort-clarification:{sid}".encode()).hexdigest()[:32] for sid in ids
    ]
    expired = 0
    try:
        sf = get_session_factory()
        with sf() as session:
            rows = (
                session.query(PendingHumanQuestion)
                .filter(PendingHumanQuestion.status == "pending")
                .filter(PendingHumanQuestion.fingerprint.in_(fingerprints))
                .all()
            )
            now = _now()
            for row in rows:
                row.status = "expired"
                if not row.answered_at:
                    row.answered_at = now
                expired += 1
            if expired:
                session.commit()
    except RECOVERABLE_ERRORS:
        return 0
    return expired


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
    inbox_expired = _expire_boss_inbox_for_sessions(expired_ids)
    return {
        "ok": True,
        "expired_count": len(expired_ids),
        "expired_ids": expired_ids,
        "pruned_count": len(pruned_ids),
        "pruned_ids": pruned_ids,
        "boss_inbox_expired_count": inbox_expired,
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
    moment = _now()
    for sid, row in sessions.items():
        if not isinstance(row, dict):
            continue
        if subject and row.get("subject") != subject:
            continue
        if not include_terminal and row.get("status") != _STATUS_OPEN:
            continue
        rows.append(_public_session(sid, row, now=moment))
    rows.sort(
        key=lambda item: (
            0 if item.get("status") == _STATUS_OPEN else 1,
            (
                item.get("seconds_remaining")
                if isinstance(item.get("seconds_remaining"), int)
                else 10**9
            ),
            str(item.get("created_at") or ""),
        )
    )
    bounded = max(1, min(int(limit or 50), 200))
    open_count = sum(1 for row in rows if row.get("status") == _STATUS_OPEN)
    critical_count = sum(1 for row in rows if row.get("urgency") == "critical")
    return {
        "ok": True,
        "count": min(len(rows), bounded),
        "open_count": open_count,
        "critical_count": critical_count,
        "healthy": open_count == 0,
        "items": rows[:bounded],
        "ttl_seconds": ttl_seconds(),
        "max_open": max_open_sessions(),
        "expire_fallback": expire_fallback(),
    }


def get_clarification(session_id: str) -> Optional[dict[str, Any]]:
    sweep_expired_clarifications()
    sid = _text(session_id, 128)
    with _LOCK:
        row = (_load_store_unlocked().get("sessions") or {}).get(sid)
    if not isinstance(row, dict):
        return None
    return _public_session(sid, row)


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
