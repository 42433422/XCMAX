"""微信聊天记录摄取与客户身份解析（本机 → 服务器 AI 智慧基建 V1）。

职责：
1. 接收本机采集端批量上行的微信联系人/消息，幂等入库（dedupe_hash 去重）。
2. 身份解析：display_name 精确匹配 customers.customer_name / contact_person 自动绑定；
   无法匹配的联系人保持 unlinked，由管理端人工绑定。
3. 上下文聚合：为回流本机（第二载体）与 AI 对话注入提供客户情报。

租户说明：本服务是系统级 ops 管道（token 认证，无会话租户上下文），读取统一走
``skip_tenant_filter`` 逃生舱并显式按 tenant_id 过滤；写入显式携带 tenant_id。
payload 未提供 tenant_id 时默认拒绝（除非 XCAGI_TENANT_ALLOW_UNSCOPED_WRITE=1）。
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import Select, func, or_, select

from app.db.models.customer import Customer
from app.db.models.wechat_sync import WechatContact, WechatMessage

logger = logging.getLogger(__name__)

_VALID_ROLES = {"self", "other"}
_VALID_SOURCES = {"db", "cv", "api"}
_SYS_READ = {"skip_tenant_filter": True}


def _sys(stmt: Select) -> Select:
    """系统级读取逃生舱：本服务自带显式租户过滤，绕过全局 fail-closed 注入。"""
    return stmt.execution_options(**_SYS_READ)


def _open_session():
    from app.db import SessionLocal

    return SessionLocal()


def _parse_ts(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        # epoch 秒/毫秒自适应
        ts = float(value)
        if ts > 1e12:
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=UTC)
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_contact_key(value: Any) -> str:
    return str(value or "").strip()[:128]


def _dedupe_hash(contact_key: str, role: str, content: str, client_seq: int | None) -> str:
    """幂等指纹：本机为每条新消息分配单调 client_seq（含同文重复），缺省退化为内容指纹。"""
    seq_part = str(client_seq) if client_seq is not None else ""
    raw = f"{contact_key}|{seq_part}|{role}|{content}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _match_customer(session: Any, display_name: str, tenant_id: int | None) -> Customer | None:
    name = str(display_name or "").strip()
    if not name:
        return None
    stmt = _sys(
        select(Customer).where(or_(Customer.customer_name == name, Customer.contact_person == name))
    )
    if tenant_id is not None:
        stmt = stmt.where(Customer.tenant_id == tenant_id)
    row: Customer | None = session.scalars(stmt.order_by(Customer.id).limit(1)).first()
    return cast("Customer | None", row)


def _upsert_contact(
    session: Any,
    *,
    contact_key: str,
    display_name: str,
    wxid: str | None,
    tenant_id: int | None,
) -> WechatContact:
    stmt = _sys(select(WechatContact).where(WechatContact.contact_key == contact_key))
    if tenant_id is not None:
        stmt = stmt.where(WechatContact.tenant_id == tenant_id)
    contact = session.scalars(stmt.limit(1)).first()
    if contact is None:
        contact = WechatContact(
            contact_key=contact_key,
            display_name=display_name or contact_key,
            wxid=wxid,
            tenant_id=tenant_id,
        )
        session.add(contact)
        session.flush()
    contact = cast("WechatContact", contact)
    if display_name and display_name != contact.display_name:
        contact.display_name = display_name
    if wxid and not contact.wxid:
        contact.wxid = wxid
    # 身份解析：未绑定时尝试按名称自动匹配客户
    if contact.customer_id is None and contact.match_status == "unlinked":
        matched = _match_customer(session, contact.display_name, tenant_id)
        if matched is not None:
            contact.customer_id = matched.id
            contact.match_status = "auto_linked"
            logger.info(
                "wechat contact %s auto-linked to customer %s",
                contact_key,
                matched.id,
            )
    return contact


def _insert_message(
    session: Any,
    *,
    contact: WechatContact,
    role: str,
    content: str,
    msg_ts: datetime | None,
    source: str,
    tenant_id: int | None,
    client_seq: int | None = None,
) -> bool:
    """幂等插入：dedupe_hash 冲突视为重复，返回是否新插入。"""
    dedupe = _dedupe_hash(contact.contact_key, role, content, client_seq)
    existing = session.scalars(
        _sys(select(WechatMessage.id).where(WechatMessage.dedupe_hash == dedupe).limit(1))
    ).first()
    if existing is not None:
        return False
    session.add(
        WechatMessage(
            contact_id=contact.id,
            role=role,
            content=content,
            msg_ts=msg_ts,
            source=source,
            dedupe_hash=dedupe,
            tenant_id=tenant_id,
        )
    )
    if msg_ts is not None and (contact.last_message_at is None or msg_ts > contact.last_message_at):
        contact.last_message_at = msg_ts
    return True


def ingest_wechat_payload(payload: dict[str, Any], *, session: Any = None) -> dict[str, Any]:
    """处理本机上行：联系人 upsert + 身份解析 + 消息幂等入库 + 上下文回流。"""
    if not isinstance(payload, dict):
        return {
            "success": False,
            "message": "payload must be an object",
            "error_code": "bad_payload",
        }
    tenant_raw = payload.get("tenant_id")
    try:
        tenant_id = int(tenant_raw) if tenant_raw not in (None, "") else None
    except (TypeError, ValueError):
        return {"success": False, "message": "tenant_id must be int", "error_code": "bad_tenant"}
    allow_unscoped = (
        os.environ.get("XCAGI_TENANT_ALLOW_UNSCOPED_WRITE") or ""
    ).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    raw_contacts = payload.get("contacts") or []
    raw_messages = payload.get("messages") or []
    if not isinstance(raw_contacts, list) or not isinstance(raw_messages, list):
        return {
            "success": False,
            "message": "contacts/messages must be lists",
            "error_code": "bad_payload",
        }
    # 有实际内容才要求租户；空心跳载荷（连接性探测）直接放行
    if tenant_id is None and not allow_unscoped and (raw_contacts or raw_messages):
        return {
            "success": False,
            "message": "tenant_id required (or set XCAGI_TENANT_ALLOW_UNSCOPED_WRITE=1)",
            "error_code": "tenant_required",
        }

    owned = session is None
    if owned:
        session = _open_session()
    try:
        contact_keys: set[str] = set()
        contacts_upserted = 0
        for item in raw_contacts:
            if not isinstance(item, dict):
                continue
            key = _normalize_contact_key(item.get("contact_key"))
            if not key:
                continue
            _upsert_contact(
                session,
                contact_key=key,
                display_name=str(item.get("display_name") or "").strip(),
                wxid=str(item.get("wxid") or "").strip() or None,
                tenant_id=tenant_id,
            )
            contact_keys.add(key)
            contacts_upserted += 1

        messages_inserted = 0
        messages_skipped = 0
        for item in raw_messages:
            if not isinstance(item, dict):
                continue
            key = _normalize_contact_key(item.get("contact_key"))
            if not key:
                continue
            role = str(item.get("role") or "other").strip()
            if role not in _VALID_ROLES:
                role = "other"
            content = str(item.get("content") or item.get("text") or "").strip()
            if not content:
                continue
            source = str(item.get("source") or "db").strip()
            if source not in _VALID_SOURCES:
                source = "db"
            contact = session.scalars(
                _sys(select(WechatContact).where(WechatContact.contact_key == key).limit(1))
            ).first()
            if contact is None:
                contact = _upsert_contact(
                    session,
                    contact_key=key,
                    display_name="",
                    wxid=None,
                    tenant_id=tenant_id,
                )
            contact_keys.add(key)
            msg_ts = _parse_ts(item.get("msg_ts"))
            raw_seq = item.get("client_seq")
            try:
                client_seq = int(raw_seq) if raw_seq not in (None, "") else None
            except (TypeError, ValueError):
                client_seq = None
            if _insert_message(
                session,
                contact=contact,
                role=role,
                content=content[:8000],
                msg_ts=msg_ts,
                source=source,
                tenant_id=tenant_id,
                client_seq=client_seq,
            ):
                messages_inserted += 1
            else:
                messages_skipped += 1

        session.commit()
        context: dict[str, Any] = {}
        for key in sorted(contact_keys):
            context[key] = build_contact_context(
                key, tenant_id=tenant_id, session=session, include_messages=True
            )
        return {
            "success": True,
            "contacts_upserted": contacts_upserted,
            "messages_inserted": messages_inserted,
            "messages_skipped": messages_skipped,
            "context": context,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        if owned:
            session.close()


def build_contact_context(
    contact_key: str,
    *,
    tenant_id: int | None = None,
    limit: int = 30,
    include_messages: bool = True,
    session: Any = None,
) -> dict[str, Any]:
    """聚合单个联系人的客户情报（身份绑定 + 档案 + 最近消息），供回流与 AI 注入。"""
    key = _normalize_contact_key(contact_key)
    if not key:
        return {"success": False, "message": "contact_key required", "error_code": "bad_contact"}

    owned = session is None
    if owned:
        session = _open_session()
    try:
        stmt = _sys(select(WechatContact).where(WechatContact.contact_key == key))
        if tenant_id is not None:
            stmt = stmt.where(WechatContact.tenant_id == tenant_id)
        contact = session.scalars(stmt.limit(1)).first()
        if contact is None:
            return {"success": True, "known": False, "contact_key": key}

        customer_payload: dict[str, Any] | None = None
        if contact.customer_id:
            customer = session.scalars(
                _sys(select(Customer).where(Customer.id == contact.customer_id).limit(1))
            ).first()
            if customer is not None:
                customer_payload = {
                    "id": customer.id,
                    "name": customer.customer_name,
                    "contact_person": customer.contact_person,
                    "phone": customer.contact_phone,
                    "address": customer.contact_address,
                }

        recent: list[dict[str, Any]] = []
        message_count = 0
        if include_messages:
            rows = session.scalars(
                _sys(
                    select(WechatMessage)
                    .where(WechatMessage.contact_id == contact.id)
                    .order_by(WechatMessage.msg_ts.desc(), WechatMessage.id.desc())
                    .limit(max(1, min(int(limit), 200)))
                )
            ).all()
            recent = [
                {
                    "role": row.role,
                    "content": row.content,
                    "msg_ts": row.msg_ts.isoformat() if row.msg_ts else None,
                    "source": row.source,
                }
                for row in reversed(rows)
            ]

        message_count = int(
            session.scalar(
                _sys(
                    select(func.count())
                    .select_from(WechatMessage)
                    .where(WechatMessage.contact_id == contact.id)
                )
            )
            or 0
        )
        return {
            "success": True,
            "known": True,
            "contact_key": key,
            "contact": {
                "display_name": contact.display_name,
                "wxid": contact.wxid,
                "customer_id": contact.customer_id,
                "match_status": contact.match_status,
                "last_message_at": (
                    contact.last_message_at.isoformat() if contact.last_message_at else None
                ),
            },
            "customer": customer_payload,
            "recent_messages": recent,
            "message_count": message_count,
        }
    finally:
        if owned:
            session.close()


def list_wechat_contacts(
    *, tenant_id: int | None = None, limit: int = 200, session: Any = None
) -> dict[str, Any]:
    """列出联系人映射（管理端用）。"""
    owned = session is None
    if owned:
        session = _open_session()
    try:
        stmt = _sys(select(WechatContact).order_by(WechatContact.id.desc()))
        if tenant_id is not None:
            stmt = stmt.where(WechatContact.tenant_id == tenant_id)
        rows = session.scalars(stmt.limit(max(1, min(int(limit), 500)))).all()
        items = [
            {
                "id": row.id,
                "contact_key": row.contact_key,
                "display_name": row.display_name,
                "wxid": row.wxid,
                "customer_id": row.customer_id,
                "match_status": row.match_status,
                "last_message_at": row.last_message_at.isoformat() if row.last_message_at else None,
            }
            for row in rows
        ]
        return {"success": True, "items": items, "count": len(items)}
    finally:
        if owned:
            session.close()


def link_wechat_contact(
    contact_key: str,
    customer_id: int,
    *,
    tenant_id: int | None = None,
    session: Any = None,
) -> dict[str, Any]:
    """管理端人工绑定：联系人 → customers.id。"""
    key = _normalize_contact_key(contact_key)
    if not key:
        return {"success": False, "message": "contact_key required", "error_code": "bad_contact"}
    owned = session is None
    if owned:
        session = _open_session()
    try:
        contact = session.scalars(
            _sys(select(WechatContact).where(WechatContact.contact_key == key).limit(1))
        ).first()
        if contact is None:
            return {"success": False, "message": "contact not found", "error_code": "not_found"}
        customer = session.scalars(
            _sys(select(Customer).where(Customer.id == int(customer_id)).limit(1))
        ).first()
        if customer is None:
            return {"success": False, "message": "customer not found", "error_code": "not_found"}
        contact.customer_id = customer.id
        contact.match_status = "manual_linked"
        session.commit()
        return {
            "success": True,
            "contact_key": key,
            "customer_id": customer.id,
            "match_status": contact.match_status,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        if owned:
            session.close()
