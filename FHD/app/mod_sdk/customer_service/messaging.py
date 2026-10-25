"""Customer messages and successful-delivery pipeline updates."""

from __future__ import annotations

from dataclasses import dataclass

from .customer_service_ports import Environment, MessagingServices, Payload, PipelineRepository
from .models import (
    ConnectedWelcomeBody,
    IntakeNoticeBody,
    WechatSendBody,
)


@dataclass(frozen=True, eq=False)
class MessagingHandlers:
    services: MessagingServices
    records: PipelineRepository
    environment: Environment

    async def user_cs_wechat_send(self, body: WechatSendBody) -> Payload:
        get_desktop_automation_service = self.services.get_desktop_automation_service
        uid = int(body.market_user_id)
        contact = body.contact_name.strip()
        if not contact:
            return {"success": False, "error": "请确认群名称"}
        message = body.message.strip()
        if not message:
            return {"success": False, "error": "请填写消息内容"}
        svc = get_desktop_automation_service()
        result = svc.send_wechat_message(contact, message)
        sent = bool(result.get("success")) and bool(
            result.get("message_sent", result.get("success"))
        )
        if sent:
            try:
                load_pipeline = self.records.load_pipeline
                save_pipeline = self.records.save_pipeline
                doc = load_pipeline(uid, username=body.username)
                if doc.get("stage") in ("idle", "connected"):
                    doc["stage"] = "connected"
                    save_pipeline(doc)
            except self.environment.boundary_errors():
                self.environment.logger().exception("pipeline update after wechat send failed")
        return {"success": sent, "data": result}

    async def user_cs_send_connected_welcome(self, body: ConnectedWelcomeBody) -> Payload:
        load_pipeline = self.records.load_pipeline
        maybe_send_connected_welcome = self.services.maybe_send_connected_welcome
        save_pipeline = self.records.save_pipeline
        uid = int(body.market_user_id)
        doc = load_pipeline(uid, username=body.username)
        if str(doc.get("stage") or "idle") == "idle":
            doc["stage"] = "connected"
            save_pipeline(doc)
        out = maybe_send_connected_welcome(
            uid, username=body.username, contact_name=body.contact_name.strip(), force=body.force
        )
        return {"success": bool(out.get("sent")), "data": out}

    async def user_cs_send_intake_notice(self, body: IntakeNoticeBody) -> Payload:
        load_pipeline = self.records.load_pipeline
        maybe_send_intake_form_notice = self.services.maybe_send_intake_form_notice
        save_pipeline = self.records.save_pipeline
        uid = int(body.market_user_id)
        doc = load_pipeline(uid, username=body.username)
        stage = str(doc.get("stage") or "idle")
        if stage in ("idle", "connected"):
            doc["stage"] = "intake"
            save_pipeline(doc)
        out = maybe_send_intake_form_notice(
            uid,
            username=body.username,
            contact_name=body.contact_name.strip(),
            brief=body.brief.strip(),
            force=body.force,
        )
        return {"success": bool(out.get("sent")), "data": out}
