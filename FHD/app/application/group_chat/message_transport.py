"""Bridge the host's authoritative conversation lifecycle to optional IM delivery."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.application.group_chat.storage import GroupChatRepository
from app.infrastructure.im.openim import OpenIMGroups, enabled

if TYPE_CHECKING:
    from app.application.ai_group_chat_service import AiGroupChatService


def require_deletion_allowed(service: AiGroupChatService) -> None:
    if enabled():
        raise ValueError("迁移验收期间暂不支持删除，请保留消息用于核对")
    if service._deny_unscoped():
        raise ValueError("群不存在")


def append_messages(repository: GroupChatRepository, messages: list[dict[str, Any]]) -> None:
    repository.append_messages(messages)
    if enabled():
        transport = OpenIMGroups(repository)
        for user_id, group_id in {(int(m["user_id"]), str(m["group_id"])) for m in messages}:
            transport.sync(user_id, group_id)


def session(service: AiGroupChatService, user_id: int, group_id: str) -> dict[str, Any]:
    # Remote history alone cannot collect finished relay/employee tasks. Run the
    # normal host conversation lifecycle before publishing the resulting audit rows.
    service.get_messages(user_id=user_id, group_id=group_id)
    return OpenIMGroups(service._storage).session(user_id, group_id)
