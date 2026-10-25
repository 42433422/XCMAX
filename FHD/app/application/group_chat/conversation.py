"""User messages and the explicit reply/discussion/work dispatch workflow."""

from __future__ import annotations

from typing import Any

from app.application.group_chat.constants import CONTEXT_TURNS
from app.application.group_chat.dispatch_targeting import DispatchTargeting
from app.application.group_chat.employee_registry import (
    _normalize_branch_context,
    _with_required_group_members,
)
from app.application.group_chat.projections import ChatProjection
from app.application.group_chat.protocols import (
    ConversationActions,
    GroupStore,
    MessageFactory,
    MessageStore,
    ProgressSources,
)
from app.application.group_chat.storage import GroupChatRepository


class GroupConversation:
    def __init__(
        self,
        groups: GroupStore,
        messages: MessageStore,
        targeting: DispatchTargeting,
        actions: ConversationActions,
        progress: ProgressSources,
        make_row: MessageFactory,
    ) -> None:
        self.groups = groups
        self.messages = messages
        self.targeting = targeting
        self.actions = actions
        self.progress = progress
        self.make_row = make_row

    async def post_message(
        self,
        *,
        user_id: int,
        group_id: str,
        text: str,
        sender_name: str = "我",
        mentions: list[str] | None = None,
        dispatch: bool = False,
        branch_context: str = "",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = (text or "").strip()
        if not body:
            raise ValueError("message 不能为空")
        action_context = context if isinstance(context, dict) else {}
        tool_action = str(action_context.get("tool_action") or "").strip()
        branch_context = _normalize_branch_context(branch_context)
        group_id = self.groups.resolve(user_id=user_id, group_id=group_id)
        groups = self.groups.for_user(user_id)
        group = GroupChatRepository.find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        members = _with_required_group_members(
            [m for m in group.get("members", []) if isinstance(m, dict)]
        )
        if members != group.get("members", []):
            group["members"] = members
            self.groups.rewrite(GroupChatRepository.replace(self.groups.all(), group))
        user_msg = self.make_row(
            user_id=user_id,
            group_id=group_id,
            role="user",
            sender_id="user",
            sender_name=sender_name or "我",
            sender_avatar="",
            body=body,
            payload={"branch_context": branch_context} if dispatch and branch_context else None,
        )
        new_messages = [user_msg]
        self.messages.append([user_msg])
        if tool_action == "acceptance_followup":
            followup = self.actions.followup(user_id=user_id, group_id=group_id)
            if followup is not None:
                new_messages.append(followup)
            previews = self.messages.previews(user_id)
            return {
                "group": ChatProjection.public_group(group, previews.get(str(group.get("id")))),
                "messages": [ChatProjection.public_message(m) for m in new_messages],
            }
        members = [m for m in group.get("members", []) if isinstance(m, dict)]
        history = self.actions.history(user_id=user_id, group_id=group_id, limit=CONTEXT_TURNS)
        work_orders: list[dict[str, Any]] = []
        if dispatch:
            responders = self.targeting.pick_dispatch_targets(members, body, mentions)
            discussion_messages: list[dict[str, Any]] = []
            if DispatchTargeting.should_run_super_discussion(responders):
                discussion_messages, responders = await self.actions.discuss(
                    group=group,
                    task=body,
                    candidates=responders,
                    user_id=user_id,
                    history=history,
                    mentions=mentions,
                    persist=True,
                )
                new_messages.extend(discussion_messages)
            dispatch_messages, work_orders = await self.actions.dispatch(
                group=group,
                members=responders,
                task=body,
                user_id=user_id,
                sender_name=sender_name or "我",
                branch_context=branch_context,
                persist=True,
            )
            new_messages.extend(dispatch_messages)
        else:
            responders = DispatchTargeting.pick_responders(members, body, mentions)
            for member in responders:
                reply = await self.actions.reply(group, member, history, user_id=user_id)
                ai_msg = self.make_row(
                    user_id=user_id,
                    group_id=group_id,
                    role="ai",
                    sender_id=str(member.get("employee_id")),
                    sender_name=str(member.get("name") or member.get("employee_id")),
                    sender_avatar=str(member.get("avatar") or ""),
                    body=reply,
                )
                new_messages.append(ai_msg)
                self.messages.append([ai_msg])
                history = history + [ChatProjection.public_message(ai_msg)]
        previews = self.messages.previews(user_id)
        result: dict[str, Any] = {
            "group": ChatProjection.public_group(group, previews.get(str(group.get("id")))),
            "messages": [ChatProjection.public_message(m) for m in new_messages],
        }
        if dispatch:
            result["work_orders"] = work_orders
        return result

    def get_messages(
        self, *, user_id: int, group_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        group_id = self.groups.resolve(user_id=user_id, group_id=group_id)
        self.progress.relay(user_id=user_id, group_id=group_id)
        self.progress.super_employee(user_id=user_id, group_id=group_id)
        rows = [
            ChatProjection.public_message(r)
            for r in self.messages.read()
            if int(r.get("user_id") or 0) == int(user_id)
            and str(r.get("group_id")) == str(group_id)
        ]
        return rows[-max(1, min(int(limit), 300)) :]

    def delete_message(self, *, user_id: int, group_id: str, message_id: str) -> dict[str, Any]:
        group_id = self.groups.resolve(user_id=user_id, group_id=group_id)
        msg_id = str(message_id or "").strip()
        if not msg_id:
            raise ValueError("消息不存在")
        rows = self.messages.read()
        target = next(
            (
                r
                for r in rows
                if int(r.get("user_id") or 0) == int(user_id)
                and str(r.get("group_id")) == str(group_id)
                and (str(r.get("id")) == msg_id)
            ),
            None,
        )
        if target is None:
            raise ValueError("消息不存在")
        if str(target.get("role") or "") != "user" or str(target.get("sender_id") or "") != "user":
            raise ValueError("只能删除自己发送的消息")
        self.messages.rewrite(
            [
                r
                for r in rows
                if not (
                    int(r.get("user_id") or 0) == int(user_id)
                    and str(r.get("group_id")) == str(group_id)
                    and str(r.get("id")) == msg_id
                )
            ]
        )
        return {"deleted": True, "id": msg_id}
