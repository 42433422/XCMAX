"""Planner 兼容对话服务（3d）：供宿主 /api/ai/* 与 Mod facade 共用。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from fastapi import HTTPException, Request

from app.application.agent_orchestrator.chat_trace import (
    attach_chat_trace_run,
    finalize_legacy_chat_run,
    start_legacy_chat_run,
)
from app.domain.ai.tier import (
    assert_p2_elevated_claim_or_raise,
    resolve_ai_tier,
    runtime_context_with_tier,
)
from app.domain.context.session_context import (
    planner_workflow_interrupt_reply,
    runtime_context_after_workflow_interrupt,
)
from app.fastapi_routes.xcagi_compat_chat_helpers import (
    XcagiCompatChatBatchBody,
    XcagiCompatChatBody,
    _ensure_chat_db_read_authorized,
    _ensure_vector_index_if_needed,
    _merge_runtime_context_with_message_paths,
    _message_requires_db_read_token,
    _xcagi_chat_http_exc,
    _xcagi_chat_timeout_error_payload,
    _xcagi_chat_timeout_seconds,
    _xcagi_compat_reply_payload,
    _xcagi_planner_stream_bytes_async,
)
from app.infrastructure.llm.client import set_mode as set_llm_mode
from app.legacy.chat.legacy_chat_adapter import chat as run_agent_chat
from app.services.conversation.modstore_adapter import create_modstore_openai_client_from_request
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _derive_industry_from_session(request: Request) -> str:
    """单一真相源 + 自动派生：从 session account_kind + User.industry_id 派生 industry。

    1. admin 账号 → "管理端"（运维助手身份）
    2. 普通账号 → User.industry_id（涂料/考勤/批发/电商/餐饮/物流等）
    3. 兜底 → "通用"（业务管家身份）

    前端/手机端无需传 industry，后端自动判断。
    """
    try:
        from app.application.session_account_meta import load_session_account_meta
        from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

        sid = _session_id_from_request(request)
        if not sid:
            return "通用"
        meta = load_session_account_meta(sid) or {}
        # 1. admin 账号 → 管理端
        if meta.get("account_kind") == "admin":
            return "管理端"
        # 2. 普通账号 → User.industry_id
        local_user_id = meta.get("local_user_id")
        if local_user_id:
            from app.db.models.user import User
            from app.db.session import get_db

            with get_db() as db:
                row = db.query(User.industry_id).filter(User.id == local_user_id).first()
                if row and row[0]:
                    return str(row[0]).strip()
    except Exception:  # noqa: BLE001  # best-effort 派生，失败回退到默认行业
        logger.debug("derive_industry_from_session failed", exc_info=True)
    return "通用"


def _attach_compat_chat_trace(
    payload: dict[str, Any],
    body: XcagiCompatChatBody | XcagiCompatChatBatchBody,
    *,
    message: str,
    runtime_context: dict[str, Any] | None,
    channel: str,
) -> dict[str, Any]:
    return attach_chat_trace_run(
        payload,
        message=message,
        runtime_context=runtime_context,
        user_id=getattr(body, "user_id", None),
        source=getattr(body, "source", None),
        channel=channel,
    )


def _legacy_requires_token_payload(parsed: dict[str, Any]) -> dict[str, Any]:
    raw_records = parsed.get("legacy_tool_records")
    legacy_tool_records = raw_records if isinstance(raw_records, list) else []
    data_payload = {
        "requires_token": True,
        "token_name": parsed.get("token_name"),
        "token_description": parsed.get("token_description"),
    }
    if legacy_tool_records:
        data_payload["legacy_tool_records"] = legacy_tool_records
    return {
        "success": True,
        "requires_token": True,
        "token_name": parsed.get("token_name"),
        "token_description": parsed.get("token_description"),
        "message": parsed.get("message"),
        "response": parsed.get("message"),
        "data": data_payload,
    }


def _reply_has_legacy_tool_records(reply: Any) -> bool:
    return isinstance(reply, dict) and isinstance(
        reply.get("legacy_tool_records") or reply.get("_tool_records"),
        list,
    )


def _clear_legacy_tool_result_if_reply_has_no_records(reply: Any) -> None:
    if _reply_has_legacy_tool_records(reply):
        return
    try:
        from app.legacy.chat.legacy_chat_adapter import clear_last_tool_result

        clear_last_tool_result()
    except RECOVERABLE_ERRORS:
        logger.debug("legacy planner local tool trace clear skipped", exc_info=True)


async def execute_compat_chat(request: Request, body: XcagiCompatChatBody) -> dict[str, Any]:
    m = (body.mode or "").strip().lower()
    if m in ("online", "offline"):
        set_llm_mode(m)

    runtime_context, _ = _merge_runtime_context_with_message_paths(body.context, body.message)
    assert_p2_elevated_claim_or_raise(request)
    tier = resolve_ai_tier(request)
    runtime_context = runtime_context_with_tier(runtime_context, tier)
    try:
        from app.application.kitten_planner_context import (
            enrich_kitten_analyzer_runtime,
            kitten_reply_attachments,
        )

        runtime_context = await enrich_kitten_analyzer_runtime(runtime_context, body.message)
        kitten_extra = kitten_reply_attachments(runtime_context)
    except RECOVERABLE_ERRORS:
        logger.debug("kitten planner context enrich skipped", exc_info=True)
        kitten_extra = {}
    ok_read, read_req = _ensure_chat_db_read_authorized(
        request,
        message=body.message,
        provided_token=body.db_read_token,
    )
    if not ok_read and read_req:
        payload = {
            "success": True,
            "requires_token": True,
            "token_name": read_req.get("token_name"),
            "token_description": read_req.get("token_description"),
            "message": read_req.get("message"),
            "response": read_req.get("message"),
            "data": {
                "requires_token": True,
                "token_name": read_req.get("token_name"),
                "token_description": read_req.get("token_description"),
            },
        }
        return _attach_compat_chat_trace(
            payload,
            body,
            message=body.message,
            runtime_context=runtime_context,
            channel="compat_chat",
        )
    if ok_read and _message_requires_db_read_token(body.message):
        runtime_context["chat_db_read_authorized"] = True
    intr = planner_workflow_interrupt_reply(body.message)
    if intr is not None:
        cleared = runtime_context_after_workflow_interrupt(runtime_context)
        payload = _xcagi_compat_reply_payload(
            intr, runtime_context_update=cleared, kitten_attachments=kitten_extra or None
        )
        return _attach_compat_chat_trace(
            payload,
            body,
            message=body.message,
            runtime_context=cleared,
            channel="compat_chat",
        )

    vector_error = _ensure_vector_index_if_needed(body.message, runtime_context)
    if vector_error:
        payload = _xcagi_compat_reply_payload(vector_error, kitten_attachments=kitten_extra or None)
        return _attach_compat_chat_trace(
            payload,
            body,
            message=body.message,
            runtime_context=runtime_context,
            channel="compat_chat",
        )

    timeout = _xcagi_chat_timeout_seconds()
    pre_run = None
    planner_runtime_context = dict(runtime_context or {})
    try:
        workspace_root = os.environ.get("WORKSPACE_ROOT", os.getcwd())
        llm_client = create_modstore_openai_client_from_request(request)
        try:
            pre_run = start_legacy_chat_run(
                message=body.message,
                runtime_context=planner_runtime_context,
                user_id=getattr(body, "user_id", None),
                source=getattr(body, "source", None),
                channel="compat_chat",
            )
            planner_runtime_context["run_id"] = pre_run.run_id
            planner_runtime_context["agent_run_id"] = pre_run.run_id
        except RECOVERABLE_ERRORS:
            logger.debug("legacy planner AgentRun pre-create skipped", exc_info=True)
        reply = await asyncio.wait_for(
            asyncio.to_thread(
                run_agent_chat,
                body.message,
                runtime_context=planner_runtime_context or None,
                system_prompt=body.system_prompt,
                workspace_root=workspace_root,
                db_write_token=body.db_write_token,
                client=llm_client,
            ),
            timeout=timeout,
        )
        try:
            parsed = reply if isinstance(reply, dict) else None
            if parsed is None and isinstance(reply, str):
                parsed = json.loads(reply)
            if isinstance(parsed, dict) and parsed.get("requires_token"):
                payload = _legacy_requires_token_payload(parsed)
                if pre_run is not None:
                    return finalize_legacy_chat_run(
                        pre_run.run_id,
                        payload,
                        message=body.message,
                        runtime_context=planner_runtime_context,
                        user_id=getattr(body, "user_id", None),
                        source=getattr(body, "source", None),
                        channel="compat_chat",
                    )
                return _attach_compat_chat_trace(
                    payload,
                    body,
                    message=body.message,
                    runtime_context=planner_runtime_context,
                    channel="compat_chat",
                )
        except json.JSONDecodeError:
            pass
        _clear_legacy_tool_result_if_reply_has_no_records(reply)
    except TimeoutError:
        payload = _xcagi_chat_timeout_error_payload(timeout)
        if pre_run is not None:
            return finalize_legacy_chat_run(
                pre_run.run_id,
                payload,
                message=body.message,
                runtime_context=planner_runtime_context,
                user_id=getattr(body, "user_id", None),
                source=getattr(body, "source", None),
                channel="compat_chat",
            )
        return _attach_compat_chat_trace(
            payload,
            body,
            message=body.message,
            runtime_context=planner_runtime_context,
            channel="compat_chat",
        )
    except RECOVERABLE_ERRORS as e:
        if pre_run is not None:
            err_payload = {
                "success": False,
                "message": str(e),
                "response": str(e),
                "data": {"error": str(e)},
            }
            finalize_legacy_chat_run(
                pre_run.run_id,
                err_payload,
                message=body.message,
                runtime_context=planner_runtime_context,
                user_id=getattr(body, "user_id", None),
                source=getattr(body, "source", None),
                channel="compat_chat",
            )
        raise _xcagi_chat_http_exc(e) from e
    payload = _xcagi_compat_reply_payload(reply, kitten_attachments=kitten_extra or None)
    if pre_run is not None:
        return finalize_legacy_chat_run(
            pre_run.run_id,
            payload,
            message=body.message,
            runtime_context=planner_runtime_context,
            user_id=getattr(body, "user_id", None),
            source=getattr(body, "source", None),
            channel="compat_chat",
        )
    return _attach_compat_chat_trace(
        payload,
        body,
        message=body.message,
        runtime_context=planner_runtime_context,
        channel="compat_chat",
    )


async def execute_compat_chat_batch(
    request: Request, body: XcagiCompatChatBatchBody
) -> dict[str, Any]:
    msgs = [str(x).strip() for x in (body.messages or []) if str(x).strip()]
    if not msgs:
        raise HTTPException(status_code=400, detail="messages 须为非空字符串数组")
    assert_p2_elevated_claim_or_raise(request)
    batch_tier = resolve_ai_tier(request)
    m = (body.mode or "").strip().lower()
    if m in ("online", "offline"):
        set_llm_mode(m)
    results: list[dict[str, Any]] = []
    timeout = _xcagi_chat_timeout_seconds()
    rolling_ctx = body.context
    llm_client = create_modstore_openai_client_from_request(request)
    for txt in msgs:
        runtime_context, _ = _merge_runtime_context_with_message_paths(rolling_ctx, txt)
        runtime_context = runtime_context_with_tier(runtime_context, batch_tier)
        ok_read, read_req = _ensure_chat_db_read_authorized(
            request,
            message=txt,
            provided_token=body.db_read_token,
        )
        if not ok_read and read_req:
            payload = {
                "success": True,
                "requires_token": True,
                "token_name": read_req.get("token_name"),
                "token_description": read_req.get("token_description"),
                "message": read_req.get("message"),
                "response": read_req.get("message"),
                "data": {
                    "requires_token": True,
                    "token_name": read_req.get("token_name"),
                    "token_description": read_req.get("token_description"),
                },
            }
            results.append(
                _attach_compat_chat_trace(
                    payload,
                    body,
                    message=txt,
                    runtime_context=runtime_context,
                    channel="compat_chat_batch",
                )
            )
            continue
        if ok_read and _message_requires_db_read_token(txt):
            runtime_context["chat_db_read_authorized"] = True
        intr = planner_workflow_interrupt_reply(txt)
        if intr is not None:
            cleared = runtime_context_after_workflow_interrupt(runtime_context)
            rolling_ctx = cleared
            payload = _xcagi_compat_reply_payload(intr, runtime_context_update=cleared)
            results.append(
                _attach_compat_chat_trace(
                    payload,
                    body,
                    message=txt,
                    runtime_context=cleared,
                    channel="compat_chat_batch",
                )
            )
            continue
        vector_error = _ensure_vector_index_if_needed(txt, runtime_context)
        if vector_error:
            payload = _xcagi_compat_reply_payload(vector_error)
            results.append(
                _attach_compat_chat_trace(
                    payload,
                    body,
                    message=txt,
                    runtime_context=runtime_context,
                    channel="compat_chat_batch",
                )
            )
            continue
        pre_run = None
        planner_runtime_context = dict(runtime_context or {})
        try:
            try:
                pre_run = start_legacy_chat_run(
                    message=txt,
                    runtime_context=planner_runtime_context,
                    user_id=getattr(body, "user_id", None),
                    source=getattr(body, "source", None),
                    channel="compat_chat_batch",
                )
                planner_runtime_context["run_id"] = pre_run.run_id
                planner_runtime_context["agent_run_id"] = pre_run.run_id
            except RECOVERABLE_ERRORS:
                logger.debug("legacy batch planner AgentRun pre-create skipped", exc_info=True)
            workspace_root = os.environ.get("WORKSPACE_ROOT", os.getcwd())
            reply = await asyncio.wait_for(
                asyncio.to_thread(
                    run_agent_chat,
                    txt,
                    runtime_context=planner_runtime_context or None,
                    system_prompt=body.system_prompt,
                    workspace_root=workspace_root,
                    db_write_token=body.db_write_token,
                    client=llm_client,
                ),
                timeout=timeout,
            )
            try:
                parsed = reply if isinstance(reply, dict) else None
                if parsed is None and isinstance(reply, str):
                    parsed = json.loads(reply)
                if isinstance(parsed, dict) and parsed.get("requires_token"):
                    payload = _legacy_requires_token_payload(parsed)
                    if pre_run is not None:
                        results.append(
                            finalize_legacy_chat_run(
                                pre_run.run_id,
                                payload,
                                message=txt,
                                runtime_context=planner_runtime_context,
                                user_id=getattr(body, "user_id", None),
                                source=getattr(body, "source", None),
                                channel="compat_chat_batch",
                            )
                        )
                    else:
                        results.append(
                            _attach_compat_chat_trace(
                                payload,
                                body,
                                message=txt,
                                runtime_context=planner_runtime_context,
                                channel="compat_chat_batch",
                            )
                        )
                    continue
            except json.JSONDecodeError:
                pass
            _clear_legacy_tool_result_if_reply_has_no_records(reply)
            payload = _xcagi_compat_reply_payload(reply)
            if pre_run is not None:
                results.append(
                    finalize_legacy_chat_run(
                        pre_run.run_id,
                        payload,
                        message=txt,
                        runtime_context=planner_runtime_context,
                        user_id=getattr(body, "user_id", None),
                        source=getattr(body, "source", None),
                        channel="compat_chat_batch",
                    )
                )
            else:
                results.append(
                    _attach_compat_chat_trace(
                        payload,
                        body,
                        message=txt,
                        runtime_context=planner_runtime_context,
                        channel="compat_chat_batch",
                    )
                )
        except TimeoutError:
            payload = _xcagi_chat_timeout_error_payload(timeout)
            if pre_run is not None:
                results.append(
                    finalize_legacy_chat_run(
                        pre_run.run_id,
                        payload,
                        message=txt,
                        runtime_context=planner_runtime_context,
                        user_id=getattr(body, "user_id", None),
                        source=getattr(body, "source", None),
                        channel="compat_chat_batch",
                    )
                )
            else:
                results.append(
                    _attach_compat_chat_trace(
                        payload,
                        body,
                        message=txt,
                        runtime_context=planner_runtime_context,
                        channel="compat_chat_batch",
                    )
                )
        except RECOVERABLE_ERRORS as e:
            err = _xcagi_chat_http_exc(e)
            payload = {
                "success": False,
                "message": err.detail if isinstance(err.detail, str) else str(err.detail),
            }
            if pre_run is not None:
                results.append(
                    finalize_legacy_chat_run(
                        pre_run.run_id,
                        payload,
                        message=txt,
                        runtime_context=planner_runtime_context,
                        user_id=getattr(body, "user_id", None),
                        source=getattr(body, "source", None),
                        channel="compat_chat_batch",
                    )
                )
            else:
                results.append(
                    _attach_compat_chat_trace(
                        payload,
                        body,
                        message=txt,
                        runtime_context=planner_runtime_context,
                        channel="compat_chat_batch",
                    )
                )
    ok = all(r.get("success") for r in results)
    return {"success": ok, "batch": True, "results": results, "count": len(results)}


def _recent_history(svc, user_id: str) -> list[dict]:
    """从对话服务里尽力读取该用户最近历史（供 persona L2/L3 周期推断使用）。

    取不到则返回空列表（容错，绝不因此中断流式响应）。
    """
    try:
        contexts = getattr(svc, "contexts", None)
        if not contexts:
            return []
        ctx = contexts.get(user_id)
        hist = getattr(ctx, "conversation_history", None) if ctx else None
        return list(hist) if hist else []
    except Exception:  # noqa: BLE001
        return []


def _resolve_chat_user_id(request: Request, body: XcagiCompatChatBody) -> str:
    """统一对话流 user_id 口径，与 butler 路由 (_resolve_user_id_int) 对齐：
    优先 body.user_id，其次 X-User-Id 头，最后默认 '1'（与 butler 默认 1 同源），
    使单部署单用户时对话流与 Settings UI 天然指向同一画像（桥接合并 / 目标 5）。
    """
    uid = getattr(body, "user_id", None)
    if uid:
        return str(uid)
    try:
        hdr = request.headers.get("X-User-Id") or request.headers.get("X-User-ID")
        if hdr and str(hdr).strip():
            return str(hdr).strip()
    except Exception:  # noqa: BLE001
        pass
    return "1"


async def compat_chat_stream_async(
    request: Request, body: XcagiCompatChatBody, *, ai_tier: str | None = None
):
    # 注入 persona system_prompt（前端没传时用 persona 系统生成去客服腔 prompt）
    if not body.system_prompt and body.message:
        try:
            from app.services.conversation.manager import get_ai_conversation_service

            svc = get_ai_conversation_service()
            persona_svc = getattr(svc, "persona_service", None)
            logger.info(
                "persona_inject check: has_persona=%s msg=%s",
                persona_svc is not None,
                body.message[:50],
            )
            if persona_svc is not None:
                user_id = _resolve_chat_user_id(request, body)
                ctx = body.context or {}
                # 单一真相源 + 自动派生：优先用前端传的 industry；
                # 没传则从 session account_kind 派生（admin → 管理端，其他 → 通用）
                industry = ctx.get("industry") if isinstance(ctx, dict) else None
                if not industry:
                    industry = _derive_industry_from_session(request)
                history = _recent_history(svc, user_id)
                logger.info(
                    "persona_inject ctx=%s industry=%s history_len=%d",
                    ctx,
                    industry,
                    len(history),
                )
                prompt, _params = await persona_svc.build_prompt_from_message(
                    user_id=user_id,
                    message=body.message,
                    history=history,
                    industry=industry,
                    context_prompt="",
                )
                body.system_prompt = prompt
                logger.info("persona_inject OK: prompt_len=%d", len(prompt))
        except Exception as e:  # noqa: BLE001  # persona 注入为尽力而为，失败不应中断流式响应
            logger.warning("persona_inject FAIL: %s", e, exc_info=True)

    tier = ai_tier or resolve_ai_tier(request)
    async for chunk in _xcagi_planner_stream_bytes_async(request, body, ai_tier=tier):
        yield chunk
