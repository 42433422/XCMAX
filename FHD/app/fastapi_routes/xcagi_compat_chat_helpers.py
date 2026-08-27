"""
XCAGI 前端兼容 API — AI 聊天辅助函数与数据模型。

供 xcagi_compat_chat / xcagi_compat_misc 等模块复用。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import queue
import re
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import Request

from app.application.agent_orchestrator.chat_trace import (
    attach_chat_trace_run as attach_chat_trace_run,
)
from app.application.agent_orchestrator.chat_trace import (
    finalize_legacy_chat_run as finalize_legacy_chat_run,
)
from app.application.agent_orchestrator.chat_trace import (
    start_legacy_chat_run as start_legacy_chat_run,
)
from app.application.chat_reply_safety import (
    sanitize_model_chat_reply as sanitize_model_chat_reply,
)
from app.application.modstore_conversation_app import (
    create_modstore_openai_client_from_request as create_modstore_openai_client_from_request,
)
from app.application.stream_status_events import MODEL_STREAM_ACCEPTED_EVENT
from app.application.tutorial_v2.scope import validated_tutorial_tenant_id
from app.domain.ai.tier import runtime_context_with_tier as runtime_context_with_tier
from app.domain.context.session_context import (
    planner_workflow_interrupt_reply as planner_workflow_interrupt_reply,
)
from app.domain.context.session_context import (
    runtime_context_after_workflow_interrupt as runtime_context_after_workflow_interrupt,
)
from app.infrastructure.auth.db_token import effective_db_read_token
from app.infrastructure.llm.client import set_mode as set_llm_mode  # noqa: F401
from app.legacy.chat.legacy_chat_adapter import chat_stream_sse_events
from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
_CHAT_DB_READ_GRACE_SEC = 5 * 60
_chat_db_read_grace_lock = threading.Lock()
_chat_db_read_grace_until: dict[str, float] = {}
_CHAT_DB_READ_ACTION_RE = re.compile(r"(查看|查询|检索|读取|看|浏览|导出)", re.IGNORECASE)
_CHAT_RAW_DB_SUBJECT_RE = re.compile(
    r"(数据库|数据表|表结构|schema|sql|SQL|raw|原始|全库|整库|数据库文件)",
    re.IGNORECASE,
)
_CHAT_CONTROLLED_BUSINESS_DB_RE = re.compile(
    r"(产品库|客户库|客户信息|购买单位|物料库|原材料|发货记录|出货记录|业务库)",
    re.IGNORECASE,
)
_CHAT_RAW_DB_STRONG_RE = re.compile(
    r"(原始|raw|SQL|sql|表结构|schema|全库|整库|数据表|数据库文件|导出数据库|备份数据库)",
    re.IGNORECASE,
)
_CHAT_DB_READ_INTENT_RE = re.compile(
    r"(查看|查询|检索|读取|看|浏览|导出).*(数据库|数据表|表结构|schema|sql|SQL|raw|原始|全库|整库|数据库文件|产品库|客户库|物料库|业务库)",
    re.IGNORECASE,
)


def _chat_request_subject(request: Request) -> str:
    xff = str(request.headers.get("x-forwarded-for") or "").strip()
    ip = xff.split(",")[0].strip() if xff else ""
    if not ip:
        client = getattr(request, "client", None)
        ip = str(getattr(client, "host", "") or "").strip()
    if not ip:
        ip = "unknown"
    ua = str(request.headers.get("user-agent") or "").strip()
    ua_fingerprint = hashlib.sha1(ua.encode("utf-8")).hexdigest()[:12] if ua else "na"
    return f"{ip}|{ua_fingerprint}"


def _chat_db_read_grace_seconds_left(request: Request) -> int:
    now = time.time()
    subject = _chat_request_subject(request)
    with _chat_db_read_grace_lock:
        until = float(_chat_db_read_grace_until.get(subject) or 0.0)
        if until <= now:
            _chat_db_read_grace_until.pop(subject, None)
            return 0
        return int(until - now)


def _touch_chat_db_read_grace(request: Request) -> int:
    now = time.time()
    subject = _chat_request_subject(request)
    until = now + _CHAT_DB_READ_GRACE_SEC
    with _chat_db_read_grace_lock:
        _chat_db_read_grace_until[subject] = until
    return _CHAT_DB_READ_GRACE_SEC


def _message_requires_db_read_token(message: str) -> bool:
    text = str(message or "").strip()
    if not text:
        return False
    # Controlled business reads (产品库/客户库/物料库等) are normal assistant
    # capabilities and must not be blocked by the raw database token gate.
    if _CHAT_CONTROLLED_BUSINESS_DB_RE.search(text) and not _CHAT_RAW_DB_STRONG_RE.search(text):
        return False
    if not _CHAT_DB_READ_ACTION_RE.search(text):
        return False
    return bool(_CHAT_RAW_DB_SUBJECT_RE.search(text))


def _runtime_context_with_authenticated_actor(
    request: Request,
    runtime_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Attach the local session actor and authenticated tenant.
    Never trust chat body.user_id for approvals, and never trust any tenant_id
    supplied by the request body/context: the tenant is derived only from the
    authenticated session (``resolve_tenant_id``) so the resolved tenant wins.
    """
    context = dict(runtime_context or {})
    # Remove caller-supplied tenant before session resolution so a missing or
    # failed resolver cannot accidentally preserve a spoofed tenant id.
    context.pop("tenant_id", None)
    try:
        from app.infrastructure.auth.dependencies import resolve_session_user

        user = resolve_session_user(request)
        actor_id = int(getattr(user, "id", 0) or 0)
        if actor_id > 0:
            context["local_user_id"] = actor_id
            context["actor_id"] = actor_id
    except RECOVERABLE_ERRORS:
        logger.debug("chat session actor resolution skipped", exc_info=True)
    if (tutorial_tenant := validated_tutorial_tenant_id(request)) is not None:
        return {**context, "tenant_id": int(tutorial_tenant)}
    try:
        from app.infrastructure.auth.tenant_context import resolve_tenant_id

        resolved_tenant = resolve_tenant_id(request)
        if resolved_tenant is not None:
            context["tenant_id"] = int(resolved_tenant)
    except RECOVERABLE_ERRORS:
        logger.debug("chat session tenant resolution skipped", exc_info=True)
    return context


def _runtime_context_with_trusted_dataset_access(
    request: Request,
    runtime_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Strip client dataset claims and inject the server-verified Persy scope."""
    from app.fastapi_routes.dataset_access import inject_trusted_dataset_access

    return inject_trusted_dataset_access(runtime_context, request)


def _chat_read_token_required_payload(message: str) -> dict[str, Any]:
    _ = message
    return {
        "requires_token": True,
        "token_name": "DB_READ_TOKEN",
        "token_description": "一级数据库查看令牌（授权后 5 分钟内可复用）",
        "message": "该操作需要一级数据库查看令牌。请先完成一级令牌验证后重试。",
    }


def _ensure_chat_db_read_authorized(
    request: Request,
    *,
    message: str,
    provided_token: str | None,
) -> tuple[bool, dict[str, Any] | None]:
    expected = effective_db_read_token()
    if not expected:
        return True, None
    if not _message_requires_db_read_token(message):
        return True, None
    if _chat_db_read_grace_seconds_left(request) > 0:
        return True, None
    got = str(provided_token or "").strip()
    if got and got == expected:
        _touch_chat_db_read_grace(request)
        return True, None
    return False, _chat_read_token_required_payload(message)


from app.fastapi_routes.xcagi_compat_chat_models import (
    XcagiCompatChatBatchBody as XcagiCompatChatBatchBody,
)
from app.fastapi_routes.xcagi_compat_chat_models import (
    XcagiCompatChatBody as XcagiCompatChatBody,
)
from app.fastapi_routes.xcagi_compat_chat_models import (
    _market_connection_label as _market_connection_label,
)
from app.fastapi_routes.xcagi_compat_chat_models import (
    _xcagi_chat_http_exc as _xcagi_chat_http_exc,
)
from app.fastapi_routes.xcagi_compat_chat_models import (
    _xcagi_compat_reply_payload as _xcagi_compat_reply_payload,
)

_EXCEL_PATH_PATTERN = re.compile(
    r"@?([^\s'\"<>]+?\.(?:xlsx|xlsm|xls))(?=$|[\s,，。.!！?？])",
    re.IGNORECASE,
)


def _extract_excel_paths_from_message(message: str) -> list[str]:
    paths: list[str] = []
    for m in _EXCEL_PATH_PATTERN.finditer(message or ""):
        p = m.group(1).strip().strip("`\"'[](){}<>")
        if not p:
            continue
        p = p.replace("\\", "/")
        if p not in paths:
            paths.append(p)
    return paths


def _extract_excel_paths_from_context(runtime_context: dict) -> list[str]:
    paths: list[str] = []

    def _push(raw: object) -> None:
        s = str(raw or "").strip().replace("\\", "/")
        if not s:
            return
        if not re.search(r"\.(xlsx|xlsm|xls)$", s, re.IGNORECASE):
            return
        if s not in paths:
            paths.append(s)

    existing_single = runtime_context.get("excel_file_path")
    if isinstance(existing_single, str):
        _push(existing_single)
    existing_multi = runtime_context.get("excel_file_paths")
    if isinstance(existing_multi, (list, tuple)):
        for p in existing_multi:
            _push(p)
    excel_analysis = runtime_context.get("excel_analysis")
    if isinstance(excel_analysis, dict):
        _push(excel_analysis.get("file_path"))
        preview = excel_analysis.get("preview_data")
        if isinstance(preview, dict):
            _push(preview.get("file_path"))
    return paths


def _merge_runtime_context_with_message_paths(
    runtime_context: dict | None,
    message: str,
) -> tuple[dict, list[str]]:
    merged_ctx = dict(runtime_context or {})
    found = _extract_excel_paths_from_message(message)
    ctx_paths = _extract_excel_paths_from_context(merged_ctx)
    if not found and not ctx_paths:
        return merged_ctx, []
    all_paths: list[str] = []
    message_basenames = {Path(p).name.lower(): p for p in found}
    for cp in ctx_paths:
        base = Path(cp).name.lower()
        if base in message_basenames and cp not in all_paths:
            all_paths.append(cp)
    for p in found:
        if p not in all_paths:
            all_paths.append(p)
    for cp in ctx_paths:
        if cp not in all_paths:
            all_paths.append(cp)
    if all_paths:
        merged_ctx["excel_file_path"] = all_paths[0]
        merged_ctx["excel_file_paths"] = all_paths
    return merged_ctx, found


def _looks_like_vector_request(message: str) -> bool:
    text = (message or "").lower()
    keywords = ("向量", "索引", "语义检索", "embedding", "vector", "semantic search")
    return any(k in text for k in keywords)


def _ensure_vector_index_if_needed(message: str, runtime_context: dict) -> str | None:
    if not _looks_like_vector_request(message):
        return None
    file_path = str(runtime_context.get("excel_file_path") or "").strip()
    if not file_path:
        return "我识别到您在请求向量索引，但没有拿到 Excel 路径。请发送类似 `@424/26年出货单打印/鸿瑞达报价26年.xlsx` 的路径。"
    root = os.environ.get("WORKSPACE_ROOT", os.getcwd())
    try:
        from app.mod_sdk.planner_tools import resolve_planner_tool_executor

        raw = resolve_planner_tool_executor()(
            "excel_vector_index",
            {"file_path": file_path},
            workspace_root=root,
        )
        result = json.loads(raw)
    except RECOVERABLE_ERRORS as e:
        logger.exception("xcagi vector pre-index failed")
        return f"我尝试为 `{file_path}` 建立向量索引时失败：{e}。请确认文件路径是否存在，或告诉我要索引的工作表名。"
    if isinstance(result, dict) and result.get("error"):
        msg = result.get("message") or result.get("error")
        return f"我尝试为 `{file_path}` 建立向量索引失败：{msg}。请确认路径正确，或把目标工作表名发我。"
    return None


def _xcagi_chat_timeout_seconds() -> float:
    raw = os.environ.get("XCAGI_CHAT_TIMEOUT_SEC", "120").strip()
    try:
        v = float(raw)
        return max(5.0, min(v, 600.0))
    except ValueError:
        return 120.0


def _xcagi_stream_first_token_timeout_seconds() -> float:
    raw = os.environ.get("XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC", "20").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 20.0
    return max(3.0, min(value, 120.0))


def _xcagi_stream_idle_notice_seconds() -> float:
    raw = os.environ.get("XCAGI_CHAT_STREAM_IDLE_NOTICE_SEC", "12").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 12.0
    return max(5.0, min(value, 60.0))


def _xcagi_chat_timeout_error_payload(timeout: float) -> dict:
    msg = f"对话处理超时（>{int(timeout)} 秒）。可缩短问题后重试，或由管理员调大环境变量 XCAGI_CHAT_TIMEOUT_SEC。"
    return {
        "success": False,
        "message": msg,
        "response": msg,
        "data": {"text": msg, "response": msg},
    }


def _xcagi_guarded_planner_stream_events(
    body: XcagiCompatChatBody,
    *,
    runtime_context: dict[str, Any] | None,
    workspace_root: str,
    client: Any,
):
    event_queue: queue.Queue[Any] = queue.Queue()
    done_marker = object()

    def _worker() -> None:
        try:
            for ev in chat_stream_sse_events(
                body.message,
                runtime_context=runtime_context or None,
                system_prompt=body.system_prompt,
                workspace_root=workspace_root,
                db_write_token=body.db_write_token,
                client=client,
            ):
                event_queue.put(ev)
            from app.legacy.chat.legacy_chat_adapter import get_last_tool_records

            records = get_last_tool_records()
            if records:
                event_queue.put({"type": "legacy_tool_records", "records": records})
        except BOUNDARY_ERRORS as exc:
            event_queue.put(exc)
        finally:
            event_queue.put(done_marker)

    threading.Thread(target=_worker, daemon=True, name="xcagi-chat-stream-guard").start()

    total_timeout = _xcagi_chat_timeout_seconds()
    first_token_timeout = min(_xcagi_stream_first_token_timeout_seconds(), total_timeout)
    idle_notice_seconds = _xcagi_stream_idle_notice_seconds()
    started_at = time.monotonic()
    first_event_seen = True
    yield MODEL_STREAM_ACCEPTED_EVENT

    while True:
        elapsed = time.monotonic() - started_at
        if elapsed >= total_timeout:
            raise TimeoutError(
                f"流式对话总超时（>{int(total_timeout)} 秒）。请稍后重试，或缩短问题范围。"
            )

        wait_timeout = first_token_timeout if not first_event_seen else idle_notice_seconds
        wait_timeout = max(0.2, min(wait_timeout, total_timeout - elapsed))
        try:
            item = event_queue.get(timeout=wait_timeout)
        except queue.Empty:
            elapsed_int = int(time.monotonic() - started_at)
            if not first_event_seen:
                raise TimeoutError(
                    f"流式对话首包超时（>{int(first_token_timeout)} 秒）。模型服务暂未返回首个分片，请稍后重试。"
                )
            yield {
                "type": "token",
                "text": f"\n（仍在处理中，已等待 {elapsed_int} 秒，请稍候…）\n",
                "ephemeral": True,
            }
            continue

        if item is done_marker:
            return
        if isinstance(item, Exception):
            exc = _xcagi_chat_http_exc(item)
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            yield {"type": "error", "message": detail, "status_code": exc.status_code}
            return

        first_event_seen = True
        yield item


def _sse_event_line(payload: dict) -> bytes:
    return ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode("utf-8")


def _sse_payload_with_run_id(payload: dict[str, Any], run_id: str | None) -> dict[str, Any]:
    if not run_id:
        return payload
    enriched = dict(payload)
    enriched["run_id"] = run_id
    enriched["agent_run_id"] = run_id
    return enriched


def _thinking_steps_from_planner_stream_text(merged: str) -> str | None:
    if not (merged or "").strip():
        return None
    lines: list[str] = []
    for m in re.finditer(r"\[正在调用工具:[^\]\n]+\]", merged):
        s = m.group(0).strip()
        if s and s not in lines:
            lines.append(s)
    for m in re.finditer(r"\[工具已返回[^\]\n]*\]|\[工具未成功[^\]\n]*\]", merged):
        s = m.group(0).strip()
        if s and s not in lines:
            lines.append(s)
    for m in re.finditer(r"\[需要授权:[^\]\n]+\]|\[请提供令牌:[^\]\n]+\]", merged):
        s = m.group(0).strip()
        if s and s not in lines:
            lines.append(s)
    if not lines:
        return None
    return "\n".join(lines)


async def _xcagi_planner_stream_bytes_async(
    request: Request, body: XcagiCompatChatBody, *, ai_tier: str
):
    """Async generator wrapper around _xcagi_planner_stream_bytes.

    Runs the sync generator in a background thread and feeds items through an
    asyncio.Queue so the event loop is NEVER blocked.  This avoids the
    Starlette BaseHTTPMiddleware / anyio thread-pool deadlock that occurs when
    a sync StreamingResponse generator is iterated via iterate_in_threadpool
    while the middleware task-group is still open.
    """
    _SENTINEL = object()
    async_q: asyncio.Queue = asyncio.Queue(maxsize=128)
    loop = asyncio.get_running_loop()

    def _feed_queue() -> None:
        try:
            for chunk in _xcagi_planner_stream_bytes(request, body, ai_tier=ai_tier):
                asyncio.run_coroutine_threadsafe(async_q.put(chunk), loop).result(timeout=120)
        except BOUNDARY_ERRORS as exc:
            err_msg = str(exc).strip() or exc.__class__.__name__
            err_line = _sse_event_line({"type": "error", "message": err_msg})
            try:
                asyncio.run_coroutine_threadsafe(async_q.put(err_line), loop).result(timeout=5)
            except RECOVERABLE_ERRORS:
                pass
        finally:
            asyncio.run_coroutine_threadsafe(async_q.put(_SENTINEL), loop).result(timeout=5)

    thread = threading.Thread(target=_feed_queue, daemon=True, name="xcagi-stream-async-bridge")
    thread.start()

    while True:
        item = await async_q.get()
        if item is _SENTINEL:
            break
        yield item


from app.fastapi_routes.xcagi_compat_chat_stream import (
    _xcagi_planner_stream_bytes as _xcagi_planner_stream_bytes,
)
