"""软件交付包通知（微信群）。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def notify_software_delivery(
    market_user_id: int,
    *,
    username: str = "",
    force: bool = False,
) -> dict[str, Any]:
    from app.services.user_cs_intake_notice import _primary_contact_name
    from app.services.user_cs_pipeline import load_pipeline, save_pipeline

    uid = int(market_user_id)
    doc = load_pipeline(uid, username=username)
    if doc.get("software_delivery_sent_at") and not force:
        return {"success": True, "skipped": True, "reason": "already_sent"}
    contact = _primary_contact_name(uid)
    if not contact:
        return {"success": False, "error": "未绑定微信群联系人"}
    text = (
        f"{contact}，您好！\n"
        "您的 XCAGI 企业版安装包与登录说明已就绪，请查收群内后续消息或联系专属客服获取下载链接。"
    )
    try:
        from app.desktop_automation.service import get_desktop_automation_service

        result = get_desktop_automation_service().send_wechat_message(contact, text)
        ok = bool(result.get("success")) and bool(result.get("message_sent", result.get("success")))
    except RECOVERABLE_ERRORS as exc:
        return {"success": False, "error": str(exc)[:300]}
    if ok:
        doc["software_delivery_sent_at"] = _now_iso()
        save_pipeline(doc)
    return {"success": ok, "message": text, "send_result": result}
