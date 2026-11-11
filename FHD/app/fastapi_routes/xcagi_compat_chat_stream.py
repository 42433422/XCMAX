"""Streaming LangGraph chat implementation for the XCAGI compatibility endpoint."""

from __future__ import annotations

import asyncio
import contextvars
import importlib
import os
import threading
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any

from fastapi import Request

if TYPE_CHECKING:
    from app.fastapi_routes.xcagi_compat_chat_helpers import XcagiCompatChatBody


def _facade():
    return importlib.import_module("app.fastapi_routes.xcagi_compat_chat_helpers")


def _client_issue_reply(receipt: dict | None) -> str:
    if not receipt:
        return ""
    if "issue_description" in (receipt.get("missing_evidence") or []):
        return "你要登记哪个软件功能或使用反馈？请说说想改的内容或遇到的情况，我会据此受理，不用固定格式。"
    shots = receipt.get("screenshots") or {}
    attachment = "本次诊断附件保存尚未确认，请在原工单继续补报。"
    if receipt.get("support_bundle_saved") is True and receipt.get("support_bundle_sha256"):
        attachment = f"支持包 SHA256：{receipt['support_bundle_sha256']}。"
        if shots:
            attachment += f"支持包已附截图 {shots.get('included')}/{shots.get('selected')} 张。"
    replies: dict[str, str] = {
        "RECEIVED": f"产品问题已受理，市场工单：{receipt.get('owner_ticket_no')}。请在原工单补充期望、实际及诊断证据，供后续复现核验。",
        "ROUTED": f"产品问题已登记，Work Order：{receipt.get('work_order_id')}，市场工单：{receipt.get('owner_ticket_no')}。{attachment}",
        "NEEDS_MORE_EVIDENCE": (
            "这看起来是产品缺陷上报，但还缺少必要信息，暂未自动建单。"
            "请用自己的话补充期望和实际表现，不用固定格式。"
            "（若只是使用咨询，请再发一次，我会直接回答。）"
        ),
        "OWNER_ROUTE_UNAVAILABLE": "暂时无法确认受理结果。请先查看客服工单列表，避免重复提交；登录失效时请重新登录。",
        "not_confirmed": "目前无法以足够把握确认是产品缺陷，因此没有自动建单。",
    }
    return replies.get(str(receipt.get("state") or ""), "")


def _apply_client_issue_outcome(payload: dict, receipt: dict | None) -> dict:
    if receipt and receipt.get("state") == "OWNER_ROUTE_UNAVAILABLE":
        payload.update(success=False, message=_client_issue_reply(receipt))
    return payload


async def _classify_and_submit_client_issue_async(
    request,
    runtime_context,
    message,
    reply,
    client=None,
    *,
    guide_unavailable: bool = True,
):
    """客户缺陷上报 → 工单受理（async 版，供 async 生成器直接 await）。

    与同步变体共用同一套判定与回执文案：只有明确判为使用咨询才回落正常对话；
    分类不可用时保留补证引导；明确建单无需模型或固定字段格式。
    """
    from app.application import client_product_issue_intake as intake

    message = intake.report_message_with_context(message, runtime_context)
    if not intake.looks_like_issue_report(message):
        return None

    def _unavailable():
        return {"state": "NEEDS_MORE_EVIDENCE"} if guide_unavailable else None

    triage = intake.classify_explicit_report(message)
    if triage is None:
        if client is None:
            try:
                client = _facade().create_modstore_openai_client_from_request(request)
            except _facade().BOUNDARY_ERRORS:
                _facade().logger.warning("client issue classifier unavailable", exc_info=True)
                return _unavailable()
        try:
            from app.infrastructure.llm.model_admission import model_rate_limit_scope

            with model_rate_limit_scope(runtime_context):
                triage = await asyncio.to_thread(intake.classify_report, client, message, reply)
        except _facade().BOUNDARY_ERRORS:
            # 分类器是外部 LLM 边界：任何意外异常都必须退化成「引导补齐证据」，
            # 既不能让缺陷被静默吃掉，也不能把对话打成 500。
            _facade().logger.warning("client issue classification raised", exc_info=True)
            return _unavailable()
    if triage is None:
        return _unavailable()
    if str(triage.get("type") or "") == "usage_question":
        return None
    if str(triage.get("type") or "") != "product_defect":
        return _unavailable()
    if "issue_description" in (triage.get("missing_evidence") or []):
        return {
            "state": "NEEDS_MORE_EVIDENCE",
            "missing_evidence": ["issue_description"],
        }
    try:
        return await intake.submit_product_issue(
            request=request,
            tenant_id=runtime_context.get("tenant_id"),
            customer_message=message,
            triage=triage,
            attachments=runtime_context.get("multimodal_attachments"),
        )
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.warning("client product issue intake failed", exc_info=True)
        return {"state": "OWNER_ROUTE_UNAVAILABLE"}


def _classify_and_submit_client_issue(
    request,
    runtime_context,
    message,
    reply,
    client=None,
    *,
    guide_unavailable: bool = True,
):
    """同步变体：供同步生成器（运行在后台线程）调用。实现见 async 版。"""
    return asyncio.run(
        _classify_and_submit_client_issue_async(
            request,
            runtime_context,
            message,
            reply,
            client,
            guide_unavailable=guide_unavailable,
        )
    )


def _is_workflow_control(message: str) -> bool:
    from app.application.ai_chat.workflow_session import CANCEL_WORDS, CONFIRM_WORDS

    text = str(message or "").strip().lower().rstrip("。.!！")
    return text in CONFIRM_WORDS or text in CANCEL_WORDS


def _tool_heartbeat_seconds() -> float:
    raw = os.environ.get("XCAGI_CHAT_STREAM_TOOL_HEARTBEAT_SEC", "8").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 8.0
    return max(0.2, min(value, 30.0))


def _progress(encode: Callable[[dict[str, Any]], bytes], phase: str, label: str) -> bytes:
    return encode({"type": "tool_progress", "phase": phase, "label": label, "text": label})


def _heartbeats(
    fn: Callable[[], Any],
    label: str,
    sink: dict[str, Any],
    encode: Callable[[dict[str, Any]], bytes],
) -> Iterator[bytes]:
    """Run blocking local work off the producer and keep the stream observably alive."""
    box: dict = {}

    def run() -> None:
        from app.utils.operational_errors import BOUNDARY_ERRORS

        try:
            box["value"] = fn()
        except BOUNDARY_ERRORS as exc:
            box["error"] = exc

    thread = threading.Thread(target=contextvars.copy_context().run, args=(run,), daemon=True)
    thread.start()
    interval = _tool_heartbeat_seconds()
    while thread.is_alive():
        thread.join(interval)
        if thread.is_alive():
            yield _progress(encode, "running", label)
    if "error" in box:
        raise box["error"]
    sink["value"] = box.get("value")


def _xcagi_planner_stream_bytes(request: Request, body: XcagiCompatChatBody, *, ai_tier: str):
    """Execute every online stream through the LangGraph-backed chat service."""
    from app.application.planner_compat.offline import is_offline

    facade = _facade()
    encode = facade._sse_event_line
    control = _is_workflow_control(str(body.message or ""))
    if is_offline(body.mode):
        from app.application.planner_compat_service import execute_compat_chat

        # The sync producer runs in its owned worker. Reuse JSON admission,
        # authorization, local handlers and receipts rather than a second lane.
        # Yield before that work: the first-event watch is 20s and would cancel
        # a confirmed rebuild that has not yet produced a byte.
        label = "正在执行已确认的任务" if control else "正在处理本地任务"
        yield _progress(encode, "running", label)
        sink: dict = {}
        yield from _heartbeats(
            lambda: asyncio.run(execute_compat_chat(request, body)),
            label,
            sink,
            encode,
        )
        payload = sink["value"]
        yield encode({"type": "token", "text": payload["response"]})
        yield encode({"type": "done", "result": payload})
        return
    from app.application import get_ai_chat_app_service
    from app.application.agent_task_context import scoped_conversation_user_id
    from app.application.planner_compat.runtime import resolve_file_context
    from app.fastapi_routes.xcagi_compat_chat_helpers import (
        create_modstore_openai_client_from_request,
    )
    from app.infrastructure.llm.client import llm_client_factory_scope
    from app.infrastructure.tenant_scope import tenant_scope

    sse_event_line = encode
    if control:
        yield _progress(encode, "running", "正在执行已确认的任务")
    else:
        yield _progress(encode, "started", "正在处理任务")
    runtime_context, _ = facade._merge_runtime_context_with_message_paths(
        body.context, body.message
    )
    runtime_context = facade._runtime_context_with_authenticated_actor(request, runtime_context)
    runtime_context = facade.runtime_context_with_tier(runtime_context, ai_tier)
    from app.application.ai_chat.chat_evidence import prepare_chat_evidence

    runtime_context = prepare_chat_evidence(request, runtime_context, str(body.message or ""))
    runtime_context.setdefault(
        "conversation_id",
        runtime_context.get("session_id")
        or str(body.user_id or runtime_context.get("local_user_id") or "default"),
    )
    runtime_context.pop("_chat_evidence_prepared_marker", None)
    runtime_context["message"] = str(body.message or "")
    body.context = runtime_context
    scoped_user_id = scoped_conversation_user_id(str(body.user_id or "default"), runtime_context)

    allowed, required = facade._ensure_chat_db_read_authorized(
        request, message=body.message, provided_token=body.db_read_token
    )
    if not allowed and required:
        payload = facade._token_required_payload(dict(required))
        payload = facade.attach_chat_trace_run(
            payload,
            message=body.message,
            runtime_context=runtime_context,
            user_id=body.user_id,
            source=body.source,
            channel="compat_chat_stream_authorization",
        )
        yield sse_event_line({"type": "token", "text": str(payload.get("response") or "需要授权")})
        yield sse_event_line({"type": "requires_token", **payload})
        return
    if allowed and facade._message_requires_db_read_token(body.message):
        runtime_context["chat_db_read_authorized"] = True

    interrupt = facade.planner_workflow_interrupt_reply(body.message)
    if interrupt is not None:
        cleared = facade.runtime_context_after_workflow_interrupt(runtime_context)
        payload = facade._xcagi_compat_reply_payload(interrupt, runtime_context_update=cleared)
        payload = facade.attach_chat_trace_run(
            payload,
            message=body.message,
            runtime_context=cleared,
            user_id=body.user_id,
            source=body.source,
            channel="compat_chat_stream_interrupt",
        )
        yield sse_event_line({"type": "token", "text": interrupt})
        yield sse_event_line({"type": "done", "result": payload})
        return

    if error := facade._ensure_vector_index_if_needed(body.message, runtime_context):
        yield sse_event_line({"type": "error", "message": error})
        return
    service = get_ai_chat_app_service()
    tenant_id = runtime_context.get("tenant_id")
    tenant_id = int(tenant_id) if tenant_id is not None else None
    try:
        def _chat():
            with (
                tenant_scope(tenant_id),
                llm_client_factory_scope(lambda: create_modstore_openai_client_from_request(request)),
            ):
                return service.process_chat(
                    user_id=scoped_user_id,
                    message=str(body.message or ""),
                    context=runtime_context,
                    source=body.source,
                    file_context=resolve_file_context(runtime_context),
                )

        if control:
            sink = {}
            yield from _heartbeats(_chat, "正在执行已确认的任务", sink, encode)
            payload = sink["value"]
        else:
            payload = _chat()
    except facade.RECOVERABLE_ERRORS as exc:
        from app.infrastructure.chat_stream_lifetime import current_lifetime

        lifetime = current_lifetime.get()
        if lifetime is not None and lifetime.run_snapshot is not None:
            raise
        error = facade._xcagi_chat_http_exc(exc)
        message = error.detail if isinstance(error.detail, str) else str(error.detail)
        yield sse_event_line(
            {"type": "error", "message": message, "status_code": error.status_code}
        )
        return

    if not isinstance(payload, dict):
        payload = facade._xcagi_compat_reply_payload(str(payload))
    if not payload.get("run_id") and not payload.get("agent_run_id"):
        payload = facade.attach_chat_trace_run(
            payload,
            message=body.message,
            runtime_context=runtime_context,
            user_id=body.user_id,
            source=body.source,
            channel="compat_chat_stream_langgraph",
        )
    response_text = str(payload.get("response") or payload.get("message") or "")
    if response_text:
        yield sse_event_line({"type": "token", "text": response_text})
    yield sse_event_line({"type": "done", "result": payload})
