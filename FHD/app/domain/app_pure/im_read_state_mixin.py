"""Read-cursor behavior shared by normal, employee, and customer-service IM."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any


class ImReadStateMixin:
    if TYPE_CHECKING:
        _db: Any
        _get_member: Any
        _member_user_ids: Any
        _record_im_read_change: Any

    def mark_read(
        self,
        conversation_id: int,
        user_id: int,
        last_message_id: int,
        *,
        record_sync: bool = True,
    ) -> dict[str, Any]:
        member = self._get_member(conversation_id, user_id)
        if not member:
            raise PermissionError("非会话成员")
        applied_read = max(int(member.last_read_message_id or 0), last_message_id)
        member.last_read_message_id = applied_read
        self._db.commit()
        updated_at_ms = (
            self._record_im_read_change(
                conversation_id,
                user_id,
                applied_read,
                actor=str(user_id),
            )
            if record_sync
            else None
        )
        return {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "last_read_message_id": applied_read,
            "member_user_ids": self._member_user_ids(conversation_id),
            "updated_at_ms": updated_at_ms,
        }
