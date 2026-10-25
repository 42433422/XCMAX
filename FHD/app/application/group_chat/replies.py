"""Conversational completion and super-employee chat replies."""

from __future__ import annotations

import asyncio
from typing import Any

from app.application.group_chat.constants import _SUPER_EMPLOYEE_IDS, CONTEXT_TURNS, CompletionFn
from app.application.group_chat.protocols import AiReply, EmployeeProviders
from app.utils.operational_errors import RECOVERABLE_ERRORS


class ChatReplies:
    def __init__(
        self, *, complete: CompletionFn, providers: EmployeeProviders, super_reply: AiReply
    ) -> None:
        self.complete = complete
        self.providers = providers
        self.super_reply = super_reply

    async def ai_reply(
        self,
        group: dict[str, Any],
        member: dict[str, Any],
        history: list[dict[str, Any]],
        *,
        user_id: int,
    ) -> str:
        employee_id = str(member.get("employee_id") or "")
        if employee_id in _SUPER_EMPLOYEE_IDS:
            return await self.super_reply(group, member, history, user_id=user_id)
        group_name = str(group.get("name") or "AI 群聊")
        me = str(member.get("name") or member.get("employee_id"))
        summary = str(member.get("summary") or "")
        roster = "、".join(
            str(m.get("name") or "") for m in group.get("members", []) if isinstance(m, dict)
        )
        system = f"你是群聊「{group_name}」里的 AI 成员「{me}」。{summary}\n群成员有：{roster}。\n请只代表你自己、用一两句话简洁地回应群里用户的最新消息；不要替其他成员发言，不要复述别人说过的话，不要加“作为AI”之类的免责声明。"
        transcript = "\n".join(
            f"{m.get('sender_name')}：{m.get('body')}" for m in history[-CONTEXT_TURNS:]
        )
        user_content = f"【群最近对话】\n{transcript}\n\n请以「{me}」身份回应最新这条消息。"
        try:
            res = await self.complete(
                [{"role": "system", "content": system}, {"role": "user", "content": user_content}]
            )
        except RECOVERABLE_ERRORS as exc:
            return f"（{me} 暂时无法回应：{str(exc)[:120]}）"
        if isinstance(res, dict) and res.get("success") and str(res.get("content") or "").strip():
            return str(res["content"]).strip()
        err = str((res or {}).get("error") or "").strip() if isinstance(res, dict) else ""
        return f"（{me} 暂时无法回应{(f'：{err}' if err else '')}）"

    async def super_employee_reply(
        self,
        group: dict[str, Any],
        member: dict[str, Any],
        history: list[dict[str, Any]],
        *,
        user_id: int,
    ) -> str:
        """超级员工群聊回复：调用专用 invoke 通道（CLI 直答 / Para 派工）。

        超级员工的回复结果会写入其自身会话的 messages.jsonl（由 invoke 内部完成），
        群聊消息则写入 ai_group_chat/messages.jsonl（由调用方 post_message 完成），
        两者独立持久化，互不干扰。
        """
        employee_id = str(member.get("employee_id") or "")
        me = str(member.get("name") or employee_id)
        group_name = str(group.get("name") or "AI 群聊")
        roster = "、".join(
            str(m.get("name") or "") for m in group.get("members", []) if isinstance(m, dict)
        )
        transcript = "\n".join(
            f"{m.get('sender_name')}：{m.get('body')}" for m in history[-CONTEXT_TURNS:]
        )
        prompt = f"你是群聊「{group_name}」里的成员「{me}」。\n群成员有：{roster}。\n【群最近对话】\n{transcript}\n\n请以「{me}」身份回应最新这条消息，用一两句话简洁回应。"
        try:
            service = self.providers.super_employee(employee_id)
            # Chat replies use the direct channel; invoke runs off the event loop.
            result = await asyncio.to_thread(
                service.invoke, user_id=int(user_id), message=prompt, context={"mode": "chat"}
            )
            assistant = result.get("assistant_message") or {}
            body = str(assistant.get("body") or "").strip()
            if body:
                return body
            return f"（{me} 暂时无法回应）"
        except RECOVERABLE_ERRORS as exc:
            return f"（{me} 暂时无法回应：{str(exc)[:120]}）"
