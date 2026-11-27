"""Exact SQL transcript fragments within the authenticated current conversation."""

from __future__ import annotations

from sqlalchemy import func

from app.application.agent_orchestrator.tool_spec import validate_tool_call
from app.db.models import AIConversation
from app.db.session import get_host_db
from app.domain.conversation.message_visibility import public_messages
from app.domain.shared_services.conversation_service import (
    ConversationRevisionError,
    begin_conversation_write,
    lock_conversation_session,
)
from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError, _bound_actor


def read_conversation_history(action: str, params: dict, context: dict) -> dict:
    validation = validate_tool_call("conversation_history", action, params)
    if not validation.ok:
        return {
            "success": False,
            "error_code": validation.error_code,
            "message": validation.message,
        }
    before, after, message_id = (params.get(key) for key in ("before_id", "after_id", "message_id"))
    if (
        (before is not None and after is not None)
        or (message_id is not None and (before is not None or after is not None))
        or ("offset" in params and message_id is None)
    ):
        return {
            "success": False,
            "error_code": "invalid_history_cursor",
            "message": "消息编号、前后游标不能混用；offset只用于单条消息。",
        }
    try:
        actor = _bound_actor(context)
        conversation_id = str(
            context.get("conversation_id") or context.get("session_id") or ""
        ).strip()
        session_id = str(context.get("session_id") or "").strip()
        if not conversation_id or (session_id and session_id != conversation_id):
            raise AgentModAuthorizationError("缺少当前会话或会话标识冲突")
        if context.get("local_user_id") is not None and str(context["local_user_id"]) != str(
            actor.id
        ):
            raise AgentModAuthorizationError("当前会话账号不匹配")
        limit = 1 if message_id is not None else int(params.get("limit") or 10)
        budget = int(params.get("max_chars") or 6000)
        limit = min(limit, budget)
        offset = int(params.get("offset") or 0)
        fragment_size = max(1, budget // limit)
        with get_host_db() as db:
            # Read a coherent lifecycle snapshot, including on SQLite where FOR UPDATE is ignored.
            begin_conversation_write(db)
            session = lock_conversation_session(
                db,
                session_id=conversation_id,
                user_id=int(actor.id),
                expected_revision=context.get("_conversation_revision"),
            )
            query = db.query(
                AIConversation.id,
                AIConversation.role,
                func.substr(AIConversation.content, offset + 1, fragment_size).label("fragment"),
                func.length(AIConversation.content).label("total_chars"),
            ).filter(
                AIConversation.session_id == conversation_id,
                AIConversation.user_id == str(actor.id),
                public_messages(db),
            )
            if before is not None:
                query = query.filter(AIConversation.id < before)
            if after is not None:
                query = query.filter(AIConversation.id > after)
            if message_id is not None:
                query = query.filter(AIConversation.id == message_id)
            ascending = after is not None
            rows = (
                query.order_by(AIConversation.id.asc() if ascending else AIConversation.id.desc())
                .limit(limit + 1)
                .all()
            )
            if message_id is not None and not rows:
                raise PermissionError("消息不在当前会话中")
            more, rows = len(rows) > limit, rows[:limit]
            if not ascending:
                rows.reverse()
            messages = [
                {
                    "id": row.id,
                    "role": row.role,
                    "content": row.fragment,
                    "offset": offset,
                    "total_chars": row.total_chars,
                    "next_offset": offset + len(row.fragment)
                    if offset + len(row.fragment) < row.total_chars
                    else None,
                    "content_complete": offset == 0 and len(row.fragment) == row.total_chars,
                }
                for row in rows
            ]
            return {
                "success": True,
                "message": "已读取当前会话原文；非完整正文请按message_id和next_offset继续读取。",
                "data": {
                    "conversation_id": conversation_id,
                    "revision": session.revision,
                    "messages": messages,
                    "has_more": more,
                    "next_before_id": rows[0].id if more and rows and not ascending else None,
                    "next_after_id": rows[-1].id if more and rows and ascending else None,
                },
            }
    except (AgentModAuthorizationError, PermissionError):
        return {
            "success": False,
            "error_code": "conversation_history_not_authorized",
            "message": "只能读取有效登录账号的当前会话。",
        }
    except ConversationRevisionError:
        return {
            "success": False,
            "error_code": "conversation_history_changed",
            "message": "会话已删除或撤回，请重新读取当前会话。",
        }
