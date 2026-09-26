"""Streaming planner implementation for the XCAGI compatibility endpoint."""

from __future__ import annotations

import asyncio
import importlib
from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from app.fastapi_routes.xcagi_compat_chat_helpers import XcagiCompatChatBody


def _facade():
    return importlib.import_module("app.fastapi_routes.xcagi_compat_chat_helpers")


def _client_issue_reply(receipt: dict | None) -> str:
    if not receipt:
        return ""
    state = str(receipt.get("state") or "")
    if state == "ROUTED":
        return f"已向 Owner 提交产品问题，Work Order：{receipt['work_order_id']}，市场工单：{receipt['owner_ticket_no']}。支持包 SHA256：{receipt['support_bundle_sha256']}。"
    if state == "NEEDS_MORE_EVIDENCE":
        return f"采证未完成（缺少：{'、'.join(receipt.get('missing_evidence') or [])}）；暂未创建工单。"
    if state == "OWNER_ROUTE_UNAVAILABLE":
        return f"Owner 候选 Work Order {receipt.get('work_order_id') or '受理服务'}尚未送达。"
    if state == "not_confirmed":
        return "目前无法以足够把握确认是产品缺陷，因此没有自动建单。"
    return ""


def _classify_and_submit_client_issue(request, client, runtime_context, message, reply):
    from app.application.client_product_issue_intake import (
        classify_report,
        looks_like_issue_report,
        submit_product_issue,
    )

    if not looks_like_issue_report(message):
        return None
    triage = classify_report(client, message, reply)
    if not triage or triage.get("type") != "product_defect":
        return None
    try:
        return asyncio.run(
            submit_product_issue(
                request=request,
                client=client,
                tenant_id=runtime_context.get("tenant_id"),
                customer_message=message,
                assistant_reply=reply,
                triage=triage,
            )
        )
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.warning("client product issue intake failed", exc_info=True)
        return {"state": "OWNER_ROUTE_UNAVAILABLE"}


def _xcagi_planner_stream_bytes(request: Request, body: XcagiCompatChatBody, *, ai_tier: str):
    m = (body.mode or "").strip().lower()
    if m in ("online", "offline"):
        _facade().set_llm_mode(m)
    (runtime_context, _) = _facade()._merge_runtime_context_with_message_paths(
        body.context, body.message
    )
    runtime_context = _facade()._runtime_context_with_authenticated_actor(request, runtime_context)
    runtime_context = _facade().runtime_context_with_tier(runtime_context, ai_tier)
    from app.application import get_ai_chat_app_service
    from app.application.normal_chat_dispatch import route_normal_mode_message
    from app.application.workflow.planner import _looks_like_business_db_write

    chat_service = get_ai_chat_app_service()
    scoped_user_id = str(body.user_id or "default")
    has_pending_workflow = scoped_user_id in chat_service._pending_workflows
    _sales_route = route_normal_mode_message(str(body.message or ""))
    sales_closed_loop_route = (
        str(_sales_route.get("intent") or "") == "sales_write"
        and str(_sales_route.get("action") or "") == "execute_closed_loop"
        and isinstance(_sales_route.get("payload"), dict)
        and bool(_sales_route.get("payload"))
    )
    controlled_entity_named = any(
        token in str(body.message or "")
        for token in ("客户", "购买单位", "产品", "商品", "原材料", "物料", "出货", "发货")
    )
    from app.infrastructure.tenant_scope import tenant_scope

    authenticated_tenant_id = runtime_context.get("tenant_id")
    authenticated_tenant_id = (
        int(authenticated_tenant_id) if authenticated_tenant_id is not None else None
    )
    if (
        has_pending_workflow
        or sales_closed_loop_route
        or (
            controlled_entity_named
            and _looks_like_business_db_write(
                str(body.message or ""), str(body.message or "").lower()
            )
        )
    ):
        with tenant_scope(authenticated_tenant_id):
            payload = chat_service.process_chat(
                user_id=scoped_user_id,
                message=body.message,
                context=runtime_context,
                source=body.source,
                file_context={},
            )
        response_text = str(payload.get("response") or payload.get("message") or "")
        yield _facade()._sse_event_line({"type": "token", "text": response_text})
        yield _facade()._sse_event_line({"type": "done", "result": payload})
        return
    from app.application.chat_business_safety import try_handle_business_chat_action

    business_payload = try_handle_business_chat_action(
        body.message, runtime_context=runtime_context, user_id=body.user_id, request=request
    )
    if business_payload is not None:
        response_text = str(
            business_payload.get("response") or business_payload.get("message") or ""
        )
        yield _facade()._sse_event_line({"type": "token", "text": response_text})
        yield _facade()._sse_event_line({"type": "done", "result": business_payload})
        return
    (ok_read, read_req) = _facade()._ensure_chat_db_read_authorized(
        request, message=body.message, provided_token=body.db_read_token
    )
    if not ok_read and read_req:
        yield _facade()._sse_event_line(
            {"type": "token", "text": f"[需要授权: {read_req.get('token_description')}]"}
        )
        yield _facade()._sse_event_line(
            {
                "type": "requires_token",
                "token_name": read_req.get("token_name"),
                "token_description": read_req.get("token_description"),
            }
        )
        return
    if ok_read and _facade()._message_requires_db_read_token(body.message):
        runtime_context["chat_db_read_authorized"] = True
    intr = _facade().planner_workflow_interrupt_reply(body.message)
    if intr is not None:
        cleared = _facade().runtime_context_after_workflow_interrupt(runtime_context)
        yield _facade()._sse_event_line({"type": "token", "text": intr})
        payload = _facade()._xcagi_compat_reply_payload(intr, runtime_context_update=cleared)
        payload = _facade().attach_chat_trace_run(
            payload,
            message=body.message,
            runtime_context=cleared,
            user_id=body.user_id,
            source=body.source,
            channel="compat_chat_stream",
        )
        yield _facade()._sse_event_line({"type": "done", "result": payload})
        return
    vector_error = _facade()._ensure_vector_index_if_needed(body.message, runtime_context)
    if vector_error:
        yield _facade()._sse_event_line({"type": "error", "message": vector_error})
        return
    workspace_root = _facade().os.environ.get("WORKSPACE_ROOT", _facade().os.getcwd())
    llm_client = _facade().create_modstore_openai_client_from_request(request)
    receipt = _classify_and_submit_client_issue(
        request, llm_client, runtime_context, body.message, ""
    )
    issue_reply = _client_issue_reply(receipt)
    if issue_reply:
        payload = _facade()._xcagi_compat_reply_payload(issue_reply)
        payload = _facade().attach_chat_trace_run(
            payload,
            message=body.message,
            runtime_context=runtime_context,
            user_id=body.user_id,
            source=body.source,
            channel="compat_chat_stream",
        )
        yield _facade()._sse_event_line({"type": "token", "text": issue_reply})
        yield _facade()._sse_event_line({"type": "done", "result": payload})
        return
    reply_parts: list[str] = []
    pre_run = None
    planner_runtime_context = dict(runtime_context or {})
    try:
        pre_run = _facade().start_legacy_chat_run(
            message=body.message,
            runtime_context=planner_runtime_context,
            user_id=body.user_id,
            source=body.source,
            channel="compat_chat_stream",
        )
        planner_runtime_context["run_id"] = pre_run.run_id
        planner_runtime_context["agent_run_id"] = pre_run.run_id
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.debug("legacy stream planner AgentRun pre-create skipped", exc_info=True)
    try:
        halted_for_write_token = False
        for ev in _facade()._xcagi_guarded_planner_stream_events(
            body,
            runtime_context=planner_runtime_context,
            workspace_root=workspace_root,
            client=llm_client,
        ):
            et = ev.get("type")
            if et == "error":
                if pre_run is not None:
                    payload = {
                        "success": False,
                        "message": str(ev.get("message") or "流式 planner 执行失败"),
                        "response": str(ev.get("message") or "流式 planner 执行失败"),
                        "data": {
                            "error": str(ev.get("message") or "流式 planner 执行失败"),
                            "status_code": ev.get("status_code"),
                        },
                    }
                    _facade().finalize_legacy_chat_run(
                        pre_run.run_id,
                        payload,
                        message=body.message,
                        runtime_context=planner_runtime_context,
                        user_id=body.user_id,
                        source=body.source,
                        channel="compat_chat_stream",
                    )
                yield _facade()._sse_event_line(
                    _facade()._sse_payload_with_run_id(ev, getattr(pre_run, "run_id", None))
                )
                return
            if et == "token":
                text = str(ev.get("text") or "")
                if not ev.get("ephemeral"):
                    reply_parts.append(text)
                yield _facade()._sse_event_line(ev)
            elif et == "requires_token":
                if pre_run is not None:
                    payload = {
                        "success": True,
                        "requires_token": True,
                        "token_name": ev.get("token_name"),
                        "token_description": ev.get("token_description"),
                        "message": ev.get("message"),
                        "response": ev.get("message"),
                        "data": {
                            "requires_token": True,
                            "token_name": ev.get("token_name"),
                            "token_description": ev.get("token_description"),
                        },
                    }
                    _facade().finalize_legacy_chat_run(
                        pre_run.run_id,
                        payload,
                        message=body.message,
                        runtime_context=planner_runtime_context,
                        user_id=body.user_id,
                        source=body.source,
                        channel="compat_chat_stream",
                    )
                yield _facade()._sse_event_line(
                    _facade()._sse_payload_with_run_id(ev, getattr(pre_run, "run_id", None))
                )
                halted_for_write_token = True
                break
            elif et == "done":
                continue
            else:
                yield _facade()._sse_event_line(ev)
        if halted_for_write_token:
            return
        merged = _facade().sanitize_model_chat_reply("".join(reply_parts))
        if not merged.strip():
            msg = "模型服务已完成请求，但没有返回可显示的正文。若附带图片，请确认当前账号已启用视觉模型，或上传文字更清晰的截图。"
            if pre_run is not None:
                payload = {
                    "success": False,
                    "message": msg,
                    "response": msg,
                    "data": {"error": msg},
                }
                _facade().finalize_legacy_chat_run(
                    pre_run.run_id,
                    payload,
                    message=body.message,
                    runtime_context=planner_runtime_context,
                    user_id=body.user_id,
                    source=body.source,
                    channel="compat_chat_stream",
                )
            yield _facade()._sse_event_line(
                _facade()._sse_payload_with_run_id(
                    {"type": "error", "message": msg}, getattr(pre_run, "run_id", None)
                )
            )
            return
        # 终态回复必须使用**清洗后**的正文：merged 仍含 planner 内部标记
        # （如 `[正在调用工具: execute_erp_capability]`），直接作为 response 会让
        # 内部标记进入用户可见正文，并被 business_result.summary 原样带出。
        from app.application.planner_display_markers import strip_planner_stream_markers

        visible_text, marker_lines = strip_planner_stream_markers(merged)
        issue_receipt = _classify_and_submit_client_issue(
            request, llm_client, runtime_context, body.message, visible_text
        )
        issue_reply = _client_issue_reply(issue_receipt)
        if issue_reply:
            visible_text += f"\n\n{issue_reply}"
        thinking = _facade()._thinking_steps_from_planner_stream_text(merged)
        if not thinking:
            thinking = marker_lines
        if thinking:
            done_reply: str | dict = {"response": visible_text, "thinking_steps": thinking}
        else:
            done_reply = visible_text
        payload = _facade()._xcagi_compat_reply_payload(done_reply)
        if pre_run is not None:
            payload = _facade().finalize_legacy_chat_run(
                pre_run.run_id,
                payload,
                message=body.message,
                runtime_context=planner_runtime_context,
                user_id=body.user_id,
                source=body.source,
                channel="compat_chat_stream",
            )
        else:
            payload = _facade().attach_chat_trace_run(
                payload,
                message=body.message,
                runtime_context=runtime_context,
                user_id=body.user_id,
                source=body.source,
                channel="compat_chat_stream",
            )
        yield _facade()._sse_event_line({"type": "done", "result": payload})
    except _facade().RECOVERABLE_ERRORS as e:
        exc = _facade()._xcagi_chat_http_exc(e)
        message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        if pre_run is not None:
            payload = {
                "success": False,
                "message": message,
                "response": message,
                "data": {"error": message, "status_code": exc.status_code},
            }
            _facade().finalize_legacy_chat_run(
                pre_run.run_id,
                payload,
                message=body.message,
                runtime_context=planner_runtime_context,
                user_id=body.user_id,
                source=body.source,
                channel="compat_chat_stream",
            )
        yield _facade()._sse_event_line(
            _facade()._sse_payload_with_run_id(
                {"type": "error", "message": message, "status_code": exc.status_code},
                getattr(pre_run, "run_id", None),
            )
        )
