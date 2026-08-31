"""Model, ecosystem, IM, workflow, and account-entitlement sync appliers."""

from __future__ import annotations

import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)


def _facade() -> Any:
    return sys.modules["app.services.xcmax_sync_service"]


@_facade().register_entity_applier("model_config")
def _apply_model_config(item: dict[str, Any]) -> None:
    """模型服务配置变更：更新用户默认 LLM 配置（写入 users.default_llm_json）。"""
    payload = item.get("payload") or {}
    try:
        from app.db import get_db
        from app.db.models.user import User

        with get_db() as db:
            user_id = payload.get("user_id")
            if not user_id:
                return
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                user.default_llm_json = _facade().json.dumps(
                    payload.get("llm_config") or {}, ensure_ascii=False
                )
                db.commit()
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("apply_model_config failed: %s", exc)


@_facade().register_entity_applier("ecosystem")
def _apply_ecosystem(item: dict[str, Any]) -> None:
    """智能生态配置变更：记录生态组件启停状态（写入 sync_meta 供前端查询）。"""
    payload = item.get("payload") or {}
    try:
        import sqlite3 as _sqlite3

        from app.db.xcmax_sync import _resolve_db_path

        conn = _sqlite3.connect(str(_resolve_db_path()))
        key = f"ecosystem:{item.get('entity_id', 'default')}"
        conn.execute(
            "INSERT OR REPLACE INTO sync_meta (key, value) VALUES (?, ?)",
            (key, _facade().json.dumps(payload, ensure_ascii=False, default=str)),
        )
        conn.commit()
        conn.close()
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.debug("apply_ecosystem non-fatal: %s", exc)


@_facade().register_entity_applier("im_message")
def _apply_im_message(item: dict[str, Any]) -> None:
    """IM 消息变更：写入 im_messages（insert/update，LWW by meta.updated_at_ms）。"""
    payload = item.get("payload") or {}
    operation = item.get("operation", "insert")
    message_id = int(payload.get("id") or item.get("entity_id") or 0)
    conversation_id = int(payload.get("conversation_id") or 0)
    if operation == "delete":
        if not message_id:
            return
        try:
            from app.db import get_db
            from app.db.models.im import ImMessage

            with get_db() as db:
                obj = db.query(ImMessage).filter(ImMessage.id == message_id).first()
                if obj:
                    db.delete(obj)
                    db.commit()
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.warning(
                "apply_im_message delete failed id=%s: %s", message_id, exc
            )
        return
    if not conversation_id:
        return
    body = str(payload.get("body") or "").strip()
    if not body:
        return
    incoming_ms = _facade()._payload_updated_at_ms(payload)
    meta_key = f"im_message:{message_id}" if message_id else ""
    if message_id and meta_key:
        stored = _facade()._read_sync_meta(meta_key)
        stored_ms = int(stored.get("updated_at_ms") or 0)
        if incoming_ms and stored_ms and (incoming_ms < stored_ms):
            return
    try:
        from app.db import get_db
        from app.db.models.im import ImConversation, ImMessage
        from app.utils.time import utc_now_naive

        sender_user_id = int(payload.get("sender_user_id") or 0)
        if not sender_user_id:
            return
        with get_db() as db:
            obj = (
                db.query(ImMessage).filter(ImMessage.id == message_id).first()
                if message_id
                else None
            )
            if obj:
                if incoming_ms:
                    stored_ms = int(
                        (_facade()._read_sync_meta(meta_key) or {}).get("updated_at_ms")
                        or 0
                    )
                    if stored_ms and incoming_ms < stored_ms:
                        return
                obj.body = body[:4000]
                if sender_user_id:
                    obj.sender_user_id = sender_user_id
                obj.origin = str(
                    payload.get("origin") or getattr(obj, "origin", "user")
                )[:32]
                raw_operator_id = payload.get("operator_user_id")
                obj.operator_user_id = int(raw_operator_id) if raw_operator_id else None
            else:
                obj = ImMessage(
                    id=message_id if message_id else None,
                    conversation_id=conversation_id,
                    sender_user_id=sender_user_id,
                    body=body[:4000],
                    origin=str(payload.get("origin") or "user")[:32],
                    operator_user_id=(
                        int(payload.get("operator_user_id"))
                        if payload.get("operator_user_id")
                        else None
                    ),
                )
                db.add(obj)
            conv = db.get(ImConversation, conversation_id)
            if conv:
                conv.last_message_at = utc_now_naive()
            db.commit()
            db.refresh(obj)
            if meta_key:
                _facade()._write_sync_meta(
                    meta_key,
                    {
                        "updated_at_ms": incoming_ms or _facade().utc_now_ms(),
                        "id": int(obj.id),
                    },
                )
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning(
            "apply_im_message failed conv=%s: %s", conversation_id, exc
        )


@_facade().register_entity_applier("im_read_state")
def _apply_im_read_state(item: dict[str, Any]) -> None:
    """IM 已读游标：更新 ImConversationMember.last_read_message_id（LWW）。"""
    payload = item.get("payload") or {}
    conversation_id = int(payload.get("conversation_id") or 0)
    user_id = int(payload.get("user_id") or 0)
    incoming_read = int(payload.get("last_read_message_id") or 0)
    if not conversation_id or not user_id:
        parts = str(item.get("entity_id") or "").split(":", 1)
        if len(parts) == 2:
            conversation_id = conversation_id or int(parts[0] or 0)
            user_id = user_id or int(parts[1] or 0)
    if not conversation_id or not user_id:
        return
    incoming_ms = _facade()._payload_updated_at_ms(payload)
    meta_key = f"im_read_state:{conversation_id}:{user_id}"
    stored = _facade()._read_sync_meta(meta_key)
    stored_ms = int(stored.get("updated_at_ms") or 0)
    stored_read = int(stored.get("last_read_message_id") or 0)
    if incoming_ms and stored_ms and (incoming_ms < stored_ms):
        return
    if (
        incoming_ms
        and stored_ms
        and (incoming_ms == stored_ms)
        and (incoming_read <= stored_read)
    ):
        return
    new_read = max(incoming_read, stored_read)
    try:
        from sqlalchemy import select

        from app.db import get_db
        from app.db.models.im import ImConversationMember

        with get_db() as db:
            member = db.execute(
                select(ImConversationMember).where(
                    ImConversationMember.conversation_id == conversation_id,
                    ImConversationMember.user_id == user_id,
                )
            ).scalar_one_or_none()
            if not member:
                return
            applied_read = max(int(member.last_read_message_id or 0), new_read)
            member.last_read_message_id = applied_read
            db.commit()
        _facade()._write_sync_meta(
            meta_key,
            {
                "updated_at_ms": (
                    max(incoming_ms, stored_ms) if incoming_ms else stored_ms
                ),
                "last_read_message_id": applied_read,
            },
        )
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning(
            "apply_im_read_state failed conv=%s user=%s: %s",
            conversation_id,
            user_id,
            exc,
        )


@_facade().register_entity_applier("workflow_employee")
def _apply_workflow_employee(item: dict[str, Any]) -> None:
    """员工工作流节点变更：更新本地 Mod manifest 的 workflow_employees 状态快照。"""
    payload = item.get("payload") or {}
    operation = item.get("operation", "sync")
    employee_id = str(payload.get("employee_id") or item.get("entity_id") or "").strip()
    if not employee_id:
        return
    try:
        import sqlite3 as _sqlite3

        from app.db.xcmax_sync import _resolve_db_path

        conn = _sqlite3.connect(str(_resolve_db_path()))
        key = f"workflow_employee:{employee_id}"
        if operation == "delete":
            conn.execute("DELETE FROM sync_meta WHERE key=?", (key,))
        else:
            conn.execute(
                "INSERT OR REPLACE INTO sync_meta (key, value) VALUES (?, ?)",
                (key, _facade().json.dumps(payload, ensure_ascii=False, default=str)),
            )
        conn.commit()
        conn.close()
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.debug("apply_workflow_employee non-fatal: %s", exc)


def _sync_payload_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


@_facade().register_entity_applier("account_entitlements")
def _apply_account_entitlements(item: dict[str, Any]) -> None:
    """账号权益快照：写入 sync_meta，并同步本地 User 核心权益字段。

    管理端强制推送的是一次完整快照，企业端收到后即使暂时没有市场 API，也能从本地
    User 表和 sync_meta 读到账号等级、行业、绑定 Mod、余额等状态。
    """
    payload = item.get("payload") or {}
    if not isinstance(payload, dict):
        return
    entity_id = str(
        payload.get("market_user_id") or item.get("entity_id") or ""
    ).strip()
    if not entity_id:
        return
    raw_profile = payload.get("profile")
    profile: dict[str, Any] = dict(raw_profile) if isinstance(raw_profile, dict) else {}
    username = str(payload.get("username") or profile.get("username") or "").strip()
    if not username:
        return
    try:
        stored_payload = {
            **payload,
            "market_user_id": entity_id,
            "mod_ids": _facade()._sync_payload_list(payload.get("mod_ids")),
        }
        _facade()._write_sync_meta(f"account_entitlements:{entity_id}", stored_payload)
        _facade()._write_sync_meta(
            f"account_entitlements:username:{username}", stored_payload
        )
        from app.db.models.user import User
        from app.db.session import get_db

        if not isinstance(profile, dict):
            profile = {}
        tier = str(profile.get("tier") or payload.get("tier") or "").strip().lower()
        if tier not in {"personal", "enterprise", "admin"}:
            tier = "enterprise" if bool(payload.get("is_enterprise")) else "personal"
        industry_id = str(
            profile.get("industry_id") or payload.get("industry_id") or "通用"
        ).strip()
        account_tier = str(profile.get("account_tier") or "").strip() or None
        budget_range = str(profile.get("budget_range") or "").strip() or None
        entitled_industries = _facade()._sync_payload_list(
            profile.get("entitled_industries")
        )
        if industry_id and industry_id not in entitled_industries:
            entitled_industries.append(industry_id)
        with get_db() as db:
            user = db.query(User).filter(User.username == username).first()
            if user is None:
                user = User(username=username, password="", role="user")
                db.add(user)
                db.flush()
            user.tier = tier
            user.industry_id = industry_id or "通用"
            user.account_tier = account_tier if tier == "enterprise" else None
            user.budget_range = budget_range
            user.entitled_industries = entitled_industries or [user.industry_id]
            if payload.get("email"):
                user.email = str(payload.get("email") or "").strip()
            db.commit()
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning(
            "apply_account_entitlements failed user=%s id=%s: %s",
            username,
            entity_id,
            exc,
        )
