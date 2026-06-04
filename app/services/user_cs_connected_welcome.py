"""已建联阶段：自动向微信群发送欢迎/建联话术。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


def build_connected_welcome_message(
    *, client_name: str = "", company_name: str = "修茈科技"
) -> str:
    who = (client_name or "您好").strip()
    if not who.endswith("好") and who != "您好":
        greeting = f"{who}，您好"
    else:
        greeting = who if who else "您好"

    return (
        f"{greeting}！\n\n"
        f"我是{company_name}为您配置的专属 AI 助理。"
        f"接下来我将按软件交付流程，在群内为您跟进需求确认、方案报价、合同签约与交付验收等环节。\n\n"
        f"如有任何问题，您可以直接在本群留言，我会及时回复。"
    )


def _primary_contact_name(market_user_id: int) -> Optional[str]:
    from app.services.wechat_group_customer_bridge import get_bindings_for_user

    bindings = get_bindings_for_user(int(market_user_id))
    if not bindings:
        return None
    first = bindings[0]
    name = str(first.get("contact_name") or first.get("remark") or "").strip()
    return name or None


def maybe_send_connected_welcome(
    market_user_id: int,
    *,
    username: str = "",
    contact_name: str = "",
    force: bool = False,
) -> dict[str, Any]:
    """
    进入已建联阶段时发送欢迎语（仅发一次，除非 force=True）。
    返回 { attempted, sent, skipped, reason, message, contact_name, send_result }
    """
    from app.desktop_automation.service import get_desktop_automation_service
    from app.services.user_cs_pipeline import load_pipeline, save_pipeline

    uid = int(market_user_id)
    doc = load_pipeline(uid, username=username)
    stage = str(doc.get("stage") or "idle")
    if stage != "connected" and not force:
        return {
            "attempted": False,
            "sent": False,
            "skipped": True,
            "reason": "not_connected_stage",
            "stage": stage,
        }

    if doc.get("connected_welcome_sent") and not force:
        return {
            "attempted": False,
            "sent": False,
            "skipped": True,
            "reason": "already_sent",
            "sent_at": doc.get("connected_welcome_sent_at"),
        }

    contact = (contact_name or _primary_contact_name(uid) or "").strip()
    if not contact:
        return {
            "attempted": False,
            "sent": False,
            "skipped": True,
            "reason": "no_binding_contact",
        }

    display_name = (username or doc.get("username") or "").strip()
    text = build_connected_welcome_message(client_name=display_name)

    try:
        svc = get_desktop_automation_service()
        send_result = svc.send_wechat_message(contact, text)
    except Exception as exc:
        logger.exception("connected welcome send failed uid=%s", uid)
        return {
            "attempted": True,
            "sent": False,
            "skipped": False,
            "reason": "send_error",
            "error": str(exc)[:500],
            "contact_name": contact,
            "message": text,
        }

    ok = bool(send_result.get("success")) and bool(
        send_result.get("message_sent", send_result.get("success"))
    )
    if ok:
        now = datetime.now(timezone.utc).isoformat()
        doc["connected_welcome_sent"] = True
        doc["connected_welcome_sent_at"] = now
        doc["connected_welcome_message"] = text
        doc["stage"] = "connected"
        timeline = list(doc.get("timeline") or [])
        timeline.append({"stage": "connected", "at": now, "source": "connected_welcome"})
        doc["timeline"] = timeline[-30:]
        save_pipeline(doc)

    return {
        "attempted": True,
        "sent": ok,
        "skipped": False,
        "reason": "ok" if ok else "send_failed",
        "contact_name": contact,
        "message": text,
        "send_result": send_result,
        "error": ""
        if ok
        else str(send_result.get("error") or send_result.get("message") or "send failed"),
    }
