"""Demand intake, form synchronization and customer-facing notice preparation."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from .models import (
    DemandFormManualBody,
    DemandFormRedeemCodeBody,
    DemandFormSyncBody,
    DemandIntakeBody,
    LandingFunnelSyncBody,
    PipelineBody,
)
from .customer_service_ports import Employee, Environment, IntakeServices, Payload, PipelineRepository


@dataclass(frozen=True, eq=False)
class IntakeHandlers:
    services: IntakeServices
    records: PipelineRepository
    environment: Environment
    employee: Employee

    async def user_cs_demand_intake(self, body: DemandIntakeBody) -> Payload:
        build_intake_form_url = self.services.build_intake_form_url
        signed_url = ""
        if body.market_user_id:
            signed_url = build_intake_form_url(
                int(body.market_user_id),
                brief=body.brief,
                client_name=body.client_name,
                base_url=body.form_url or "",
            )
        payload = {
            "action": "demand_intake",
            "brief": body.brief,
            "client_name": body.client_name,
            "form_url": signed_url or body.form_url,
            "channel": body.channel,
            "use_llm": body.use_llm,
        }
        result = await self.employee(payload)
        mark_demand_intake_sent = self.services.mark_demand_intake_sent
        normalize_demand_intake_result = self.services.normalize_demand_intake_result
        result, employee_ok = normalize_demand_intake_result(
            result,
            signed_url=signed_url,
            fallback_url=body.form_url or "https://xiu-ci.com/contact.html",
        )
        if body.market_user_id and employee_ok:
            try:
                mark_demand_intake_sent(int(body.market_user_id))
            except self.environment.boundary_errors():
                self.environment.logger().exception("pipeline update after demand intake failed")
        return result

    async def user_cs_demand_form_sync(self, body: DemandFormSyncBody, request: Request) -> Payload:
        apply_landing_submission_to_funnel = self.services.apply_landing_submission_to_funnel
        verify_webhook_secret = self.services.verify_webhook_secret
        if not verify_webhook_secret(request.headers.get("x-intake-webhook-secret")):
            return {"success": False, "error": "unauthorized"}
        doc = apply_landing_submission_to_funnel(body.model_dump(), notify_wechat=True)
        return {
            "success": True,
            "data": {
                "pipeline": doc,
                "finalize": {
                    "erp_linked": bool(doc.get("erp_customer_id")),
                    "erp_customer_id": doc.get("erp_customer_id"),
                    "erp_customer_name": doc.get("erp_customer_name"),
                    "crm_funnel_synced_at": doc.get("crm_funnel_synced_at"),
                    "crm_opportunity_id": doc.get("crm_opportunity_id"),
                    "crm_quote_id": doc.get("crm_quote_id"),
                    "intake_done_notice_sent": doc.get("intake_done_notice_sent"),
                },
            },
        }

    async def user_cs_landing_funnel_sync(
        self, body: LandingFunnelSyncBody, request: Request
    ) -> Payload:
        apply_landing_submission_to_funnel = self.services.apply_landing_submission_to_funnel
        verify_webhook_secret = self.services.verify_webhook_secret
        if not verify_webhook_secret(request.headers.get("x-intake-webhook-secret")):
            return {"success": False, "error": "unauthorized"}
        payload = body.model_dump(exclude_none=True)
        doc = apply_landing_submission_to_funnel(
            payload, notify_wechat=bool(payload.get("market_user_id"))
        )
        return {
            "success": True,
            "data": {
                "pipeline": doc if int(payload.get("market_user_id") or 0) > 0 else None,
                "crm_opportunity_id": doc.get("crm_opportunity_id"),
                "anonymous_lead": bool(doc.get("anonymous_lead")),
            },
        }

    def user_cs_demand_form_link(
        self, market_user_id: int, client_name: str = "", brief: str = ""
    ) -> Payload:
        build_intake_form_url = self.services.build_intake_form_url
        url = build_intake_form_url(int(market_user_id), brief=brief, client_name=client_name)
        return {"success": True, "data": {"form_url": url}}

    def user_cs_demand_form_notice_message(
        self, market_user_id: int, client_name: str = "", brief: str = ""
    ) -> Payload:
        build_intake_form_notice_message = self.services.build_intake_form_notice_message
        build_intake_form_url = self.services.build_intake_form_url
        uid = int(market_user_id)
        url = build_intake_form_url(uid, brief=brief, client_name=client_name)
        text = build_intake_form_notice_message(form_url=url, contact_name=client_name, brief=brief)
        return {"success": True, "data": {"form_url": url, "message": text}}

    async def user_cs_demand_form_manual(self, body: DemandFormManualBody) -> Payload:
        apply_landing_submission_to_pipeline = self.services.apply_landing_submission_to_pipeline
        doc = apply_landing_submission_to_pipeline(
            {
                "market_user_id": int(body.market_user_id),
                "username": body.username,
                "name": body.name.strip(),
                "email": body.email.strip(),
                "phone": body.phone.strip(),
                "company": body.company.strip(),
                "message": body.message.strip(),
                "desktop_os": body.desktop_os.strip(),
                "need_mobile": body.need_mobile,
                "submitted_at": self.environment.now(),
                "intake_source": "manual_card",
            }
        )
        return {"success": True, "data": {"pipeline": doc}}

    async def user_cs_demand_form_by_audit_code(
        self, audit_code: str, market_user_id: int | None = None
    ) -> Payload:
        fetch_submission_by_audit_code = self.services.fetch_submission_by_audit_code
        try:
            submission = await fetch_submission_by_audit_code(audit_code)
        except ValueError:
            return {"success": False, "error": "请求参数无效"}
        except self.environment.boundary_errors():
            self.environment.logger().exception("fetch intake by audit code failed")
            return {"success": False, "error": "获取表单失败，请稍后重试"}
        return {"success": True, "data": {"submission": submission}}

    async def user_cs_demand_form_redeem_code(self, body: DemandFormRedeemCodeBody) -> Payload:
        redeem_submission_by_audit_code = self.services.redeem_submission_by_audit_code
        try:
            doc = await redeem_submission_by_audit_code(
                int(body.market_user_id), body.audit_code, username=body.username
            )
        except ValueError:
            return {"success": False, "error": "请求参数无效"}
        except self.environment.boundary_errors():
            self.environment.logger().exception("redeem intake audit code failed")
            return {"success": False, "error": "校验审核码失败，请稍后重试"}
        return {"success": True, "data": {"pipeline": doc}}

    async def user_cs_demand_form_status(self, market_user_id: int, username: str = "") -> Payload:
        finalize_intake_submission = self.services.finalize_intake_submission
        sync_intake_from_market_if_newer = self.services.sync_intake_from_market_if_newer
        uid = int(market_user_id)
        doc = await sync_intake_from_market_if_newer(uid, username=username)
        if doc is None:
            load_pipeline = self.records.load_pipeline
            doc = load_pipeline(uid, username=username)
        elif doc.get("intake_submitted_at") and (not doc.get("crm_funnel_synced_at")):
            doc, _ = finalize_intake_submission(uid, doc, username=username, notify_wechat=False)
        return {"success": True, "data": {"pipeline": doc}}

    async def user_cs_demand_form_finalize(self, body: PipelineBody) -> Payload:
        finalize_intake_submission = self.services.finalize_intake_submission
        load_pipeline = self.records.load_pipeline
        uid = int(body.market_user_id)
        doc = load_pipeline(uid, username=body.username)
        if not doc.get("intake_submitted_at"):
            return {
                "success": False,
                "error": "尚未同步到需求提交记录，请先同步官网表单或校验审核码",
            }
        doc, meta = finalize_intake_submission(uid, doc, username=body.username, notify_wechat=True)
        return {"success": True, "data": {"pipeline": doc, "finalize": meta}}
