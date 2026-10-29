"""Durable, owner-scoped conversation history for desktop agent tasks."""

from __future__ import annotations

import json
from datetime import datetime
from html.parser import HTMLParser
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.db.models import AIConversation, AIConversationSession
from app.db.session import get_db


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
    ) -> int:
        now = datetime.now()
        with get_db() as db:
            if db.get_bind().dialect.name == "sqlite":
                db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            session_query = db.query(AIConversationSession).filter(
                AIConversationSession.session_id == session_id
            )
            session = (
                db.query(AIConversationSession)
                .filter(AIConversationSession.session_id == session_id)
                .with_for_update()
                .first()
            )
            if session is not None and int(session.user_id or 0) != user_id:
                raise PermissionError("conversation session belongs to another user")
            if session is None:
                try:
                    with db.begin_nested():
                        session = AIConversationSession(
                            session_id=session_id,
                            user_id=user_id,
                            message_count=0,
                            created_at=now,
                        )
                        db.add(session)
                        db.flush()
                except IntegrityError:
                    session = session_query.with_for_update().one()
                    if int(session.user_id or 0) != user_id:
                        raise PermissionError(
                            "conversation session belongs to another user"
                        ) from None

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

    def get_conversation(self, *, session_id: str, user_id: int) -> dict[str, Any]:
        with get_db() as db:
            session = (
                db.query(AIConversationSession)
                .filter(
                    AIConversationSession.session_id == session_id,
                    AIConversationSession.user_id == user_id,
                )
                .first()
            )
            if session is None:
                return {"session": None, "messages": []}
            messages = (
                db.query(AIConversation)
                .filter(
                    AIConversation.session_id == session_id, AIConversation.user_id == str(user_id)
                )
                .order_by(AIConversation.created_at.asc(), AIConversation.id.asc())
                .all()
            )
            return {
                "session": _session_row(session),
                "messages": [_message_row(message) for message in messages],
            }

    def get_history(self, *, session_id: str, user_id: int, mod_id: str = "") -> dict[str, Any]:
        durable = self.get_conversation(session_id=session_id, user_id=user_id)
        session = durable.get("session")
        return {
            "success": True,
            "id": session_id,
            "title": session.get("title") if isinstance(session, dict) else None,
            "mod_id": mod_id,
            "messages": durable.get("messages") or [],
            "metadata": {},
            "durable": True,
        }

    def list_sessions(self, *, user_id: int, limit: int, offset: int = 0) -> list[dict[str, Any]]:
        with get_db() as db:
            sessions = (
                db.query(AIConversationSession)
                .filter(AIConversationSession.user_id == user_id)
                .order_by(
                    AIConversationSession.last_message_at.desc(),
                    AIConversationSession.id.desc(),
                )
                .offset(offset)
                .limit(limit)
                .all()
            )
            return [_session_row(session) for session in sessions]

    def clear_sessions(self, *, user_id: int) -> int:
        with get_db() as db:
            sessions = (
                db.query(AIConversationSession)
                .filter(AIConversationSession.user_id == user_id)
                .all()
            )
            for session in sessions:
                db.delete(session)
            db.commit()
            return len(sessions)


task_conversation_store = TaskConversationStore()
