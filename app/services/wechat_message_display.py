"""群聊消息展示：将 wxid / 原始前缀解析为联系人昵称，并自动写入 wechat_contacts 缓存。"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

_WXID_RE = re.compile(r"^wxid_[0-9a-zA-Z_-]+$")

_WXID_PREFIX_RE = re.compile(r"^(wxid_[0-9a-zA-Z_-]+)\s*[:：]\s*(.*)$", re.DOTALL)
_WXID_INLINE_RE = re.compile(r"^(wxid_[0-9a-zA-Z_-]+)\s*:\s*(.+)$", re.DOTALL)
_GROUP_BOT_RECV_RE = re.compile(r"^.+?，收到[：:]\s*(.*)$", re.DOTALL)
_NICK_SENDER_RE = re.compile(r"^([^:\n]{1,64})\s*:\s*(.+)$", re.DOTALL)

_BOT_OUTBOUND_MARKERS = (
    "我们会尽快跟进",
    "收到您的消息",
    "我是修茈科技",
    "专属 AI 助理",
    "修茈科技客服",
    "为您配置的专属",
    "软件交付流程",
    "需求确认、方案报价",
    "结合之前的上下文",
    "禁止以",
    "禁止复述",
    "只回应对方最新",
    "不能使用套话",
    "可能SUNBIRD",
    "客户的最新消息",
    "参考近期群聊",
    "不要照抄",
    "作为客服",
    "已经回复过",
    "必须换措辞",
    "不能复读",
    "从参考的近期",
    "需求信息我们已记录",
    "请随时告知",
    "如有其他需要",
    "收到您的文件",
    "感谢您分享",
    "稍后为您详细回复",
)


def _contact_db_path() -> str:
    path = (os.environ.get("WECHAT_CONTACT_DB_PATH") or "").strip()
    if path and os.path.isfile(path):
        return path
    try:
        from app.utils.path_utils import get_resource_path

        for rel in (
            ("wechat-decrypt", "decrypted", "contact", "contact.db"),
            ("wechat-decrypt", "decrypted", "contact.db"),
        ):
            candidate = get_resource_path(*rel)
            if candidate and os.path.isfile(candidate):
                return candidate
    except Exception:
        pass
    return ""


def ensure_contact_db_available() -> str:
    """
    确保解密后的 contact.db 可用（与群消息同步共用快照流程，无需用户在数据来源页手点刷新）。
    """
    path = _contact_db_path()
    if path:
        return path
    try:
        from app.services.wechat_decrypt_autoconfig import prepare_wechat_message_db_for_read

        prep = prepare_wechat_message_db_for_read(force_decrypt=False, retry_key_scan=False)
        path = (prep.get("contact_db_path") or _contact_db_path()).strip()
        if path:
            return path
        prep = prepare_wechat_message_db_for_read(force_decrypt=True, retry_key_scan=False)
        return (prep.get("contact_db_path") or _contact_db_path()).strip()
    except Exception as exc:
        logger.debug("ensure_contact_db_available: %s", exc)
        return ""


def _batch_lookup_from_contact_db(wxids: list[str]) -> dict[str, str]:
    """从解密库 contact 表批量查 remark / nick_name。"""
    path = _contact_db_path() or ensure_contact_db_available()
    if not path or not wxids:
        return {}
    out: dict[str, str] = {}
    try:
        from app.utils.external_sqlite import sqlite_conn

        with sqlite_conn(path) as conn:
            cur = conn.cursor()
            for i in range(0, len(wxids), 80):
                chunk = [w for w in wxids[i : i + 80] if w]
                if not chunk:
                    continue
                placeholders = ",".join("?" * len(chunk))
                sql = (
                    f"SELECT username, remark, nick_name FROM contact "
                    f"WHERE username IN ({placeholders}) AND (delete_flag IS NULL OR delete_flag = 0)"
                )
                try:
                    rows = cur.execute(sql, chunk).fetchall()
                except Exception:
                    sql = (
                        f"SELECT username, remark, nick_name FROM contact "
                        f"WHERE username IN ({placeholders})"
                    )
                    rows = cur.execute(sql, chunk).fetchall()
                for username, remark, nick_name in rows:
                    uname = (username or "").strip()
                    if not uname:
                        continue
                    name = (remark or nick_name or "").strip()
                    if name and name != uname:
                        out[uname] = name
    except Exception as exc:
        logger.warning("batch_lookup_from_contact_db failed: %s", exc)
    return out


def persist_wxids_to_wechat_contacts(wxids_to_names: dict[str, str]) -> int:
    """把 wxid→昵称 写入 wechat_contacts，供内部客服/数据来源搜索共用。"""
    if not wxids_to_names:
        return 0
    try:
        from app.db.init_db import ensure_wechat_contact_tables_for_active_db
        from app.db.models.wechat import WechatContact
        from app.db.session import get_db

        ensure_wechat_contact_tables_for_active_db()
        now = datetime.now()
        saved = 0
        with get_db() as db:
            for wxid, display in wxids_to_names.items():
                key = (wxid or "").strip()
                label = (display or "").strip()
                if not key or not _WXID_RE.match(key):
                    continue
                if not label or label == key:
                    continue
                row = db.query(WechatContact).filter(WechatContact.wechat_id == key).first()
                if row:
                    changed = False
                    if (row.contact_name or "").strip() != label:
                        row.contact_name = label
                        changed = True
                    if (row.remark or "").strip() != label:
                        row.remark = label
                        changed = True
                    if row.is_active != 1:
                        row.is_active = 1
                        changed = True
                    if changed:
                        row.updated_at = now
                        saved += 1
                else:
                    db.add(
                        WechatContact(
                            contact_name=label,
                            remark=label,
                            wechat_id=key,
                            contact_type="contact",
                            is_active=1,
                            is_starred=0,
                        )
                    )
                    saved += 1
            db.commit()
        if saved:
            resolve_wechat_display_name.cache_clear()
            logger.info("已自动写入 %s 个微信群成员到联系人缓存", saved)
        return saved
    except Exception as exc:
        logger.warning("persist_wxids_to_wechat_contacts failed: %s", exc)
        return 0


def _lookup_from_orm_cache(wxid: str) -> str:
    key = (wxid or "").strip()
    if not key:
        return ""
    try:
        from app.db.models.wechat import WechatContact
        from app.db.session import get_db

        with get_db() as db:
            row = (
                db.query(WechatContact)
                .filter(WechatContact.wechat_id == key, WechatContact.is_active == 1)
                .first()
            )
            if row:
                name = (row.remark or row.contact_name or "").strip()
                if name and name != key:
                    return name
    except Exception:
        pass
    return ""


@lru_cache(maxsize=4096)
def resolve_wechat_display_name(wxid: str) -> str:
    """wxid → 备注/昵称；优先 ORM，再 contact.db。"""
    key = (wxid or "").strip()
    if not key:
        return ""
    if not key.startswith("wxid_") and "@" not in key:
        return key

    cached = _lookup_from_orm_cache(key)
    if cached:
        return cached

    db_path = _contact_db_path() or ensure_contact_db_available()
    if db_path:
        try:
            from wechat_db_read import get_contact_display_name

            resolved = get_contact_display_name(db_path, key)
            if resolved and resolved.strip() and resolved.strip() != key:
                persist_wxids_to_wechat_contacts({key: resolved.strip()})
                return resolved.strip()
        except Exception as exc:
            logger.debug("resolve_wechat_display_name contact.db %s: %s", key, exc)

    return key


def batch_resolve_wechat_display_names(wxids: set[str]) -> dict[str, str]:
    """
    批量解析 wxid 昵称，并自动持久化到 wechat_contacts（无需手动画数据来源刷新）。
    """
    keys = sorted({(w or "").strip() for w in wxids if (w or "").strip().startswith("wxid_")})
    if not keys:
        return {}

    ensure_contact_db_available()
    out: dict[str, str] = {}

    for wxid in keys:
        name = _lookup_from_orm_cache(wxid)
        if name:
            out[wxid] = name

    missing = [w for w in keys if w not in out]
    if missing:
        from_db = _batch_lookup_from_contact_db(missing)
        out.update(from_db)
        if from_db:
            persist_wxids_to_wechat_contacts(from_db)

    for wxid in missing:
        if wxid not in out:
            out[wxid] = resolve_wechat_display_name(wxid)

    return out


def collect_wxids_from_messages(messages: list[dict[str, Any]]) -> set[str]:
    found: set[str] = set()
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        sender = str(msg.get("sender") or "").strip()
        if sender.startswith("wxid_"):
            found.add(sender)
            continue
        text = str(msg.get("text") or msg.get("content") or "").strip()
        wxid, _ = _split_legacy_group_text(text)
        if wxid:
            found.add(wxid)
    return found


def is_bot_outbound_group_message(text: str, *, group_name: str = "") -> bool:
    """
    判定是否为己方（客服/AI）已发出的群消息模板，避免被动轮询再次回复造成死循环。

    规则：
    - 含建联/跟进类固定话术；
    - 「群名，收到：…」且「收到」后不是 wxid_ 开头 → 己方模板（含欢迎语）；
    - 「群名，收到：wxid_…」→ 历史被动回复回声，同样跳过。
    """
    t = (text or "").strip()
    if not t:
        return True
    if any(m in t for m in _BOT_OUTBOUND_MARKERS):
        return True
    g = (group_name or "").strip()
    if g and t.startswith(f"{g}，收到"):
        return True
    m = _GROUP_BOT_RECV_RE.match(t)
    if m:
        payload = (m.group(1) or "").strip()
        if payload.startswith("wxid_"):
            return True
        return True
    return False


def is_actionable_incoming_group_message(
    msg: dict[str, Any],
    *,
    group_name: str = "",
) -> bool:
    """是否应对该条群消息做被动回复（仅真实他人发言）。"""
    if not isinstance(msg, dict):
        return False
    if str(msg.get("role") or "").strip().lower() == "self":
        return False
    text = str(msg.get("text") or msg.get("content") or "").strip()
    if not text or is_bot_outbound_group_message(text, group_name=group_name):
        return False
    sender = str(msg.get("sender") or "").strip()
    if sender:
        if sender.startswith("wxid_"):
            return True
        if "，收到" not in text:
            return True
        return False
    wxid, body = _split_legacy_group_text(text)
    if wxid:
        return True
    nick_m = _NICK_SENDER_RE.match(text)
    if nick_m and "，收到" not in text:
        return bool((nick_m.group(2) or "").strip())
    return "，收到" not in text and bool(text)


def _split_legacy_group_text(text: str) -> tuple[str | None, str]:
    """从旧版「wxid_xxx: 正文」拆出发送者与纯文本。"""
    raw = (text or "").strip()
    if not raw:
        return None, ""
    m = _WXID_PREFIX_RE.match(raw) or _WXID_INLINE_RE.match(raw)
    if m:
        return m.group(1).strip(), (m.group(2) or "").strip()
    return None, raw


def enrich_group_chat_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    为群聊上下文补全 sender / sender_display，并去掉 text 里重复的 wxid 前缀。
    已写入 sender_display 的条目会保留；仅按 wxid 变化时重新解析。
    """
    if not messages:
        return []

    wxids: set[str] = set()
    parsed: list[tuple[dict[str, Any], str | None, str]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        item = dict(msg)
        sender = str(item.get("sender") or "").strip() or None
        text = str(item.get("text") or item.get("content") or "").strip()
        if not sender:
            sender, text = _split_legacy_group_text(text)
        if not sender and text:
            nick_m = _NICK_SENDER_RE.match(text)
            if nick_m:
                nick = (nick_m.group(1) or "").strip()
                body = (nick_m.group(2) or "").strip()
                if nick and body and "，收到" not in body:
                    if nick.startswith("wxid_"):
                        sender = nick
                        text = body
                    else:
                        item["sender_display"] = nick
                        text = body
        if sender and sender.startswith("wxid_"):
            wxids.add(sender)
        parsed.append((item, sender, text))

    name_map = batch_resolve_wechat_display_names(wxids) if wxids else {}

    enriched: list[dict[str, Any]] = []
    for item, sender, text in parsed:
        if sender:
            item["sender"] = sender
            resolved = name_map.get(sender) or sender
            existing_display = str(item.get("sender_display") or "").strip()
            if (
                existing_display
                and existing_display != sender
                and not existing_display.startswith("wxid_")
            ):
                item["sender_display"] = existing_display
            else:
                item["sender_display"] = resolved
            item["text"] = text
        elif text:
            item["text"] = text
        if is_bot_outbound_group_message(str(item.get("text") or "")):
            item["role"] = "self"
        enriched.append(item)
    return enriched
