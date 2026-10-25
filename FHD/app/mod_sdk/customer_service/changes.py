"""Customer change requests, operations dispatch and notification receipts."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from .models import (
    ChangeRequestCreateBody,
    ChangeRequestNotifyBody,
    ChangeRequestStatusBody,
)
from .customer_service_ports import ChangesServices, Environment, Payload, PipelineRepository


@dataclass(frozen=True, eq=False)
class ChangesHandlers:
    services: ChangesServices
    records: PipelineRepository
    environment: Environment

    def user_cs_change_requests_list(self, market_user_id: int, username: str = "") -> Payload:
        list_change_requests = self.services.list_change_requests
        load_pipeline = self.records.load_pipeline
        uid = int(market_user_id)
        return {
            "success": True,
            "data": {
                "requests": list_change_requests(uid, username=username),
                "pipeline_stage": str(load_pipeline(uid, username=username).get("stage") or "idle"),
            },
        }

    def user_cs_change_requests_create(self, body: ChangeRequestCreateBody) -> Payload:
        create_change_request = self.services.create_change_request
        try:
            row = create_change_request(
                int(body.market_user_id),
                change_type=body.change_type,
                title=body.title,
                description=body.description,
                priority=body.priority,
                username=body.username,
                source=body.source,
            )
        except ValueError:
            return {"success": False, "error": "请求参数无效"}
        return {"success": True, "data": {"request": row}}

    def user_cs_change_requests_status(
        self, ticket_id: str, body: ChangeRequestStatusBody
    ) -> Payload:
        update_change_request_status = self.services.update_change_request_status
        try:
            row = update_change_request_status(
                int(body.market_user_id),
                ticket_id,
                status=body.status,
                admin_note=body.admin_note,
                username=body.username,
            )
        except ValueError:
            return {"success": False, "error": "请求参数无效"}
        return {"success": True, "data": {"request": row}}

    async def user_cs_change_requests_ops_dispatch(
        self, ticket_id: str, body: ChangeRequestNotifyBody, request: Request
    ) -> Payload:
        build_ops_dispatch_task_description = self.services.build_ops_dispatch_task_description
        list_change_requests = self.services.list_change_requests
        load_pipeline = self.records.load_pipeline
        mark_change_request_ops_dispatched = self.services.mark_change_request_ops_dispatched
        uid = int(body.market_user_id)
        rows = list_change_requests(uid, username=body.username)
        row = next((r for r in rows if str(r.get("id")) == str(ticket_id)), None)
        if not row:
            return {"success": False, "error": "未找到该变更工单"}
        if row.get("ops_dispatch_job_id"):
            return {
                "success": True,
                "data": {
                    "request": row,
                    "job_id": row.get("ops_dispatch_job_id"),
                    "already_dispatched": True,
                },
            }
        client = (body.contact_name or "").strip()
        if not client:
            doc = load_pipeline(uid, username=body.username)
            client = str(doc.get("erp_customer_name") or doc.get("username") or "").strip()
        task_description = build_ops_dispatch_task_description(
            row, market_user_id=uid, client_name=client
        )
        try:
            _authorization_from_request = self.services._authorization_from_request
            _proxy_json = self.services._proxy_json
        except self.environment.boundary_errors():
            self.environment.logger().exception("market agent unavailable")
            return {"success": False, "error": "市场代理暂时不可用"}
        authorization = _authorization_from_request(request, {})
        if not authorization:
            return {"success": False, "error": "尚未绑定修茈服务器账号，无法派发运维任务"}
        payload = {
            "task_description": task_description,
            "use_task_router": True,
            "dispatch_source": "cs_change_request",
        }
        raw = await _proxy_json(
            "POST",
            "/api/ops/orchestrate/async",
            json_body=payload,
            authorization=authorization,
            return_error_payload=True,
        )
        if isinstance(raw, dict) and raw.get("__proxy_error__"):
            err_msg = str(raw.get("payload") or "dispatch_failed")[:500]
            mark_change_request_ops_dispatched(
                uid, ticket_id, error=err_msg, username=body.username
            )
            return {"success": False, "error": err_msg}
        job_id = ""
        if isinstance(raw, dict):
            data = raw.get("data")
            inner = data if isinstance(data, dict) else raw
            job_id = str(inner.get("job_id") or inner.get("id") or raw.get("job_id") or "").strip()
        if not job_id:
            mark_change_request_ops_dispatched(
                uid, ticket_id, error="未返回 job_id", username=body.username
            )
            return {"success": False, "error": "运维派发未返回 job_id", "data": raw}
        updated = mark_change_request_ops_dispatched(
            uid, ticket_id, job_id=job_id, username=body.username
        )
        return {"success": True, "data": {"request": updated, "job_id": job_id, "dispatch": raw}}

    def user_cs_change_requests_notify_wechat(
        self, ticket_id: str, body: ChangeRequestNotifyBody
    ) -> Payload:
        _primary_contact_name = self.services._primary_contact_name
        build_change_request_wechat_message = self.services.build_change_request_wechat_message
        get_desktop_automation_service = self.services.get_desktop_automation_service
        list_change_requests = self.services.list_change_requests
        load_pipeline = self.records.load_pipeline
        mark_change_request_wechat_notified = self.services.mark_change_request_wechat_notified
        uid = int(body.market_user_id)
        rows = list_change_requests(uid, username=body.username)
        row = next((r for r in rows if str(r.get("id")) == str(ticket_id)), None)
        if not row:
            return {"success": False, "error": "未找到该变更工单"}
        contact = (body.contact_name or "").strip() or _primary_contact_name(uid) or ""
        if not contact:
            return {"success": False, "error": "未绑定微信群联系人"}
        doc = load_pipeline(uid, username=body.username)
        client = str(doc.get("username") or body.username or "")
        text = build_change_request_wechat_message(row, client_name=client)
        try:
            send_result = get_desktop_automation_service().send_wechat_message(contact, text)
        except self.environment.boundary_errors():
            self.environment.logger().exception("customer service send failed")
            return {"success": False, "error": "客服消息发送服务暂时不可用"}
        ok = bool(send_result.get("success")) and bool(
            send_result.get("message_sent", send_result.get("success"))
        )
        if ok:
            mark_change_request_wechat_notified(uid, ticket_id, username=body.username)
        return {
            "success": ok,
            "data": {"message": text, "send_result": send_result},
            "error": "" if ok else str(send_result.get("error") or "发送失败"),
        }
