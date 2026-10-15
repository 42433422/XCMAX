# mypy: disable-error-code="name-defined"
"""FastAPI route registration phase extracted from the MOD facade."""

from __future__ import annotations


def _register_routes_part03(router, mod_id, facade):
    globals()["facade"] = facade

    @router.post("/user-cs/analyze")
    async def user_cs_analyze(body: facade.AnalyzePipelineBody):
        from app.mod_sdk.host_services import (
            PIPELINE_STAGES,
            analyze_customer_pipeline,
        )

        uid = int(body.market_user_id)
        doc = analyze_customer_pipeline(
            uid,
            username=body.username,
            message_texts=[],
            has_binding=body.has_binding,
            intake_sent=body.intake_sent,
        )
        connected_welcome = None
        if str(doc.get("stage")) == "connected" and body.has_binding:
            from app.mod_sdk.host_services import maybe_send_connected_welcome

            connected_welcome = maybe_send_connected_welcome(uid, username=body.username)
            if connected_welcome.get("sent"):
                from app.mod_sdk.host_services import load_pipeline

                doc = load_pipeline(uid, username=body.username)
        return {
            "success": True,
            "data": {
                "pipeline": doc,
                "stages": PIPELINE_STAGES,
                "message_count": 0,
                "connected_welcome": connected_welcome,
            },
        }

    @router.get("/user-cs/contract/schema")
    def user_cs_contract_schema():
        from app.mod_sdk.host_services import list_field_schema

        return {"success": True, "data": list_field_schema()}

    @router.get("/user-cs/contract/fields")
    def user_cs_contract_fields(market_user_id: int, username: str = ""):
        from app.mod_sdk.host_services import build_merged_fields, load_field_overrides

        uid = int(market_user_id)
        return {
            "success": True,
            "data": {
                "values": build_merged_fields(uid, username=username),
                "overrides": load_field_overrides(uid),
            },
        }

    @router.put("/user-cs/contract/fields")
    def user_cs_contract_save_fields(body: facade.ContractFieldsBody):
        from app.mod_sdk.host_services import (
            apply_contract_snapshot_to_doc,
            build_merged_fields,
            load_pipeline,
            save_field_overrides,
            save_pipeline,
        )

        uid = int(body.market_user_id)
        save_field_overrides(uid, body.values, username=body.username)
        doc = apply_contract_snapshot_to_doc(
            load_pipeline(uid, username=body.username), body.values
        )
        save_pipeline(doc)
        return {"success": True, "data": build_merged_fields(uid, username=body.username)}

    @router.post("/user-cs/contract/generate")
    async def user_cs_contract_generate(body: facade.ContractGenerateBody):
        from app.mod_sdk.host_services import (
            build_contract_wechat_hint,
            generate_contract_docx,
            load_pipeline,
            save_pipeline,
        )

        uid = int(body.market_user_id)
        result = generate_contract_docx(uid, username=body.username, field_values=body.values)
        hint = build_contract_wechat_hint(
            result.get("party_a_name") or body.username, result.get("filename") or ""
        )
        if body.advance_stage:
            try:
                doc = load_pipeline(uid, username=body.username)
                doc["stage"] = "contract_pending"
                now = facade.datetime.now(facade.UTC).isoformat()
                tl = list(doc.get("timeline") or [])
                tl.append({"stage": "contract_pending", "at": now, "source": "contract_generate"})
                doc["timeline"] = tl[-30:]
                doc["contract_filename"] = result.get("filename")
                save_pipeline(doc)
            except facade.BOUNDARY_ERRORS:
                facade.logger.exception("pipeline update after contract generate failed")
        return {
            "success": True,
            "data": {
                **result,
                "download_url": f"/api/mod/{mod_id}/user-cs/contract/download/{result.get('filename')}",
                "wechat_hint": hint,
            },
        }

    @router.get("/user-cs/contract/download/{filename}")
    def user_cs_contract_download(filename: str):
        from fastapi.responses import FileResponse

        from app.mod_sdk.host_services import generated_contracts_dir

        safe = facade.os.path.basename(filename)
        path = generated_contracts_dir() / safe
        if not path.is_file():
            return {"success": False, "error": "文件不存在"}
        return FileResponse(
            path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=safe,
        )

    @router.get("/user-cs/contract/sample-pdf")
    def user_cs_contract_sample_pdf():
        from fastapi.responses import FileResponse

        from app.mod_sdk.host_services import contract_assets_dir

        path = contract_assets_dir() / "sample_party_b_prefilled.pdf"
        if not path.is_file():
            return {"success": False, "error": "样例 PDF 不存在"}
        return FileResponse(path, media_type="application/pdf", filename="乙方预填样例.pdf")

    @router.post("/user-cs/wechat/send")
    async def user_cs_wechat_send(body: facade.WechatSendBody):
        from app.mod_sdk.host_services import get_desktop_automation_service

        uid = int(body.market_user_id)
        contact = body.contact_name.strip()
        if not contact:
            return {"success": False, "error": "请确认群名称"}
        svc = get_desktop_automation_service()
        result = svc.send_wechat_message(contact, body.message.strip())
        sent = bool(result.get("success")) and bool(
            result.get("message_sent", result.get("success"))
        )
        if sent:
            try:
                from app.mod_sdk.host_services import load_pipeline, save_pipeline

                doc = load_pipeline(uid, username=body.username)
                if doc.get("stage") in ("idle", "connected"):
                    doc["stage"] = "connected"
                    save_pipeline(doc)
            except facade.BOUNDARY_ERRORS:
                facade.logger.exception("pipeline update after wechat send failed")
        return {"success": sent, "data": result}

    @router.post("/user-cs/wechat/send-connected-welcome")
    async def user_cs_send_connected_welcome(body: facade.ConnectedWelcomeBody):
        from app.mod_sdk.host_services import (
            load_pipeline,
            maybe_send_connected_welcome,
            save_pipeline,
        )

        uid = int(body.market_user_id)
        doc = load_pipeline(uid, username=body.username)
        if str(doc.get("stage") or "idle") == "idle":
            doc["stage"] = "connected"
            save_pipeline(doc)
        out = maybe_send_connected_welcome(
            uid, username=body.username, contact_name=body.contact_name.strip(), force=body.force
        )
        return {"success": bool(out.get("sent")), "data": out}

    @router.post("/user-cs/wechat/send-intake-notice")
    async def user_cs_send_intake_notice(body: facade.IntakeNoticeBody):
        from app.mod_sdk.host_services import (
            load_pipeline,
            maybe_send_intake_form_notice,
            save_pipeline,
        )

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
