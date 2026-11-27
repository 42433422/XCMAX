"""Keep host-authored employee execution memory outside the public transcript."""

import hashlib
import json

from sqlalchemy import String, and_, case, cast, func
from sqlalchemy.dialects.postgresql import JSONB

from app.db.models import AIConversation, AIConversationSession

EMPLOYEE_MEMORY_PREFIX = "employee-memory:"
EMPLOYEE_MEMORY_SOURCE = {
    "source": "employee_task",
    "source_component": "employee_runtime",
    "evidence_kind": "execution_summary",
}


def employee_memory_session(session_id: str, user_id: str, tenant_id: str, employee_id: str) -> str:
    scope = json.dumps([tenant_id, user_id, employee_id, session_id], ensure_ascii=False)
    return EMPLOYEE_MEMORY_PREFIX + hashlib.sha256(scope.encode()).hexdigest()


def is_employee_memory(metadata: object) -> bool:
    return isinstance(metadata, dict) and all(
        metadata.get(k) == v for k, v in EMPLOYEE_MEMORY_SOURCE.items()
    )


def employee_memory_rows(db, **scope: str):
    raw = AIConversation.conversation_metadata
    if db.get_bind().dialect.name == "postgresql":
        doc = cast(case((func.pg_input_is_valid(raw, "jsonb"), raw), else_="{}"), JSONB)
        fields = [doc[k].astext == v for k, v in (EMPLOYEE_MEMORY_SOURCE | scope).items()]
    else:
        doc = case((func.json_valid(raw), raw), else_="{}")
        fields = [
            cast(func.json_extract(doc, f"$.{k}"), String) == v
            for k, v in (EMPLOYEE_MEMORY_SOURCE | scope).items()
        ]
    return func.coalesce(and_(*fields), False)


def public_messages(db):
    return and_(
        ~AIConversation.session_id.startswith(EMPLOYEE_MEMORY_PREFIX),
        ~employee_memory_rows(db),
    )


def ordered_public_sessions(db):
    messages = (
        db.query(AIConversation)
        .filter(
            AIConversation.session_id == AIConversationSession.session_id,
            AIConversation.user_id == cast(AIConversationSession.user_id, String),
        )
        .correlate(AIConversationSession)
    )
    public = messages.filter(public_messages(db))
    last = (
        public.with_entities(AIConversation.created_at).order_by(AIConversation.id.desc()).limit(1)
    )
    return (
        db.query(AIConversationSession)
        .filter(
            AIConversationSession.deleted_at.is_(None),
            ~AIConversationSession.session_id.startswith(EMPLOYEE_MEMORY_PREFIX),
            public.exists() | ~messages.exists(),
        )
        .order_by(last.scalar_subquery().desc().nulls_last(), AIConversationSession.id.desc())
    )
