"""Durable, owner-scoped conversation history for desktop agent tasks."""

from __future__ import annotations

import json
from datetime import datetime
from html.parser import HTMLParser
from typing import Any

from app.db.models import AIConversation, AIConversationSession
from app.db.session import get_db
from app.domain.shared_services.conversation_service import (
    ConversationRevisionError as ConversationRevisionError,
)
from app.domain.shared_services.conversation_service import (
    begin_conversation_write,
    lock_conversation_session,
)


def durable_user_id(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text.isdigit():
        return None
    parsed = int(text)
    return parsed if parsed > 0 else None


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _plain_text(value: Any) -> str:
    parser = _PlainTextParser()
    parser.feed(str(value or ""))
    parser.close()
    return "".join(parser.parts).strip()


def _session_row(session: AIConversationSession) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "revision": int(session.revision or 0),
        "title": session.title,
        "summary": session.summary or "",
        "message_count": int(session.message_count or 0),
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "last_message_at": (
            session.last_message_at.isoformat() if session.last_message_at else None
        ),
    }


def _message_row(message: AIConversation) -> dict[str, Any]:
    return {
        "id": message.id,
        "session_id": message.session_id,
        "role": message.role,
        "content": message.content,
        "intent": message.intent or "",
        "metadata": message.conversation_metadata or "",
        "timestamp": message.created_at.isoformat() if message.created_at else None,
    }


def _message_suffix(db: Any, session_id: str, user_id: int, message_id: int):
    return db.query(AIConversation).filter(
        AIConversation.session_id == session_id,
        AIConversation.user_id == str(user_id),
        AIConversation.id >= message_id,
    )


class TaskConversationStore:
    """Persist task chat turns without allowing cross-user session access."""

    def save_message(
        self,
        *,
        session_id: str,
        user_id: int,
        role: str,
        content: str,
        intent: str = "",
        metadata: str = "",
        client_message_id: str = "",
        expected_revision: int | None = None,
    ) -> int:
        from app.application.ai_chat.conversation_history import strip_client_recall_binding

        metadata = strip_client_recall_binding(metadata)
        now = datetime.now()
        with get_db() as db:
            begin_conversation_write(db)
            session = lock_conversation_session(
                db,
                session_id=session_id,
                user_id=user_id,
                expected_revision=expected_revision,
                create=True,
            )

            if client_message_id:
                marker = json.dumps({"client_message_id": client_message_id})[1:-1]
                candidates = (
                    db.query(AIConversation)
                    .filter(
                        AIConversation.session_id == session_id,
                        AIConversation.user_id == str(user_id),
                        AIConversation.conversation_metadata.contains(marker, autoescape=True),
                    )
                    .all()
                )
                for candidate in candidates:
                    try:
                        prior = json.loads(candidate.conversation_metadata or "{}")
                    except (TypeError, ValueError):
                        continue
                    if (
                        isinstance(prior, dict)
                        and prior.get("client_message_id") == client_message_id
                    ):
                        if candidate.role != role or candidate.content != content:
                            raise ValueError("message retry does not match the original content")
                        return int(candidate.id)
                try:
                    payload = json.loads(metadata or "{}")
                except (TypeError, ValueError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                payload["client_message_id"] = client_message_id
                metadata = json.dumps(payload, ensure_ascii=False)

            message = AIConversation(
                session_id=session_id,
                user_id=str(user_id),
                role=role,
                content=content,
                intent=intent,
                conversation_metadata=metadata,
                created_at=now,
            )
            db.add(message)
            session.message_count = int(session.message_count or 0) + 1
            session.last_message_at = now
            plain = _plain_text(content).replace("\n", " ")
            session.summary = f"{plain[:120]}…" if len(plain) > 120 else plain
            if not session.title and role == "user" and plain:
                session.title = f"{plain[:48]}…" if len(plain) > 48 else plain
            db.commit()
            db.refresh(message)
            return int(message.id)

    def get_conversation(
        self,
        *,
        session_id: str,
        user_id: int,
        limit: int = 50,
        before_id: int | None = None,
        after_id: int | None = None,
        turn_id: str | None = None,
        through_id: int | None = None,
    ) -> dict[str, Any]:
        """Owner-scoped keyset page; the initial page contains the newest messages."""
        from sqlalchemy import or_

        if before_id is not None and after_id is not None:
            raise ValueError("before_id and after_id are mutually exclusive")
        limit = max(1, min(int(limit), 200))
        with get_db() as db:
            session = (
                db.query(AIConversationSession)
                .filter(
                    AIConversationSession.session_id == session_id,
                    AIConversationSession.user_id == user_id,
                    AIConversationSession.deleted_at.is_(None),
                )
                .first()
            )
            if session is None:
                return {
                    "session": None,
                    "messages": [],
                    "has_more": False,
                    "next_before_id": None,
                    "next_after_id": None,
                }
            query = db.query(AIConversation).filter(
                AIConversation.session_id == session_id,
                AIConversation.user_id == str(user_id),
            )
            newest = (
                query.with_entities(AIConversation.id).order_by(AIConversation.id.desc()).first()
            )
            snapshot_latest_id = int(newest.id) if newest else 0
            if before_id is not None:
                query = query.filter(AIConversation.id < before_id)
            if after_id is not None:
                query = query.filter(AIConversation.id > after_id)
            if through_id is not None:
                query = query.filter(AIConversation.id <= through_id)
            if turn_id:
                markers = [
                    json.dumps({key: turn_id}, ensure_ascii=False, separators=sep)[1:-1]
                    for key in ("turn_id", "turnId")
                    for sep in ((",", ":"), (", ", ": "))
                ]
                query = query.filter(
                    or_(
                        *(
                            AIConversation.conversation_metadata.contains(marker, autoescape=True)
                            for marker in markers
                        )
                    )
                )
            ascending = after_id is not None
            rows = (
                query.order_by(AIConversation.id.asc() if ascending else AIConversation.id.desc())
                .limit(limit + 1)
                .all()
            )
            more = len(rows) > limit
            rows = rows[:limit]
            if not ascending:
                rows.reverse()
            return {
                "session": _session_row(session),
                "messages": [_message_row(row) for row in rows],
                "has_more": more,
                "next_before_id": int(rows[0].id) if more and rows and not ascending else None,
                "next_after_id": int(rows[-1].id) if more and rows and ascending else None,
                "snapshot_latest_id": snapshot_latest_id,
            }

    def iter_conversation_messages(self, *, session_id: str, user_id: int, batch_size: int = 200):
        """Read an authorized, bounded snapshot without an unbounded SQL .all()."""
        from app.domain.shared_services.conversation_service import ConversationRevisionError

        cursor, revision, through = 0, None, None
        while True:
            page = self.get_conversation(
                session_id=session_id,
                user_id=user_id,
                limit=batch_size,
                after_id=cursor,
                through_id=through,
            )
            session = page["session"]
            if session is None:
                if revision is not None:
                    raise ConversationRevisionError("conversation changed during history read")
                return
            current = int(session.get("revision") or 0)
            if revision is not None and current != revision:
                raise ConversationRevisionError("conversation changed during history read")
            revision = current
            if through is None:
                through = page["snapshot_latest_id"]
            yield from page["messages"]
            if not page["has_more"]:
                return
            cursor = page["next_after_id"]

    def get_history(
        self, *, session_id: str, user_id: int, mod_id: str = "", **pagination
    ) -> dict[str, Any]:
        page = self.get_conversation(session_id=session_id, user_id=user_id, **pagination)
        session = page.pop("session")
        active_turn = None
        if isinstance(session, dict) and type(session.get("revision")) is int:
            from app.application.elt.batch_continuation import active_batch_turn
            from app.infrastructure.tenant_scope import current_tenant_id

            active_turn = active_batch_turn(
                owner=str(user_id),
                tenant=str(current_tenant_id() or ""),
                mod=mod_id,
                session=session_id,
                revision=session["revision"],
                turn_id=pagination.get("turn_id"),
            )
        return {
            "success": True,
            "id": session_id,
            "title": session.get("title") if isinstance(session, dict) else None,
            "revision": session.get("revision") if isinstance(session, dict) else None,
            "mod_id": mod_id,
            **page,
            **({"active_turn": active_turn} if active_turn else {}),
            "metadata": {},
            "durable": True,
        }

    def list_sessions(self, *, user_id: int, limit: int, offset: int = 0) -> list[dict[str, Any]]:
        with get_db() as db:
            sessions = (
                db.query(AIConversationSession)
                .filter(
                    AIConversationSession.user_id == user_id,
                    AIConversationSession.deleted_at.is_(None),
                )
                .order_by(
                    AIConversationSession.last_message_at.desc(),
                    AIConversationSession.id.desc(),
                )
                .offset(offset)
                .limit(limit)
                .all()
            )
            rows: list[dict[str, Any]] = []
            changed = False
            for session in sessions:
                if not (session.title or "").strip():
                    first_user = (
                        db.query(AIConversation)
                        .filter(
                            AIConversation.session_id == session.session_id,
                            AIConversation.role == "user",
                        )
                        .order_by(AIConversation.id.asc())
                        .first()
                    )
                    plain = _plain_text(first_user.content if first_user else "").replace("\n", " ")
                    if plain:
                        session.title = f"{plain[:48]}…" if len(plain) > 48 else plain
                        changed = True
                rows.append(_session_row(session))
            if changed:
                db.commit()
            return rows

    def prepare_revision(
        self, *, session_id: str, user_id: int, expected_revision: int | None = None
    ) -> int:
        """Register first turns before execution so clear/delete can fence them."""
        with get_db() as db:
            begin_conversation_write(db)
            session = lock_conversation_session(
                db,
                session_id=session_id,
                user_id=user_id,
                expected_revision=expected_revision,
                create=True,
            )
            revision = int(session.revision)
            db.commit()
            return revision

    def memory_snapshot(
        self,
        *,
        session_id: str,
        user_id: int,
        include_messages: bool = False,
    ) -> dict[str, Any] | None:
        """The SQL lifecycle and surviving transcript are the projection authority."""
        with get_db() as db:
            session = (
                db.query(AIConversationSession)
                .filter(
                    AIConversationSession.session_id == session_id,
                    AIConversationSession.user_id == user_id,
                    AIConversationSession.deleted_at.is_(None),
                )
                .first()
            )
            if session is None:
                return None
            messages = (
                (
                    db.query(AIConversation)
                    .filter(AIConversation.session_id == session_id)
                    .order_by(AIConversation.id.desc())
                    .limit(400)
                    .all()
                )
                if include_messages
                else []
            )
            return {
                "revision": int(session.revision),
                "messages": [_message_row(message) for message in reversed(messages)],
            }

    def delete_session(self, *, session_id: str, user_id: int) -> bool:
        """Retain an owner-scoped tombstone, including IDs whose first turn is pending."""
        with get_db() as db:
            begin_conversation_write(db)
            previous = (
                db.query(AIConversationSession)
                .filter(AIConversationSession.session_id == session_id)
                .with_for_update()
                .first()
            )
            if previous is not None and (
                previous.user_id != user_id or previous.deleted_at is not None
            ):
                return False
            session = lock_conversation_session(
                db,
                session_id=session_id,
                user_id=user_id,
                create=True,
            )
            db.query(AIConversation).filter(
                AIConversation.session_id == session_id,
            ).delete(synchronize_session=False)
            session.revision += 1
            session.deleted_at = datetime.now()
            session.message_count = 0
            session.title = session.summary = None
            db.commit()
            return previous is not None

    def recall_snapshot(
        self, *, session_id: str, user_id: int, message_id: int
    ) -> tuple[int, list[dict[str, Any]]]:
        with get_db() as db:
            session = lock_conversation_session(db, session_id=session_id, user_id=user_id)
            suffix = _message_suffix(db, session_id, user_id, message_id)
            rows = suffix.order_by(AIConversation.id).limit(1001).all()
            if not rows or rows[0].id != message_id or rows[0].role != "user":
                raise PermissionError("只能撤回当前会话中自己发送的消息")
            if len(rows) > 1000:
                raise ConversationRevisionError("撤回范围过大，请从更近的消息开始")
            return int(session.revision or 0), [_message_row(row) for row in rows]

    def delete_messages_from(
        self, *, session_id: str, user_id: int, message_id: int,
        expected_revision: int | None = None, expected_ids: tuple[int, ...] | None = None,
    ) -> int:
        """Withdraw a user turn and fence every completion based on the old transcript."""
        with get_db() as db:
            begin_conversation_write(db)
            session = lock_conversation_session(
                db, session_id=session_id, user_id=user_id, expected_revision=expected_revision,
            )
            suffix = _message_suffix(db, session_id, user_id, message_id)
            target = suffix.filter(AIConversation.id == message_id).first()
            if target is None or target.role != "user":
                raise PermissionError("only user messages can be withdrawn")
            if expected_ids is not None:
                current = tuple(row.id for row in suffix.with_entities(AIConversation.id)
                                .order_by(AIConversation.id).limit(len(expected_ids) + 1))
                if current != expected_ids:
                    raise ConversationRevisionError("会话已有新消息，撤回范围已变更")
            deleted = suffix.delete(synchronize_session=False)
            session.revision += 1
            session.message_count = (
                db.query(AIConversation).filter(AIConversation.session_id == session_id).count()
            )
            last = (
                db.query(AIConversation)
                .filter(AIConversation.session_id == session_id)
                .order_by(AIConversation.id.desc())
                .first()
            )
            session.last_message_at = last.created_at if last else None
            plain = _plain_text(last.content if last else "").replace("\n", " ")
            session.summary = f"{plain[:120]}…" if len(plain) > 120 else plain
            db.commit()
            return int(deleted or 0)

    def clear_sessions(self, *, user_id: int) -> int:
        with get_db() as db:
            begin_conversation_write(db)
            sessions = (
                db.query(AIConversationSession)
                .filter(
                    AIConversationSession.user_id == user_id,
                    AIConversationSession.deleted_at.is_(None),
                )
                .with_for_update()
                .all()
            )
            for session in sessions:
                db.query(AIConversation).filter(
                    AIConversation.session_id == session.session_id,
                ).delete(synchronize_session=False)
                session.revision += 1
                session.deleted_at = datetime.now()
                session.message_count = 0
                session.title = session.summary = None
            db.commit()
            return len(sessions)


task_conversation_store = TaskConversationStore()
