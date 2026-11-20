"""
对话服务模块

提供对话历史和会话管理的业务逻辑。
"""

import json
import logging
import uuid
from datetime import datetime
from html.parser import HTMLParser
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import AIConversation, AIConversationSession
from app.db.session import get_db
from app.domain.shared_services.mobile_push import notify_user
from app.neuro_bus.event_publisher_mixin import NeuroEventPublisherMixin
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


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


class _MessageTitleParser(HTMLParser):
    """Extract title text from a bounded prefix without a backtracking tag regex."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _message_title(content: str) -> str:
    parser = _MessageTitleParser()
    # A title needs only 48 visible characters; arbitrary message bodies must
    # not make title extraction parse an unbounded malformed HTML fragment.
    parser.feed((content or "")[:4096])
    parser.close()
    plain = " ".join("".join(parser.parts).split())
    return f"{plain[:48]}…" if len(plain) > 48 else plain


class ConversationService(NeuroEventPublisherMixin):
    """对话服务类"""

    def __init__(self):
        """初始化对话服务"""
        pass

    @staticmethod
    def _normalize_user_id(user_id: Any) -> int | None:
        """兼容历史 user_id 字段：非数字值回退为 None。"""
        if user_id is None:
            return None
        if isinstance(user_id, int):
            return user_id
        text = str(user_id).strip()
        if not text:
            return None
        if text.isdigit():
            return int(text)
        return None

    def save_message(
        self,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        intent: str = "",
        metadata: str = "",
        *,
        idempotency_key: str = "",
        expected_revision: int | None = None,
    ) -> int:
        from app.application.ai_chat.conversation_history import strip_client_recall_binding

        return self.save_turn(
            session_id=session_id,
            user_id=user_id,
            expected_revision=expected_revision,
            messages=[
                {
                    "role": role,
                    "content": content,
                    "intent": intent,
                    "metadata": strip_client_recall_binding(metadata),
                    "idempotency_key": idempotency_key,
                }
            ],
        )[0]

    def save_turn(
        self,
        *,
        session_id: str,
        user_id: str,
        messages: list[dict[str, Any]],
        expected_revision: int | None = None,
    ) -> list[int]:
        """Commit a complete receipt atomically, fenced by the conversation revision."""
        owner = self._normalize_user_id(user_id)
        message_owner = str(user_id) if user_id is not None else None
        ids: list[int] = []
        notifications: list[tuple[int, int, str]] = []
        with get_db() as db:
            begin_conversation_write(db)
            session = lock_conversation_session(
                db,
                session_id=session_id,
                user_id=owner,
                expected_revision=expected_revision,
                create=True,
            )
            for item in messages:
                role, content = str(item["role"]), str(item["content"])
                intent = str(item.get("intent") or "")
                metadata = item.get("metadata") or "{}"
                payload = json.loads(metadata)
                if not isinstance(payload, dict):
                    raise ValueError("conversation metadata must be a JSON object")
                key = str(item.get("idempotency_key") or "").strip()
                if len(key) > 256:
                    raise ValueError("conversation idempotency key is too long")
                if key:
                    payload["idempotency_key"] = key
                    # The session lock serializes duplicate writers. Search the whole
                    # indexed session, not just its last 100 messages.
                    marker = json.dumps({"idempotency_key": key}, ensure_ascii=False)[1:-1]
                    candidates = (
                        db.query(AIConversation)
                        .filter(
                            AIConversation.session_id == session_id,
                            AIConversation.user_id == message_owner,
                            AIConversation.conversation_metadata.contains(marker, autoescape=True),
                        )
                        .all()
                    )
                    prior = next(
                        (
                            row
                            for row in candidates
                            if json.loads(row.conversation_metadata or "{}").get("idempotency_key")
                            == key
                        ),
                        None,
                    )
                    if prior is not None:
                        if (prior.role, prior.content, prior.intent or "") != (
                            role,
                            content,
                            intent,
                        ):
                            raise ValueError("message retry does not match the original content")
                        ids.append(int(prior.id))
                        continue
                row = AIConversation(
                    session_id=session_id,
                    user_id=message_owner,
                    role=role,
                    content=content,
                    intent=intent,
                    conversation_metadata=json.dumps(payload, ensure_ascii=False, default=str),
                    created_at=datetime.now(),
                )
                db.add(row)
                db.flush()
                ids.append(int(row.id))
                session.message_count = int(session.message_count or 0) + 1
                session.last_message_at = row.created_at
                session.summary = _message_title(content)[:120]
                if role == "user" and not session.title:
                    session.title = _message_title(content)
                if role == "assistant" and owner:
                    notifications.append((owner, int(row.id), content))
            db.commit()
        for notification_owner, message_id, content in notifications:
            try:
                notify_user(
                    user_id=notification_owner,
                    title="AI 助手",
                    body=content[:120],
                    data={
                        "message_id": str(message_id),
                        "session_id": session_id,
                        "source": "ai",
                        "route": f"xcagi://chat?session={session_id}",
                        "channel": "xcagi_chat",
                    },
                )
            except RECOVERABLE_ERRORS as exc:
                logger.warning("conversation push notify failed: %s", exc)
        return ids

    def get_session_messages(
        self, session_id: str, limit: int = 50, *, user_id: Any = None
    ) -> list[tuple]:
        """
        获取最近的会话消息，再按时间正序返回。

        Args:
            session_id: 会话 ID
            limit: 返回数量限制
            user_id: 提供时同时校验会话所有者及消息所有者

        Returns:
            消息列表，每个元素是元组 (id, session_id, user_id, role, content, intent, metadata, created_at)
        """
        with get_db() as db:
            try:
                query = db.query(AIConversation).filter(AIConversation.session_id == session_id)
                if user_id is not None:
                    owner = self._normalize_user_id(user_id)
                    if isinstance(user_id, bool) or owner is None or owner <= 0:
                        return []
                    query = query.join(
                        AIConversationSession,
                        AIConversationSession.session_id == AIConversation.session_id,
                    ).filter(
                        AIConversationSession.user_id == owner,
                        AIConversation.user_id == str(owner),
                    )
                messages = (
                    query.order_by(AIConversation.created_at.desc(), AIConversation.id.desc())
                    .limit(limit)
                    .all()
                )

                result = []
                for msg in reversed(messages):
                    result.append(
                        (
                            msg.id,
                            msg.session_id,
                            msg.user_id,
                            msg.role,
                            msg.content,
                            msg.intent or "",
                            msg.conversation_metadata or "",
                            msg.created_at,
                        )
                    )
                return result
            except RECOVERABLE_ERRORS as e:
                logger.error("获取会话消息失败: %s", e)
                raise

    def get_sessions(self, user_id: str | None = None, limit: int = 20) -> list[tuple]:
        """
        获取会话列表

        Args:
            user_id: 用户 ID（可选）
            limit: 返回数量限制

        Returns:
            会话列表，每个元素是元组 (id, session_id, user_id, title, summary, message_count, last_message_at, created_at)
        """
        with get_db() as db:
            try:
                query = db.query(AIConversationSession).filter(
                    AIConversationSession.deleted_at.is_(None)
                )

                if user_id:
                    query = query.filter(
                        (AIConversationSession.user_id == user_id)
                        | (AIConversationSession.user_id.is_(None))
                    )

                sessions = (
                    query.order_by(AIConversationSession.last_message_at.desc()).limit(limit).all()
                )

                result = []
                for session in sessions:
                    result.append(
                        (
                            session.id,
                            session.session_id,
                            session.user_id,
                            session.title,
                            session.summary,
                            session.message_count,
                            session.last_message_at,
                            session.created_at,
                        )
                    )
                return result
            except RECOVERABLE_ERRORS as e:
                logger.error("获取会话列表失败: %s", e)
                raise

    def update_session_title(
        self, session_id: str, title: str, *, user_id: str | None = None
    ) -> bool:
        """
        更新会话标题

        Args:
            session_id: 会话 ID
            title: 新标题

        Returns:
            是否更新成功
        """
        with get_db() as db:
            try:
                query = db.query(AIConversationSession).filter(
                    AIConversationSession.session_id == session_id,
                    AIConversationSession.deleted_at.is_(None),
                )
                if user_id is not None:
                    query = query.filter(AIConversationSession.user_id == user_id)
                session = query.first()

                if session:
                    session.title = title
                    db.commit()
                    return True
                return False
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                logger.error("更新会话标题失败: %s", e)
                raise

    def delete_session(self, session_id: str, *, user_id: str | None = None) -> bool:
        with get_db() as db:
            begin_conversation_write(db)
            try:
                session = lock_conversation_session(
                    db,
                    session_id=session_id,
                    user_id=self._normalize_user_id(user_id),
                )
            except (ConversationRevisionError, PermissionError):
                return False
            db.query(AIConversation).filter(AIConversation.session_id == session_id).delete(
                synchronize_session=False,
            )
            session.revision = int(session.revision or 0) + 1
            session.deleted_at = datetime.now()
            session.title = session.summary = ""
            session.message_count = 0
            db.commit()
            return True

    def create_session(self, user_id: str = "default", title: str | None = None) -> str:
        """
        创建新会话

        Args:
            user_id: 用户 ID
            title: 会话标题（可选）

        Returns:
            新创建的会话 ID
        """
        with get_db() as db:
            try:
                session_id = str(uuid.uuid4())
                session = AIConversationSession(
                    session_id=session_id,
                    user_id=self._normalize_user_id(user_id),
                    title=title,
                    message_count=0,
                    last_message_at=datetime.now(),
                    created_at=datetime.now(),
                )
                db.add(session)
                db.commit()
                return session_id
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                logger.error("创建会话失败：%s", e)
                raise


# 全局服务实例
_conversation_service: ConversationService | None = None


def get_conversation_service() -> ConversationService:
    """获取对话服务单例"""
    global _conversation_service
    if _conversation_service is None:
        _conversation_service = ConversationService()
    return _conversation_service


# NEURO-DDD: 为 Services 层类添加 instrumentation
from app.neuro_bus.neuro_service_instrumentation import instrument_service_layer_class

instrument_service_layer_class(
    ConversationService, "app.domain.shared_services.conversation_service"
)
