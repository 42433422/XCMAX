"""IM V0 应用服务。"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db.models.im import ImConversation, ImConversationMember, ImMessage
from app.db.models.user import User
from app.utils.time import utc_now_naive

logger = logging.getLogger(__name__)


def ensure_im_tables(engine) -> None:
    from app.db.init_db import init_im_tables

    init_im_tables(engine)


class ImApplicationService:
    def __init__(self, db: Session):
        self._db = db

    def _display_name(self, user_id: int) -> str:
        user = self._db.get(User, int(user_id))
        if not user:
            return f"用户{user_id}"
        name = str(user.display_name or "").strip() or str(user.username or "").strip()
        return name or f"用户{user_id}"

    def _display_name_map(self, user_ids: list[int]) -> dict[int, str]:
        ids = [int(u) for u in set(user_ids)]
        if not ids:
            return {}
        rows = self._db.execute(select(User).where(User.id.in_(ids))).scalars().all()
        out: dict[int, str] = {}
        for u in rows:
            name = str(u.display_name or "").strip() or str(u.username or "").strip()
            out[int(u.id)] = name or f"用户{u.id}"
        return out

    def _direct_peer_id(self, conversation_id: int, user_id: int) -> int | None:
        row = self._db.execute(
            select(ImConversationMember.user_id).where(
                ImConversationMember.conversation_id == conversation_id,
                ImConversationMember.user_id != user_id,
            )
        ).first()
        return int(row[0]) if row else None

    def list_conversations(self, user_id: int) -> list[dict[str, Any]]:
        rows = (
            self._db.execute(
                select(ImConversation)
                .join(
                    ImConversationMember,
                    ImConversationMember.conversation_id == ImConversation.id,
                )
                .where(ImConversationMember.user_id == user_id)
                .order_by(desc(ImConversation.last_message_at), desc(ImConversation.id))
            )
            .scalars()
            .all()
        )
        out: list[dict[str, Any]] = []
        for conv in rows:
            last_msg = (
                self._db.execute(
                    select(ImMessage)
                    .where(ImMessage.conversation_id == conv.id)
                    .order_by(desc(ImMessage.id))
                    .limit(1)
                )
                .scalars()
                .first()
            )
            unread = self._count_unread(conv.id, user_id)
            if conv.is_direct:
                peer_id = self._direct_peer_id(conv.id, user_id)
                title = (
                    self._display_name(peer_id) if peer_id else (conv.title or f"会话 #{conv.id}")
                )
            else:
                title = conv.title or f"会话 #{conv.id}"
            out.append(
                {
                    "id": conv.id,
                    "title": title,
                    "is_direct": conv.is_direct,
                    "last_message_at": (
                        conv.last_message_at.isoformat() if conv.last_message_at else None
                    ),
                    "last_message_preview": (last_msg.body[:120] if last_msg else ""),
                    "unread_count": unread,
                }
            )
        return out

    def list_contacts(self, user_id: int) -> list[dict[str, Any]]:
        me = self._db.get(User, int(user_id))
        my_tenant = getattr(me, "tenant_id", None) if me else None
        q = select(User).where(User.id != int(user_id), User.is_active.is_(True))
        if my_tenant is not None:
            q = q.where(User.tenant_id == my_tenant)
        rows = self._db.execute(q.order_by(User.display_name, User.username)).scalars().all()
        out: list[dict[str, Any]] = []
        for u in rows:
            name = str(u.display_name or "").strip() or str(u.username or "").strip()
            out.append(
                {
                    "id": int(u.id),
                    "display_name": name or f"用户{u.id}",
                    "username": str(u.username or "").strip(),
                }
            )
        return out

    def _count_unread(self, conversation_id: int, user_id: int) -> int:
        member = self._get_member(conversation_id, user_id)
        last_read = int(member.last_read_message_id or 0) if member else 0
        return int(
            self._db.execute(
                select(func.count())
                .select_from(ImMessage)
                .where(
                    ImMessage.conversation_id == conversation_id,
                    ImMessage.id > last_read,
                    ImMessage.sender_user_id != user_id,
                )
            ).scalar()
            or 0
        )

    def _get_member(self, conversation_id: int, user_id: int) -> ImConversationMember | None:
        return self._db.execute(
            select(ImConversationMember).where(
                ImConversationMember.conversation_id == conversation_id,
                ImConversationMember.user_id == user_id,
            )
        ).scalar_one_or_none()

    def get_or_create_direct(self, user_id: int, peer_user_id: int) -> dict[str, Any]:
        if user_id == peer_user_id:
            raise ValueError("不能与自己创建会话")
        conv_id = self._find_direct_conversation(user_id, peer_user_id)
        if conv_id:
            conv = self._db.get(ImConversation, conv_id)
            return {"id": conv.id, "title": conv.title, "created": False}
        conv = ImConversation(
            title=f"用户{user_id} ↔ 用户{peer_user_id}",
            is_direct=True,
        )
        self._db.add(conv)
        self._db.flush()
        for uid in (user_id, peer_user_id):
            self._db.add(ImConversationMember(conversation_id=conv.id, user_id=uid))
        self._db.commit()
        self._db.refresh(conv)
        return {"id": conv.id, "title": conv.title, "created": True}

    def _find_direct_conversation(self, a: int, b: int) -> int | None:
        sub_a = select(ImConversationMember.conversation_id).where(
            ImConversationMember.user_id == a
        )
        sub_b = select(ImConversationMember.conversation_id).where(
            ImConversationMember.user_id == b
        )
        row = self._db.execute(
            select(ImConversation.id)
            .where(
                ImConversation.is_direct.is_(True),
                ImConversation.id.in_(sub_a),
                ImConversation.id.in_(sub_b),
            )
            .limit(1)
        ).first()
        return int(row[0]) if row else None

    def list_messages(
        self, conversation_id: int, user_id: int, *, limit: int = 50, before_id: int | None = None
    ) -> list[dict[str, Any]]:
        if not self._get_member(conversation_id, user_id):
            raise PermissionError("非会话成员")
        q = select(ImMessage).where(ImMessage.conversation_id == conversation_id)
        if before_id:
            q = q.where(ImMessage.id < before_id)
        rows = (
            self._db.execute(q.order_by(desc(ImMessage.id)).limit(min(limit, 100))).scalars().all()
        )
        rows = list(reversed(rows))
        names = self._display_name_map([m.sender_user_id for m in rows])
        return [self._message_dict(m, names.get(int(m.sender_user_id))) for m in rows]

    def send_message(self, conversation_id: int, sender_user_id: int, body: str) -> dict[str, Any]:
        if not self._get_member(conversation_id, sender_user_id):
            raise PermissionError("非会话成员")
        text = (body or "").strip()
        if not text:
            raise ValueError("消息不能为空")
        msg = ImMessage(
            conversation_id=conversation_id,
            sender_user_id=sender_user_id,
            body=text[:4000],
        )
        self._db.add(msg)
        conv = self._db.get(ImConversation, conversation_id)
        if conv:
            conv.last_message_at = utc_now_naive()
        self._db.commit()
        self._db.refresh(msg)
        member_ids = self._member_user_ids(conversation_id)
        message = self._message_dict(msg, self._display_name(sender_user_id))
        updated_at_ms = self._record_im_message_change(message, actor=str(sender_user_id))
        return {
            "message": message,
            "member_user_ids": member_ids,
            "updated_at_ms": updated_at_ms,
        }

    def mark_read(
        self, conversation_id: int, user_id: int, last_message_id: int
    ) -> dict[str, Any]:
        member = self._get_member(conversation_id, user_id)
        if not member:
            raise PermissionError("非会话成员")
        applied_read = max(int(member.last_read_message_id or 0), last_message_id)
        member.last_read_message_id = applied_read
        self._db.commit()
        updated_at_ms = self._record_im_read_change(
            conversation_id,
            user_id,
            applied_read,
            actor=str(user_id),
        )
        return {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "last_read_message_id": applied_read,
            "member_user_ids": self._member_user_ids(conversation_id),
            "updated_at_ms": updated_at_ms,
        }

    @staticmethod
    def _record_im_message_change(message: dict[str, Any], *, actor: str) -> int:
        from app.services.xcmax_sync_service import record_change, utc_now_ms

        updated_at_ms = utc_now_ms()
        record_change(
            "im_message",
            str(message["id"]),
            "insert",
            {**message, "meta": {"updated_at_ms": updated_at_ms}},
            actor=actor,
        )
        return updated_at_ms

    @staticmethod
    def _record_im_read_change(
        conversation_id: int,
        user_id: int,
        last_read_message_id: int,
        *,
        actor: str,
    ) -> int:
        from app.services.xcmax_sync_service import record_change, utc_now_ms

        updated_at_ms = utc_now_ms()
        record_change(
            "im_read_state",
            f"{conversation_id}:{user_id}",
            "update",
            {
                "conversation_id": conversation_id,
                "user_id": user_id,
                "last_read_message_id": last_read_message_id,
                "meta": {"updated_at_ms": updated_at_ms},
            },
            actor=actor,
        )
        return updated_at_ms

    def _member_user_ids(self, conversation_id: int) -> list[int]:
        rows = self._db.execute(
            select(ImConversationMember.user_id).where(
                ImConversationMember.conversation_id == conversation_id
            )
        ).all()
        return [int(r[0]) for r in rows]

    @staticmethod
    def _message_dict(m: ImMessage, sender_name: str | None = None) -> dict[str, Any]:
        return {
            "id": m.id,
            "conversation_id": m.conversation_id,
            "sender_user_id": m.sender_user_id,
            "sender_display_name": sender_name or f"用户{m.sender_user_id}",
            "body": m.body,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
