"""ImApplicationService 的「运营者客服收件箱」mixin。

从 im_app_service 拆出以控制单文件行数（arch-fitness giant-file 上限）。覆盖运营者(管理端)查看并回复
「企业客户↔企业专属客服」会话（手机端/桌面端同一张 IM 表）。依赖宿主类提供：``_db`` /
``_ensure_enterprise_dedicated_cs_user`` / ``_direct_peer_id`` / ``_display_name`` / ``_count_unread`` /
``list_messages`` / ``send_message``。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import desc, select

from app.db.models.im import ImConversation, ImConversationMember


class CsInboxMixin:
    def enterprise_cs_user_id(self) -> int | None:
        cs = self._ensure_enterprise_dedicated_cs_user()
        return int(cs.id) if cs is not None else None

    def list_cs_inbox(self) -> list[dict[str, Any]]:
        """运营者客服收件箱:所有「企业客户↔企业专属客服」会话(含手机端/桌面端,同一张 IM 表)。"""
        cs_id = self.enterprise_cs_user_id()
        if cs_id is None:
            return []
        conv_ids = [
            int(r[0])
            for r in self._db.execute(
                select(ImConversationMember.conversation_id).where(
                    ImConversationMember.user_id == cs_id
                )
            ).all()
        ]
        if not conv_ids:
            return []
        rows = (
            self._db.execute(
                select(ImConversation)
                .where(ImConversation.id.in_(conv_ids), ImConversation.is_direct.is_(True))
                .order_by(desc(ImConversation.last_message_at))
            )
            .scalars()
            .all()
        )
        out: list[dict[str, Any]] = []
        for conv in rows:
            customer_id = self._direct_peer_id(int(conv.id), cs_id)
            if not customer_id:
                continue
            out.append(
                {
                    "id": int(conv.id),
                    "customer_user_id": int(customer_id),
                    "customer_name": self._display_name(int(customer_id)),
                    "last_message_at": conv.last_message_at.isoformat()
                    if conv.last_message_at
                    else "",
                    "unread_count": self._count_unread(int(conv.id), cs_id),
                }
            )
        return out

    def cs_inbox_messages(self, conversation_id: int) -> list[dict[str, Any]]:
        """运营者读某客服会话历史(以 enterprise-cs 成员身份)。"""
        cs_id = self.enterprise_cs_user_id()
        if cs_id is None:
            return []
        return self.list_messages(conversation_id, cs_id, limit=100)

    def cs_reply(self, conversation_id: int, body: str) -> dict[str, Any]:
        """运营者以「企业专属客服」身份回复客户。"""
        cs_id = self.enterprise_cs_user_id()
        if cs_id is None:
            raise ValueError("客服通道不可用")
        return self.send_message(conversation_id, cs_id, body)
