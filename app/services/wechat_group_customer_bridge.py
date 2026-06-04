"""微信群聊 ↔ 内部客服 ↔ 企业用户绑定。"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Literal

from app.db.session import get_db

logger = logging.getLogger(__name__)


def ensure_enterprise_wechat_binding_tables() -> None:
    from app.db import _get_engine
    from app.db.init_db import ensure_wechat_contact_tables_for_active_db
    from app.db.models.wechat import (
        EnterpriseWechatCustomerBinding,
    )

    ensure_wechat_contact_tables_for_active_db()
    from app.db.base import Base

    eng = _get_engine()
    Base.metadata.create_all(
        eng,
        tables=[EnterpriseWechatCustomerBinding.__table__],
        checkfirst=True,
    )


def list_group_contacts(*, keyword: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    from app.application import get_wechat_contact_app_service

    ensure_enterprise_wechat_binding_tables()
    service = get_wechat_contact_app_service()
    # 绑定页需列出全部已导入群聊；store 默认 default_starred_when_all=True 会只剩星标群
    return service.get_contacts(
        keyword=keyword,
        contact_type="group",
        starred_only=False,
        limit=limit,
        default_starred_when_all=False,
    )


def get_bindings_for_user(market_user_id: int) -> list[dict[str, Any]]:
    from app.db.models.wechat import EnterpriseWechatCustomerBinding, WechatContact

    ensure_enterprise_wechat_binding_tables()
    uid = int(market_user_id)
    with get_db() as db:
        rows = (
            db.query(EnterpriseWechatCustomerBinding, WechatContact)
            .join(
                WechatContact, WechatContact.id == EnterpriseWechatCustomerBinding.wechat_contact_id
            )
            .filter(EnterpriseWechatCustomerBinding.market_user_id == uid)
            .all()
        )
        out: list[dict[str, Any]] = []
        for binding, contact in rows:
            out.append(
                {
                    "binding_id": binding.id,
                    "market_user_id": uid,
                    "wechat_contact_id": contact.id,
                    "wechat_id": contact.wechat_id,
                    "contact_name": contact.contact_name,
                    "remark": contact.remark,
                    "contact_type": contact.contact_type,
                    "is_starred": bool(contact.is_starred),
                }
            )
        return out


def save_bindings_for_user(market_user_id: int, contact_ids: list[int]) -> dict[str, Any]:
    from app.db.models.wechat import EnterpriseWechatCustomerBinding, WechatContact

    ensure_enterprise_wechat_binding_tables()
    uid = int(market_user_id)
    ids = sorted({int(x) for x in contact_ids if int(x) > 0})
    with get_db() as db:
        db.query(EnterpriseWechatCustomerBinding).filter(
            EnterpriseWechatCustomerBinding.market_user_id == uid
        ).delete(synchronize_session=False)
        bound = 0
        for cid in ids:
            contact = (
                db.query(WechatContact)
                .filter(
                    WechatContact.id == cid,
                    WechatContact.is_active == 1,
                    WechatContact.contact_type == "group",
                )
                .first()
            )
            if not contact:
                continue
            contact.is_starred = 1
            contact.updated_at = datetime.now()
            db.add(
                EnterpriseWechatCustomerBinding(
                    market_user_id=uid,
                    wechat_contact_id=cid,
                    display_name=contact.contact_name,
                )
            )
            bound += 1
    return {"success": True, "bound": bound, "contact_ids": ids}


def sync_bound_groups_from_live_wechat(
    market_user_id: int,
    *,
    message_limit: int = 80,
    mode: Literal["poll", "manual", "feed"] = "manual",
) -> dict[str, Any]:
    """
    统一同步入口：本机微信库快照 → 强制解密 → 对每个绑定群 refresh_messages。
    与数据来源「刷新聊天记录」及轮询客服共用，避免多套 force_refresh 策略。
    """
    from app.application import get_wechat_contact_app_service
    from app.services.wechat_decrypt_autoconfig import (
        _keys_file_usable,
        load_runtime_config,
        prepare_wechat_message_db_for_read,
    )

    ensure_enterprise_wechat_binding_tables()
    uid = int(market_user_id)
    bindings = get_bindings_for_user(uid)
    contact_ids = [int(b["wechat_contact_id"]) for b in bindings if b.get("wechat_contact_id")]

    snapshot_result: dict[str, Any] = {
        "success": False,
        "message": "未执行快照",
        "rebuilt": False,
        "skipped": False,
    }
    # poll/manual 必须复制+解密本机库，不能只读旧 WECHAT_MSG_DB_PATH（否则会「假刷新」）
    try:
        from app.services.wechat_db_snapshot import ensure_snapshot_message_db_ready

        snapshot_result = ensure_snapshot_message_db_ready(
            force=(mode in ("poll", "manual")),
        )
        if not snapshot_result.get("success"):
            logger.warning("ensure_snapshot_message_db_ready: %s", snapshot_result.get("message"))
    except Exception as exc:
        logger.warning("ensure_snapshot_message_db_ready failed: %s", exc)
        snapshot_result = {
            "success": False,
            "message": str(exc)[:200],
            "rebuilt": False,
            "skipped": False,
        }

    if not contact_ids:
        return {
            "success": False,
            "message": "该企业尚未保存任何群聊绑定：请在左侧勾选群聊后点击「保存绑定」，再点「同步群聊」",
            "synced": 0,
            "failed": 0,
            "contact_ids": [],
            "details": [],
            "snapshot": snapshot_result,
            "messages_pulled_this_round": 0,
            "messages_pulled": 0,
            "latest_message_ts": 0.0,
            "latest_message_label": "",
            "stale": False,
            "stale_reason": "",
            "message_db_ready": False,
            "mode": mode,
        }

    # 轮询且本机库指纹未变时跳过重复解密，缩短「发现消息 → 发微信」链路
    force_decrypt = mode in ("manual", "feed") or (
        mode == "poll" and not snapshot_result.get("skipped")
    )
    force_live_refresh = mode in ("poll", "manual", "feed")
    msg_db = prepare_wechat_message_db_for_read(
        force_decrypt=force_decrypt,
        retry_key_scan=False,
    )
    if not msg_db.get("message_db_path"):
        msg_db = prepare_wechat_message_db_for_read(force_decrypt=True, retry_key_scan=True)
    if msg_db.get("stale") and msg_db.get("message_db_path"):
        try:
            from app.services.wechat_db_snapshot import ensure_snapshot_message_db_ready

            ensure_snapshot_message_db_ready(force=True)
        except Exception as exc:
            logger.warning("ensure_snapshot_message_db_ready: %s", exc)
        msg_db = prepare_wechat_message_db_for_read(force_decrypt=True, retry_key_scan=False)
    if not msg_db.get("message_db_path"):
        tk = str(load_runtime_config().get("toolkit_dir") or "").strip()
        keys_path = os.path.join(tk, "all_keys.json") if tk else ""
        if tk and not _keys_file_usable(keys_path):
            msg_db = prepare_wechat_message_db_for_read(force_decrypt=True, retry_key_scan=True)

    if not msg_db.get("message_db_path"):
        return {
            "success": False,
            "message": "未找到微信消息库。请先在「数据来源」配置微信目录并扫描密钥。",
            "synced": 0,
            "failed": len(contact_ids),
            "contact_ids": contact_ids,
            "details": [],
            "snapshot": snapshot_result,
            "messages_pulled_this_round": 0,
            "messages_pulled": 0,
            "latest_message_ts": 0.0,
            "latest_message_label": "",
            "stale": bool(msg_db.get("stale")),
            "stale_reason": str(msg_db.get("stale_reason") or ""),
            "message_db_ready": False,
            "mode": mode,
        }

    from app.services.wechat_message_display import ensure_contact_db_available

    ensure_contact_db_available()

    service = get_wechat_contact_app_service()
    synced = 0
    failed = 0
    messages_pulled_this_round = 0
    latest_ts = 0.0
    details: list[dict[str, Any]] = []
    for cid in contact_ids:
        name = ""
        for b in bindings:
            if int(b.get("wechat_contact_id") or 0) == cid:
                name = str(b.get("contact_name") or b.get("remark") or "")
                break
        try:
            result = service.refresh_messages(
                int(cid),
                limit=message_limit,
                force_live_refresh=force_live_refresh,
            )
            pulled = int(result.get("count") or 0)
            pulled_new = int(result.get("count_new") or 0)
            ok = bool(result.get("success"))
            details.append(
                {
                    "contact_id": cid,
                    "contact_name": name,
                    "success": ok,
                    "count": pulled,
                    "count_new": pulled_new,
                    "message": result.get("message"),
                }
            )
            if ok:
                synced += 1
                messages_pulled_this_round += pulled_new
                for m in service.get_contact_context(int(cid)) or []:
                    if isinstance(m, dict):
                        latest_ts = max(latest_ts, _message_ts(m))
                service.star_contact(int(cid), starred=True)
            else:
                failed += 1
        except Exception as exc:
            failed += 1
            details.append(
                {
                    "contact_id": cid,
                    "contact_name": name,
                    "success": False,
                    "message": str(exc)[:200],
                }
            )
            logger.warning("绑定群刷新失败 id=%s: %s", cid, exc)

    stale_note = ""
    if msg_db.get("stale"):
        stale_note = str(msg_db.get("stale_reason") or "解密库落后于本机微信")

    latest_label = ""
    if latest_ts > 0:
        latest_label = datetime.fromtimestamp(latest_ts).strftime("%m-%d %H:%M")

    msg = (
        f"已从本机微信库刷新 {synced} 个绑定群"
        f"（失败 {failed}，新增 {messages_pulled_this_round} 条）"
    )
    if latest_label:
        msg = f"{msg}，库内最新 {latest_label}"
    if stale_note:
        msg = f"{msg}（⚠ {stale_note}）"
    elif messages_pulled_this_round == 0 and synced > 0:
        msg = f"{msg}（⚠ 本轮无新入库，库内可能仍是旧记录）"

    return {
        "success": synced > 0 and not msg_db.get("stale"),
        "message": msg,
        "synced": synced,
        "failed": failed,
        "messages_pulled": messages_pulled_this_round,
        "messages_pulled_this_round": messages_pulled_this_round,
        "latest_message_ts": latest_ts,
        "latest_message_label": latest_label,
        "groups_total": len(contact_ids),
        "contact_ids": contact_ids,
        "details": details,
        "stale": bool(msg_db.get("stale")),
        "stale_reason": stale_note,
        "message_db_ready": bool(msg_db.get("message_db_path")),
        "snapshot": snapshot_result,
        "mode": mode,
    }


def refresh_bound_group_messages(
    market_user_id: int,
    *,
    message_limit: int = 80,
    force_refresh: bool = True,
) -> dict[str, Any]:
    """
    与「数据来源 → 刷新聊天记录」相同：先快照/解密 message 库，再对每个绑定群
    调用 refresh_messages(contact_id)。
    """
    mode: Literal["manual", "feed"] = "manual" if force_refresh else "feed"
    return sync_bound_groups_from_live_wechat(
        int(market_user_id),
        message_limit=message_limit,
        mode=mode,
    )


def sync_group_messages(
    *,
    market_user_id: int | None = None,
    group_limit: int = 30,
    message_limit: int = 80,
    force_refresh: bool = True,
) -> dict[str, Any]:
    """从本机微信解密后的 message_0.db 拉取群聊消息写入 wechat_contact_context。"""
    if market_user_id is not None:
        mode: Literal["manual", "feed"] = "manual" if force_refresh else "feed"
        return sync_bound_groups_from_live_wechat(
            int(market_user_id),
            message_limit=message_limit,
            mode=mode,
        )

    from app.application import get_wechat_contact_app_service
    from app.services.wechat_decrypt_autoconfig import prepare_wechat_message_db_for_read

    ensure_enterprise_wechat_binding_tables()
    msg_db = prepare_wechat_message_db_for_read(
        force_decrypt=bool(force_refresh), retry_key_scan=False
    )
    if not msg_db.get("message_db_path"):
        msg_db = prepare_wechat_message_db_for_read(force_decrypt=True, retry_key_scan=False)
    if (force_refresh or msg_db.get("stale")) and msg_db.get("message_db_path"):
        try:
            from app.services.wechat_db_snapshot import ensure_snapshot_message_db_ready

            ensure_snapshot_message_db_ready(force=True)
        except Exception as exc:
            logger.warning("ensure_snapshot_message_db_ready: %s", exc)
        msg_db = prepare_wechat_message_db_for_read(force_decrypt=True, retry_key_scan=False)
    if not msg_db.get("message_db_path"):
        from app.services.wechat_decrypt_autoconfig import _keys_file_usable, load_runtime_config

        tk = str(load_runtime_config().get("toolkit_dir") or "").strip()
        keys_path = os.path.join(tk, "all_keys.json") if tk else ""
        if tk and not _keys_file_usable(keys_path):
            msg_db = prepare_wechat_message_db_for_read(force_decrypt=True, retry_key_scan=True)
    if not msg_db.get("message_db_path"):
        return {
            "success": False,
            "message": "未找到微信消息库。请先在「数据来源」配置微信目录并扫描密钥、同步聊天记录。",
            "synced": 0,
            "failed": 0,
        }
    stale_note = ""
    if msg_db.get("stale"):
        stale_note = str(msg_db.get("stale_reason") or "解密库落后于本机微信，仅同步已解密部分")

    from app.services.wechat_message_display import ensure_contact_db_available

    ensure_contact_db_available()

    service = get_wechat_contact_app_service()
    groups = service.get_contacts(contact_type="group", limit=group_limit)

    synced = 0
    failed = 0
    for g in groups:
        cid = g.get("id")
        if cid is None:
            continue
        try:
            result = service.refresh_messages(int(cid), limit=message_limit)
            pulled = int(result.get("count") or 0)
            if result.get("success"):
                if pulled > 0:
                    synced += 1
                    service.star_contact(int(cid), starred=True)
                elif force_refresh:
                    synced += 1
                    service.star_contact(int(cid), starred=True)
                else:
                    logger.info("群消息同步无新内容 id=%s: %s", cid, result.get("message"))
            else:
                failed += 1
                logger.info("群消息同步跳过 id=%s: %s", cid, result.get("message"))
        except Exception as exc:
            failed += 1
            logger.warning("群消息同步失败 id=%s: %s", cid, exc)

    msg = f"已同步 {synced} 个群聊消息（失败 {failed}）"
    if stale_note and synced == 0:
        msg = f"{stale_note}。{msg}"
    elif stale_note:
        msg = f"{msg}（{stale_note}）"
    return {
        "success": True,
        "message": msg,
        "synced": synced,
        "failed": failed,
        "groups_total": len(groups),
        "stale": bool(msg_db.get("stale")),
    }


def build_starred_group_feed(
    *,
    limit: int = 10,
    market_user_id: int | None = None,
) -> list[dict[str, Any]]:
    from app.application import get_wechat_contact_app_service

    ensure_enterprise_wechat_binding_tables()
    service = get_wechat_contact_app_service()

    if market_user_id is not None:
        bindings = get_bindings_for_user(int(market_user_id))
        items: list[dict[str, Any]] = []
        for b in bindings:
            cid = b.get("wechat_contact_id")
            if cid is None:
                continue
            contact = service.get_contact_by_id(int(cid)) or b
            messages = service.get_contact_context(int(cid))
            name = (contact.get("contact_name") or contact.get("remark") or "群聊").strip()
            # 列表展示与数据来源「查看聊天记录」一致：按时间取真正最新一条
            last = _latest_context_message(messages)
            if not last:
                continue
            text = _message_text(last)
            ts = _message_ts(last)
            role = str(last.get("role") or "").strip().lower()
            sender_disp = str(last.get("sender_display") or last.get("sender") or "").strip()
            if not sender_disp and role == "self":
                sender_disp = "我"
            items.append(
                {
                    "id": f"{cid}-{ts}",
                    "contact_id": cid,
                    "contact_name": name,
                    "nickname": name,
                    "content": text,
                    "message": text,
                    "last_message_preview": text,
                    "last_message_time": ts,
                    "timestamp": ts,
                    "contact_type": "group",
                    "is_group": True,
                    "market_user_id": int(market_user_id),
                    "sender_display": sender_disp,
                    "role": role or None,
                }
            )
        items.sort(key=lambda r: float(r.get("timestamp") or 0), reverse=True)
        return items[:limit]

    contacts = service.get_contacts(contact_type="group", starred_only=True, limit=80)
    items = []
    for c in contacts:
        cid = c.get("id")
        if cid is None:
            continue
        messages = service.get_contact_context(int(cid))
        name = (c.get("contact_name") or c.get("remark") or "群聊").strip()
        last = _latest_peer_message(messages, group_name=name)
        if not last:
            continue
        text = _message_text(last)
        ts = _message_ts(last)
        items.append(
            {
                "id": f"{cid}-{ts}",
                "contact_id": cid,
                "contact_name": name,
                "nickname": name,
                "content": text,
                "message": text,
                "timestamp": ts,
                "contact_type": "group",
                "is_group": True,
                "sender_display": last.get("sender_display") or last.get("sender") or "",
            }
        )
    items.sort(key=lambda r: float(r.get("timestamp") or 0), reverse=True)
    return items[:limit]


def _message_text(msg: dict[str, Any]) -> str:
    for key in ("content", "message", "text", "raw_text", "body"):
        val = msg.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


def _message_ts(msg: dict[str, Any]) -> float:
    for key in ("timestamp", "create_time", "created_at", "time"):
        val = msg.get(key)
        if val is None:
            continue
        try:
            return float(val)
        except (TypeError, ValueError):
            continue
    return 0.0


def _latest_context_message(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """从已同步的上下文里取最新一条（按 timestamp）。"""
    if not messages:
        return None
    best: dict[str, Any] | None = None
    best_ts = -1.0
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        ts = _message_ts(msg)
        if ts > best_ts:
            best_ts = ts
            best = msg
    if best is not None and best_ts > 0:
        return best
    for msg in messages:
        if isinstance(msg, dict) and _message_text(msg):
            return msg
    return None


def _latest_peer_message(
    messages: list[dict[str, Any]],
    *,
    group_name: str = "",
) -> dict[str, Any] | None:
    """摘要/进度用：取最新一条「他人真实发言」，跳过己方模板与 role=self。"""
    from app.services.wechat_message_display import is_bot_outbound_group_message

    if not messages:
        return None
    ranked: list[tuple[float, dict[str, Any]]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        text = _message_text(msg)
        if not text:
            continue
        ts = _message_ts(msg)
        ranked.append((ts, msg))
    ranked.sort(key=lambda x: x[0], reverse=True)

    from app.services.wechat_passive_group_monitor import is_prompt_echo_reply

    for ts, msg in ranked:
        if str(msg.get("role") or "").strip().lower() == "self":
            continue
        text = _message_text(msg)
        if is_bot_outbound_group_message(text, group_name=group_name):
            continue
        if is_prompt_echo_reply(text):
            continue
        return msg

    for ts, msg in ranked:
        text = _message_text(msg)
        if str(msg.get("role") or "").strip().lower() == "self":
            continue
        if is_bot_outbound_group_message(text, group_name=group_name):
            continue
        if is_prompt_echo_reply(text):
            continue
        return msg
    return ranked[0][1] if ranked else None
