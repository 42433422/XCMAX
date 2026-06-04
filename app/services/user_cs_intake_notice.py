"""需求采集阶段：向微信群发送官网表单链接与填写说明。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


def build_intake_form_notice_message(
    *,
    form_url: str,
    client_name: str = "",
    brief: str = "",
) -> str:
    """生成需求采集阶段群消息（含专属表单链接与审核码说明）。"""
    url = (form_url or "").strip()
    if not url:
        raise ValueError("form_url 不能为空")

    who = (client_name or "您好").strip()
    if not who.endswith("好") and who != "您好":
        greeting = f"{who}，您好"
    else:
        greeting = who if who else "您好"

    lines = [
        f"{greeting}！",
        "",
        "接下来进入需求采集环节。为便于我们准确评估方案与报价，请您填写下方需求表单（约 3–5 分钟）：",
        "",
        url,
        "",
        "填写完成后页面会显示审核码（形如 XC-000123），请把审核码发在本群，便于我们归档并跟进。",
        "若您更习惯口头沟通，也可直接在群内留言，我们会整理后与您确认。",
    ]
    brief = (brief or "").strip()
    if brief:
        lines.extend(
            [
                "",
                "（客服备注）本次沟通背景摘要：",
                brief,
            ]
        )
    lines.extend(["", "感谢配合！"])
    return "\n".join(lines)


def _primary_contact_name(market_user_id: int) -> Optional[str]:
    from app.services.wechat_group_customer_bridge import get_bindings_for_user

    bindings = get_bindings_for_user(int(market_user_id))
    if not bindings:
        return None
    first = bindings[0]
    name = str(first.get("contact_name") or first.get("remark") or "").strip()
    return name or None


def maybe_send_intake_form_notice(
    market_user_id: int,
    *,
    username: str = "",
    contact_name: str = "",
    brief: str = "",
    force: bool = False,
) -> dict[str, Any]:
    """
    在需求采集阶段向微信群发送表单链接与说明（默认仅发一次，force 可重发）。
    返回 { attempted, sent, skipped, reason, message, contact_name, form_url, send_result }
    """
    from app.desktop_automation.service import get_desktop_automation_service
    from app.services.user_cs_demand_form import build_intake_form_url
    from app.services.user_cs_pipeline import _stage_rank, load_pipeline, save_pipeline

    uid = int(market_user_id)
    doc = load_pipeline(uid, username=username)
    stage = str(doc.get("stage") or "idle")
    if _stage_rank(stage) < _stage_rank("intake") and not force:
        return {
            "attempted": False,
            "sent": False,
            "skipped": True,
            "reason": "before_intake_stage",
            "stage": stage,
        }

    if doc.get("intake_form_notice_sent") and not force:
        return {
            "attempted": False,
            "sent": False,
            "skipped": True,
            "reason": "already_sent",
            "sent_at": doc.get("intake_form_notice_sent_at"),
        }

    contact = (contact_name or _primary_contact_name(uid) or "").strip()
    if not contact:
        return {
            "attempted": False,
            "sent": False,
            "skipped": True,
            "reason": "no_binding_contact",
        }

    from app.services.user_cs_demand_form import resolve_intake_prefill

    pre = resolve_intake_prefill(uid, username=username)
    greeting = pre["greeting_name"]
    form_url = build_intake_form_url(
        uid,
        brief=brief,
        client_name=greeting,
        company=pre["company"],
        contact_name=pre["contact_name"],
    )
    text = build_intake_form_notice_message(
        form_url=form_url,
        client_name=greeting,
        brief=brief,
    )

    try:
        svc = get_desktop_automation_service()
        send_result = svc.send_wechat_message(contact, text)
    except Exception as exc:
        logger.exception("intake form notice send failed uid=%s", uid)
        return {
            "attempted": True,
            "sent": False,
            "skipped": False,
            "reason": "send_error",
            "error": str(exc)[:500],
            "contact_name": contact,
            "message": text,
            "form_url": form_url,
        }

    ok = bool(send_result.get("success")) and bool(
        send_result.get("message_sent", send_result.get("success"))
    )
    if ok:
        now = datetime.now(timezone.utc).isoformat()
        doc["intake_form_notice_sent"] = True
        doc["intake_form_notice_sent_at"] = now
        doc["intake_form_notice_message"] = text
        doc["intake_sent"] = True
        doc["intake_form_url"] = form_url
        if _stage_rank(str(doc.get("stage") or "idle")) < _stage_rank("intake"):
            doc["stage"] = "intake"
        timeline = list(doc.get("timeline") or [])
        timeline.append({"stage": "intake", "at": now, "source": "intake_form_notice"})
        doc["timeline"] = timeline[-30:]
        save_pipeline(doc)

    return {
        "attempted": True,
        "sent": ok,
        "skipped": False,
        "reason": "ok" if ok else "send_failed",
        "contact_name": contact,
        "message": text,
        "form_url": form_url,
        "send_result": send_result,
        "error": ""
        if ok
        else str(send_result.get("error") or send_result.get("message") or "send failed"),
    }
