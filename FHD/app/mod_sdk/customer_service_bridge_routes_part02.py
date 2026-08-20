# mypy: disable-error-code="name-defined"
"""FastAPI route registration phase extracted from the MOD facade."""

from __future__ import annotations


def _register_routes_part02(router, mod_id, facade):
    globals()["facade"] = facade

    @router.get("/user-cs/demand-form/link")
    def user_cs_demand_form_link(market_user_id: int, client_name: str = "", brief: str = ""):
        from app.mod_sdk.host_services import build_intake_form_url

        url = build_intake_form_url(int(market_user_id), brief=brief, client_name=client_name)
        return {"success": True, "data": {"form_url": url}}

    @router.get("/user-cs/demand-form/notice-message")
    def user_cs_demand_form_notice_message(
        market_user_id: int, client_name: str = "", brief: str = ""
    ):
        from app.mod_sdk.host_services import (
            build_intake_form_notice_message,
            build_intake_form_url,
        )

        uid = int(market_user_id)
        url = build_intake_form_url(uid, brief=brief, client_name=client_name)
        text = build_intake_form_notice_message(form_url=url, client_name=client_name, brief=brief)
        return {"success": True, "data": {"form_url": url, "message": text}}

    @router.post("/user-cs/demand-form/manual")
    async def user_cs_demand_form_manual(body: facade.DemandFormManualBody):
        from datetime import datetime

        from app.mod_sdk.host_services import apply_landing_submission_to_pipeline

        doc = apply_landing_submission_to_pipeline(
            int(body.market_user_id),
            {
                "name": body.name.strip(),
                "email": body.email.strip(),
                "phone": body.phone.strip(),
                "company": body.company.strip(),
                "message": body.message.strip(),
                "desktop_os": body.desktop_os.strip(),
                "need_mobile": body.need_mobile,
                "submitted_at": datetime.now(facade.UTC).isoformat(),
                "intake_source": "manual_card",
            },
            username=body.username,
        )
        return {"success": True, "data": {"pipeline": doc}}

    @router.get("/user-cs/demand-form/by-audit-code")
    async def user_cs_demand_form_by_audit_code(audit_code: str, market_user_id: int | None = None):
        from app.mod_sdk.host_services import fetch_submission_by_audit_code

        try:
            submission = await fetch_submission_by_audit_code(
                audit_code, market_user_id=int(market_user_id) if market_user_id else None
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        except facade.BOUNDARY_ERRORS:
            facade.logger.exception("fetch intake by audit code failed")
            return {"success": False, "error": "获取表单失败，请稍后重试"}
        return {"success": True, "data": {"submission": submission}}

    @router.post("/user-cs/demand-form/redeem-code")
    async def user_cs_demand_form_redeem_code(body: facade.DemandFormRedeemCodeBody):
        from app.mod_sdk.host_services import redeem_submission_by_audit_code

        try:
            doc = await redeem_submission_by_audit_code(
                int(body.market_user_id), body.audit_code, username=body.username
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        except facade.BOUNDARY_ERRORS:
            facade.logger.exception("redeem intake audit code failed")
            return {"success": False, "error": "校验审核码失败，请稍后重试"}
        return {"success": True, "data": {"pipeline": doc}}

    @router.get("/user-cs/demand-form/status")
    async def user_cs_demand_form_status(market_user_id: int, username: str = ""):
        from app.mod_sdk.host_services import (
            finalize_intake_submission,
            sync_intake_from_market_if_newer,
        )

        uid = int(market_user_id)
        doc = await sync_intake_from_market_if_newer(uid, username=username)
        if doc is None:
            from app.mod_sdk.host_services import load_pipeline

            doc = load_pipeline(uid, username=username)
        elif doc.get("intake_submitted_at") and (not doc.get("crm_funnel_synced_at")):
            (doc, _) = finalize_intake_submission(uid, doc, username=username, notify_wechat=False)
        return {"success": True, "data": {"pipeline": doc}}

    @router.post("/user-cs/demand-form/finalize")
    async def user_cs_demand_form_finalize(body: facade.PipelineBody):
        from app.mod_sdk.host_services import finalize_intake_submission, load_pipeline

        uid = int(body.market_user_id)
        doc = load_pipeline(uid, username=body.username)
        if not doc.get("intake_submitted_at"):
            return {
                "success": False,
                "error": "尚未同步到需求提交记录，请先同步官网表单或校验审核码",
            }
        (doc, meta) = finalize_intake_submission(
            uid, doc, username=body.username, notify_wechat=True
        )
        return {"success": True, "data": {"pipeline": doc, "finalize": meta}}

    @router.get("/user-cs/crm")
    def user_cs_crm_bundle(market_user_id: int):
        from app.mod_sdk.host_services import get_crm_bundle_for_market_user

        return {"success": True, "data": get_crm_bundle_for_market_user(int(market_user_id))}

    @router.post("/user-cs/crm/sync")
    async def user_cs_crm_sync(body: facade.PipelineBody):
        from app.mod_sdk.host_services import (
            get_crm_bundle_for_market_user,
            load_pipeline,
            save_pipeline,
            sync_crm_from_pipeline_doc,
        )

        uid = int(body.market_user_id)
        doc = load_pipeline(uid, username=body.username)
        doc = sync_crm_from_pipeline_doc(doc)
        doc = save_pipeline(doc)
        return {
            "success": True,
            "data": {"pipeline": doc, "crm": get_crm_bundle_for_market_user(uid)},
        }

    @router.post("/user-cs/crm/push-external")
    async def user_cs_crm_push_external(body: facade.PipelineBody):
        from app.mod_sdk.host_services import CrmSyncError, push_external_crm_for_market_user

        try:
            out = push_external_crm_for_market_user(
                int(body.market_user_id), username=body.username
            )
            return {"success": True, "data": out}
        except CrmSyncError as exc:
            return {"success": False, "error": str(exc)}
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

    @router.post("/user-cs/crm/pull-external")
    async def user_cs_crm_pull_external(body: facade.PipelineBody):
        from app.mod_sdk.host_services import CrmSyncError, pull_external_crm_for_market_user

        try:
            out = pull_external_crm_for_market_user(
                int(body.market_user_id), username=body.username
            )
            pull = out.get("pull") if isinstance(out, dict) else {}
            if isinstance(pull, dict) and (not pull.get("ok")) and (not pull.get("skipped")):
                return {"success": False, "error": pull.get("error") or "pull_failed", "data": out}
            return {"success": True, "data": out}
        except CrmSyncError as exc:
            return {"success": False, "error": str(exc)}
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

    @router.get("/user-cs/delivery")
    def user_cs_delivery_get(market_user_id: int, username: str = ""):
        from app.mod_sdk.host_services import ensure_delivery_on_doc, load_pipeline

        doc = ensure_delivery_on_doc(load_pipeline(int(market_user_id), username=username))
        return {
            "success": True,
            "data": {
                "delivery": doc.get("delivery"),
                "payment": doc.get("payment"),
                "invoice": doc.get("invoice"),
            },
        }

    @router.put("/user-cs/delivery/plan")
    def user_cs_delivery_save_plan(body: facade.DeliveryPlanBody):
        from app.mod_sdk.host_services import (
            ensure_delivery_on_doc,
            load_pipeline,
            save_pipeline,
            set_pipeline_stage,
            update_delivery_plan,
        )

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
            try:
                doc = set_pipeline_stage(
                    uid,
                    target_stage,
                    username=body.username,
                    source="delivery_plan",
                    note="delivery_plan_saved",
                )
            except ValueError as exc:
                return {"success": False, "error": str(exc)}
        else:
            doc = save_pipeline(doc)
        return {"success": True, "data": {"pipeline": doc}}

    @router.post("/user-cs/delivery/signoff/request")
    def user_cs_delivery_signoff_request(body: facade.PipelineBody):
        from app.mod_sdk.host_services import create_signoff_request

        try:
            out = create_signoff_request(
                int(body.market_user_id),
                username=body.username,
                signed_by=body.note or "",
                notes=body.note or "",
            )
            return {"success": True, "data": out}
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

    @router.post("/user-cs/delivery/signoff/confirm")
    def user_cs_delivery_signoff_confirm(body: facade.PipelineBody):
        from app.mod_sdk.host_services import confirm_signoff

        sid = int(getattr(body, "signoff_id", 0) or 0)
        if sid <= 0:
            return {"success": False, "error": "signoff_id required"}
        try:
            out = confirm_signoff(
                sid, market_user_id=int(body.market_user_id), username=body.username
            )
            return {"success": True, "data": out}
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

    @router.post("/user-cs/delivery/notify-progress")
    def user_cs_delivery_notify_progress(body: facade.PipelineBody):
        from app.mod_sdk.host_services import (
            _primary_contact_name,
            build_delivery_progress_message,
            ensure_delivery_on_doc,
            get_desktop_automation_service,
            load_pipeline,
            save_pipeline,
        )

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
        except facade.BOUNDARY_ERRORS as exc:
            return {"success": False, "error": str(exc)[:300]}
        ok = bool(send_result.get("success")) and bool(
            send_result.get("message_sent", send_result.get("success"))
        )
        if ok:
            delivery = dict(doc.get("delivery") or {})
            delivery["last_progress_notice_at"] = facade.datetime.now(facade.UTC).isoformat()
            doc["delivery"] = delivery
            doc = save_pipeline(doc)
        return {
            "success": ok,
            "data": {"message": text, "send_result": send_result},
            "error": "" if ok else str(send_result.get("error") or "发送失败"),
        }

    @router.post("/user-cs/delivery/notify-software")
    def user_cs_delivery_notify_software(body: facade.PipelineBody):
        from app.mod_sdk.host_services import notify_software_delivery

        force = bool(getattr(body, "force", False))
        out = notify_software_delivery(
            int(body.market_user_id), username=body.username, force=force
        )
        if not out.get("ok"):
            return {"success": False, "error": out.get("error") or "发送失败", "data": out}
        return {"success": True, "data": out}

    @router.post("/user-cs/delivery/check-payment")
    def user_cs_delivery_check_payment(body: facade.DeliveryPaymentBody):
        from app.mod_sdk.host_services import (
            build_starred_group_feed,
            ensure_delivery_on_doc,
            load_pipeline,
            save_pipeline,
            try_confirm_payment_and_invoice,
        )

        uid = int(body.market_user_id)
        doc = ensure_delivery_on_doc(load_pipeline(uid, username=body.username))
        feed = build_starred_group_feed(limit=40, market_user_id=uid)
        texts = [
            str(x.get("content") or x.get("message") or "")
            for x in feed
            if x.get("content") or x.get("message")
        ]
        outcome = try_confirm_payment_and_invoice(
            uid,
            doc,
            message_texts=texts,
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

    @router.post("/user-cs/pipeline/auto-advance")
    async def user_cs_auto_advance_pipeline(body: facade.PipelineBody):
        from app.mod_sdk.host_services import auto_advance_pipeline_if_ready

        (doc, advanced) = auto_advance_pipeline_if_ready(
            int(body.market_user_id), username=body.username
        )
        return {"success": True, "data": {"pipeline": doc, "advanced": advanced}}
