"""Delivery plans, signoff, payment checks and progress notifications."""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    DeliveryPaymentBody,
    DeliveryPlanBody,
    PipelineBody,
)
from .customer_service_ports import DeliveryServices, Environment, Payload, PipelineRepository


@dataclass(frozen=True, eq=False)
class DeliveryHandlers:
    services: DeliveryServices
    records: PipelineRepository
    environment: Environment

    def user_cs_delivery_get(self, market_user_id: int, username: str = "") -> Payload:
        ensure_delivery_on_doc = self.services.ensure_delivery_on_doc
        load_pipeline = self.records.load_pipeline
        doc = ensure_delivery_on_doc(load_pipeline(int(market_user_id), username=username))
        return {
            "success": True,
            "data": {
                "delivery": doc.get("delivery"),
                "payment": doc.get("payment"),
                "invoice": doc.get("invoice"),
            },
        }

    def user_cs_delivery_save_plan(self, body: DeliveryPlanBody) -> Payload:
        ensure_delivery_on_doc = self.services.ensure_delivery_on_doc
        load_pipeline = self.records.load_pipeline
        save_pipeline = self.records.save_pipeline
        set_pipeline_stage = self.services.set_pipeline_stage
        update_delivery_plan = self.services.update_delivery_plan
        uid = int(body.market_user_id)
        doc = ensure_delivery_on_doc(load_pipeline(uid, username=body.username))
        doc = update_delivery_plan(
            doc,
            expected_delivery_at=body.expected_delivery_at,
            milestones=body.milestones or None,
            start_delivery=body.start_delivery,
        )
        target_stage = (body.stage or "").strip()
        if body.start_delivery and (not target_stage):
            target_stage = "delivering"
        if target_stage:
            delivery = doc["delivery"]
            try:
                doc = set_pipeline_stage(
                    uid,
                    target_stage,
                    username=body.username,
                    source="delivery_plan",
                    note="delivery_plan_saved",
                )
            except ValueError:
                return {"success": False, "error": "请求参数无效"}
            doc["delivery"] = delivery
        doc = save_pipeline(doc)
        return {"success": True, "data": {"pipeline": doc}}

    def user_cs_delivery_signoff_request(self, body: PipelineBody) -> Payload:
        create_signoff_request = self.services.create_signoff_request
        try:
            out = create_signoff_request(
                int(body.market_user_id),
                username=body.username,
                signed_by=body.note or "",
                notes=body.note or "",
            )
            return {"success": True, "data": out}
        except ValueError:
            return {"success": False, "error": "请求参数无效"}

    def user_cs_delivery_signoff_confirm(self, body: PipelineBody) -> Payload:
        confirm_signoff = self.services.confirm_signoff
        sid = int(getattr(body, "signoff_id", 0) or 0)
        if sid <= 0:
            return {"success": False, "error": "signoff_id required"}
        try:
            out = confirm_signoff(
                sid, market_user_id=int(body.market_user_id), username=body.username
            )
            return {"success": True, "data": out}
        except ValueError:
            return {"success": False, "error": "请求参数无效"}

    def user_cs_delivery_notify_progress(self, body: PipelineBody) -> Payload:
        _primary_contact_name = self.services._primary_contact_name
        build_delivery_progress_message = self.services.build_delivery_progress_message
        ensure_delivery_on_doc = self.services.ensure_delivery_on_doc
        get_desktop_automation_service = self.services.get_desktop_automation_service
        load_pipeline = self.records.load_pipeline
        save_pipeline = self.records.save_pipeline
        uid = int(body.market_user_id)
        doc = ensure_delivery_on_doc(load_pipeline(uid, username=body.username))
        contact = _primary_contact_name(uid) or ""
        if not contact:
            return {"success": False, "error": "未绑定微信群联系人"}
        text = build_delivery_progress_message(
            doc, client_name=str(doc.get("username") or body.username or "")
        )
        try:
            send_result = get_desktop_automation_service().send_wechat_message(contact, text)
        except self.environment.boundary_errors():
            self.environment.logger().exception("customer service send failed")
            return {"success": False, "error": "客服消息发送服务暂时不可用"}
        ok = bool(send_result.get("success")) and bool(
            send_result.get("message_sent", send_result.get("success"))
        )
        if ok:
            delivery = dict(doc.get("delivery") or {})
            delivery["last_progress_notice_at"] = self.environment.now()
            doc["delivery"] = delivery
            doc = save_pipeline(doc)
        return {
            "success": ok,
            "data": {"message": text, "send_result": send_result},
            "error": "" if ok else str(send_result.get("error") or "发送失败"),
        }

    def user_cs_delivery_notify_software(self, body: PipelineBody) -> Payload:
        notify_software_delivery = self.services.notify_software_delivery
        force = bool(getattr(body, "force", False))
        out = notify_software_delivery(
            int(body.market_user_id), username=body.username, force=force
        )
        if not out.get("ok"):
            return {"success": False, "error": out.get("error") or "发送失败", "data": out}
        return {"success": True, "data": out}

    def user_cs_delivery_check_payment(self, body: DeliveryPaymentBody) -> Payload:
        ensure_delivery_on_doc = self.services.ensure_delivery_on_doc
        load_pipeline = self.records.load_pipeline
        save_pipeline = self.records.save_pipeline
        try_confirm_payment_and_invoice = self.services.try_confirm_payment_and_invoice
        uid = int(body.market_user_id)
        doc = ensure_delivery_on_doc(load_pipeline(uid, username=body.username))
        outcome = try_confirm_payment_and_invoice(
            uid,
            doc,
            message_texts=[],
            force=body.force_confirm,
            payment_reference=body.payment_reference,
        )
        doc["payment"] = outcome.get("payment") or doc.get("payment")
        if outcome.get("invoice"):
            doc["invoice"] = outcome.get("invoice")
            doc["crm_invoice_id"] = outcome.get("invoice", {}).get("id")
        doc = save_pipeline(doc)
        return {
            "success": True,
            "data": {
                "pipeline": doc,
                "payment_detected": outcome.get("payment_detected"),
                "invoice_created": outcome.get("invoice_created"),
                "invoice": outcome.get("invoice"),
                "market_payment": outcome.get("market_payment"),
                "error": outcome.get("error") or "",
            },
        }
