"""SQLAlchemy fencing shared by history writers and conversation lifecycle actions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import AIConversationSession


class ConversationRevisionError(ValueError):
    """The conversation was deleted or changed after this turn started."""


def begin_conversation_write(db: Session) -> None:
    # SQLite ignores FOR UPDATE. Reserve its write transaction before reading.
    if db.get_bind().dialect.name == "sqlite":
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")


def lock_conversation_session(
    db: Session,
    *,
    session_id: str,
    user_id: int | None,
    expected_revision: int | None = None,
    create: bool = False,
) -> AIConversationSession:
    query = db.query(AIConversationSession).filter(AIConversationSession.session_id == session_id)
    session = query.with_for_update().first()
    if session is None:
        if not create or expected_revision not in (None, 0):
            raise ConversationRevisionError("conversation no longer exists")
        try:
            with db.begin_nested():
                session = AIConversationSession(
                    session_id=session_id,
                    user_id=user_id,
                    revision=0,
                    message_count=0,
                    created_at=datetime.now(),
                )
                db.add(session)
                db.flush()
        except IntegrityError:
            session = query.with_for_update().one()
    if session.user_id != user_id:
        raise PermissionError("conversation session belongs to another user")
    if session.deleted_at is not None:
        raise ConversationRevisionError("conversation was deleted")
    if expected_revision is not None and session.revision != expected_revision:
        raise ConversationRevisionError("conversation changed after this turn started")
    return session
