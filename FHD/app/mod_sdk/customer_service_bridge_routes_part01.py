# mypy: disable-error-code="name-defined, union-attr"
"""FastAPI route registration phase extracted from the MOD facade."""

from __future__ import annotations


def _register_routes_part01(router, mod_id, facade):
    globals()["facade"] = facade

    @router.get("/status")
    def status():
        from app.mod_sdk.customer_service_pages_compat import list_customer_service_pages_registry

        return {
            "success": True,
            "data": {
                "ok": True,
                "mod_id": mod_id,
                "registry": list_customer_service_pages_registry(),
                "user_cs_employee_id": "user-customer-service-officer",
            },
        }

    @router.get("/user-cs/status")
    async def user_cs_status():
        return await facade._run_user_cs_employee({"action": "status"})

    @router.post("/user-cs/demand-intake")
    async def user_cs_demand_intake(body: facade.DemandIntakeBody):
        from app.mod_sdk.host_services import build_intake_form_url

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
        result = await facade._run_user_cs_employee(payload)
        from app.mod_sdk.host_services import (
            mark_demand_intake_sent,
            normalize_demand_intake_result,
        )

        (result, employee_ok) = normalize_demand_intake_result(
            result,
            signed_url=signed_url,
            fallback_url=body.form_url or "https://xiu-ci.com/contact.html",
        )
        if body.market_user_id and employee_ok:
            try:
                mark_demand_intake_sent(int(body.market_user_id))
            except facade.BOUNDARY_ERRORS:
                facade.logger.exception("pipeline update after demand intake failed")
        return result

    @router.get("/user-cs/clients")
    async def user_cs_list_clients():
        """已有商机 pipeline 档案的市场用户（供内部客服列表与「添加客户」合并）。"""
        from app.mod_sdk.host_services import list_pipeline_client_summaries

        return {"success": True, "data": {"clients": list_pipeline_client_summaries()}}

    @router.get("/user-cs/pipeline/funnel")
    async def user_cs_pipeline_funnel(max_clients_per_stage: int = 8):
        from app.mod_sdk.host_services import PIPELINE_STAGES, build_pipeline_funnel_summary

        data = build_pipeline_funnel_summary(max_clients_per_stage=max_clients_per_stage)
        return {"success": True, "data": {**data, "stage_definitions": PIPELINE_STAGES}}

    @router.post("/user-cs/pipeline/repair-crm")
    async def user_cs_pipeline_repair_crm(body: facade.PipelineBody):
        from app.mod_sdk.host_services import (
            CrmSyncError,
            PipelineCrmGateError,
            get_crm_bundle_for_market_user,
            repair_pipeline_crm,
        )

        try:
            doc = repair_pipeline_crm(int(body.market_user_id), username=body.username)
            uid = int(body.market_user_id)
            return {
                "success": True,
                "data": {"pipeline": doc, "crm": get_crm_bundle_for_market_user(uid)},
            }
        except (PipelineCrmGateError, CrmSyncError) as exc:
            return {"success": False, "error": str(exc), "crm_gate": True}
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

    @router.post("/user-cs/pipeline/repair-all")
    async def user_cs_pipeline_repair_all(body: facade.PipelineBody):
        from app.mod_sdk.host_services import repair_all_pipelines

        summary = repair_all_pipelines(username=body.username)
        return {"success": True, "data": summary}

    @router.get("/user-cs/enterprise-credentials")
    async def user_cs_get_enterprise_credentials(market_user_id: int, username: str = ""):
        from app.mod_sdk.host_services import get_enterprise_credentials

        data = get_enterprise_credentials(int(market_user_id), username=username)
        return {"success": True, "data": data}

    @router.post("/user-cs/enterprise-credentials/issue")
    async def user_cs_issue_enterprise_credentials(body: facade.EnterpriseCredentialsIssueBody):
        from app.mod_sdk.host_services import issue_enterprise_credentials

        pwd = (body.password or "").strip() or None
        result = issue_enterprise_credentials(
            int(body.market_user_id), username=body.username, password=pwd
        )
        if not result.get("ok"):
            return {"success": False, "error": result.get("error") or "issue_failed"}
        return {"success": True, "data": result}

    @router.get("/user-cs/pipeline")
    async def user_cs_get_pipeline(
        market_user_id: int, username: str = "", auto_advance: bool = False
    ):
        from app.mod_sdk.host_services import (
            PIPELINE_STAGES,
            auto_advance_pipeline_if_ready,
            load_pipeline,
        )

        uid = int(market_user_id)
        advanced = False
        if auto_advance:
            (doc, advanced) = auto_advance_pipeline_if_ready(uid, username=username)
        else:
            doc = load_pipeline(uid, username=username)
        from app.mod_sdk.host_services import get_crm_bundle_for_market_user

        return {
            "success": True,
            "data": {
                "pipeline": doc,
                "stages": PIPELINE_STAGES,
                "advanced": advanced,
                "crm": get_crm_bundle_for_market_user(uid),
            },
        }

    def _apply_pipeline_body(body: facade.PipelineBody):
        from app.mod_sdk.host_services import load_pipeline, save_pipeline, set_pipeline_stage

        uid = int(body.market_user_id)
        doc = load_pipeline(uid, username=body.username)
        if body.stage:
            try:
                doc = set_pipeline_stage(
                    uid,
                    body.stage,
                    username=body.username,
                    source="manual" if body.manual else "api",
                    note=body.note,
                )
            except ValueError as exc:
                return {"success": False, "error": str(exc)}
            except facade.BOUNDARY_ERRORS as exc:
                from app.mod_sdk.host_services import PipelineCrmGateError

                if isinstance(exc, PipelineCrmGateError):
                    return {"success": False, "error": str(exc), "code": "crm_gate"}
                from app.mod_sdk.host_services import CrmSyncError

                if isinstance(exc, CrmSyncError):
                    return {
                        "success": False,
                        "error": str(exc),
                        "code": "crm_sync",
                        "details": getattr(exc, "details", ""),
                    }
                raise
        if body.intake_sent:
            doc["intake_sent"] = True
            doc = save_pipeline(doc)
        return {"success": True, "data": {"pipeline": doc}}

    @router.put("/user-cs/pipeline")
    async def user_cs_put_pipeline(body: facade.PipelineBody):
        return _apply_pipeline_body(body)

    @router.post("/user-cs/pipeline/stage")
    async def user_cs_post_pipeline_stage(body: facade.PipelineBody):
        return _apply_pipeline_body(body)

    @router.post("/user-cs/demand-form/sync")
    async def user_cs_demand_form_sync(body: facade.DemandFormSyncBody, request: facade.Request):
        from app.mod_sdk.host_services import (
            apply_landing_submission_to_funnel,
            verify_webhook_secret,
        )

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

    @router.post("/user-cs/landing-funnel/sync")
    async def user_cs_landing_funnel_sync(
        body: facade.LandingFunnelSyncBody, request: facade.Request
    ):
        from app.mod_sdk.host_services import (
            apply_landing_submission_to_funnel,
            verify_webhook_secret,
        )

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

    @router.get("/user-cs/change-requests")
    def user_cs_change_requests_list(market_user_id: int, username: str = ""):
        from app.mod_sdk.host_services import list_change_requests, load_pipeline

        uid = int(market_user_id)
        return {
            "success": True,
            "data": {
                "requests": list_change_requests(uid, username=username),
                "pipeline_stage": str(load_pipeline(uid, username=username).get("stage") or "idle"),
            },
        }

    @router.post("/user-cs/change-requests")
    def user_cs_change_requests_create(body: facade.ChangeRequestCreateBody):
        from app.mod_sdk.host_services import create_change_request

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
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        return {"success": True, "data": {"request": row}}

    @router.put("/user-cs/change-requests/{ticket_id}/status")
    def user_cs_change_requests_status(ticket_id: str, body: facade.ChangeRequestStatusBody):
        from app.mod_sdk.host_services import update_change_request_status

        try:
            row = update_change_request_status(
                int(body.market_user_id),
                ticket_id,
                status=body.status,
                admin_note=body.admin_note,
                username=body.username,
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        return {"success": True, "data": {"request": row}}

    @router.post("/user-cs/change-requests/{ticket_id}/ops-dispatch")
    async def user_cs_change_requests_ops_dispatch(
        ticket_id: str, body: facade.ChangeRequestNotifyBody, request: facade.Request
    ):
        from app.mod_sdk.host_services import (
            build_ops_dispatch_task_description,
            list_change_requests,
            load_pipeline,
            mark_change_request_ops_dispatched,
        )

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
            from app.mod_sdk.host_services import _authorization_from_request, _proxy_json
        except facade.BOUNDARY_ERRORS as exc:
            return {"success": False, "error": f"市场代理不可用: {exc}"}
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
            inner = raw.get("data") if isinstance(raw.get("data"), dict) else raw
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

    @router.post("/user-cs/change-requests/{ticket_id}/notify-wechat")
    def user_cs_change_requests_notify_wechat(ticket_id: str, body: facade.ChangeRequestNotifyBody):
        from app.mod_sdk.host_services import (
            _primary_contact_name,
            build_change_request_wechat_message,
            get_desktop_automation_service,
            list_change_requests,
            load_pipeline,
            mark_change_request_wechat_notified,
        )

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
        except facade.BOUNDARY_ERRORS as exc:
            return {"success": False, "error": str(exc)[:300]}
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
