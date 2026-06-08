"""内部客服：建联欢迎语。"""

from __future__ import annotations

from typing import Any


def maybe_send_connected_welcome(
    market_user_id: int,
    *,
    username: str = "",
    contact_name: str = "",
    force: bool = False,
) -> dict[str, Any]:
    from app.services.user_cs_intake_notice import _primary_contact_name
    from app.services.user_cs_pipeline import load_pipeline, save_pipeline

    uid = int(market_user_id)
    doc = load_pipeline(uid, username=username)
    if doc.get("connected_welcome_sent") and not force:
        return {"sent": False, "skipped": True, "reason": "already_sent"}
    contact = (contact_name or _primary_contact_name(uid)).strip()
    if not contact:
        return {"sent": False, "error": "未找到微信群联系人"}
    text = (
        f"{contact}，您好！我是修茈 AI 客服助理，已为您建立专属服务通道。\n"
        "后续需求采集、合同与交付进度都会在此群同步，请随时 @ 我。"
    )
    try:
        from app.desktop_automation.service import get_desktop_automation_service

        result = get_desktop_automation_service().send_wechat_message(contact, text)
        ok = bool(result.get("success")) and bool(result.get("message_sent", result.get("success")))
    except Exception as exc:
        return {"sent": False, "error": str(exc)[:300]}
    if ok:
        doc["connected_welcome_sent"] = True
        if str(doc.get("stage") or "idle") == "idle":
            doc["stage"] = "connected"
        save_pipeline(doc)
    return {"sent": ok, "message": text, "send_result": result}
