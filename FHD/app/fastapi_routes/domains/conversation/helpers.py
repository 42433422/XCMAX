"""
XCAGI 前端兼容 API — AI 聊天辅助函数与数据模型。

供 xcagi_compat_chat / xcagi_compat_misc 等模块复用。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from openai import APIConnectionError, APIError, AuthenticationError, RateLimitError
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.application.agent_orchestrator.chat_trace import (
    attach_chat_trace_run as attach_chat_trace_run,
)
from app.application.chat_reply_safety import (
    sanitize_model_chat_reply as sanitize_model_chat_reply,
)
from app.application.modstore_conversation_app import (
    create_modstore_openai_client_from_request as create_modstore_openai_client_from_request,
)
from app.application.workflow.multimodal_user_content import (
    EmptyMultimodalResponseError,
    UnsupportedMultimodalModelError,
)
from app.domain.ai.tier import runtime_context_with_tier as runtime_context_with_tier
from app.domain.context.session_context import (
    planner_workflow_interrupt_reply as planner_workflow_interrupt_reply,
)
from app.domain.context.session_context import (
    runtime_context_after_workflow_interrupt as runtime_context_after_workflow_interrupt,
)
from app.infrastructure.auth.db_token import effective_db_read_token
from app.infrastructure.llm.client import set_mode as set_llm_mode  # noqa: F401
from app.legacy.chat.legacy_chat_adapter import (
    chat_stream_sse_events as chat_stream_sse_events,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

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


class XcagiCompatChatBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("message", "user_message", "content", "text", "query"),
    )
    context: dict | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "context",
            "runtime_context",
            "session_context",
            "ddd_context",
            "neuro_context",
            "neuro_ddd_context",
        ),
    )
    system_prompt: str | None = Field(
        default=None,
        validation_alias=AliasChoices("system_prompt", "system", "instructions"),
    )
    mode: str | None = Field(
        default=None,
        validation_alias=AliasChoices("mode", "llm_mode"),
    )
    db_read_token: str | None = Field(
        default=None,
        description="兼容旧客户端字段；当前版本不需要数据库查看授权。",
    )
    db_write_token: str | None = Field(
        default=None,
        description="兼容旧客户端字段；当前版本不需要数据库写入授权。",
    )
    user_id: str | None = None
    source: str | None = None


class XcagiCompatChatBatchBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    messages: list[str] = Field(default_factory=list)
    context: dict | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "context",
            "runtime_context",
            "session_context",
            "ddd_context",
            "neuro_context",
            "neuro_ddd_context",
        ),
    )
    system_prompt: str | None = Field(
        default=None,
        validation_alias=AliasChoices("system_prompt", "system", "instructions"),
    )
    mode: str | None = Field(
        default=None,
        validation_alias=AliasChoices("mode", "llm_mode"),
    )
    db_read_token: str | None = Field(default=None)
    db_write_token: str | None = Field(default=None)
    user_id: str | None = None
    source: str | None = None


def _market_connection_label() -> str:
    raw = os.environ.get("XCAGI_MARKET_BASE_URL") or os.environ.get("MODSTORE_PLATFORM_URL") or ""
    try:
        return urlsplit(raw).hostname or "修茈市场"
    except ValueError:
        return "修茈市场"


def _xcagi_chat_http_exc(exc: BaseException) -> HTTPException:
    if isinstance(exc, TimeoutError):
        msg = str(exc).strip() or "大模型响应超时，请稍后重试。"
        return HTTPException(status_code=504, detail=msg)
    try:
        import httpx

        if isinstance(exc, httpx.ConnectError):
            return HTTPException(
                status_code=503,
                detail=f"无法连接修茈平台 LLM（{_market_connection_label()}）",
            )
        if isinstance(exc, httpx.HTTPError):
            return HTTPException(status_code=502, detail="修茈平台 LLM 请求失败")
    except ImportError:
        pass
    if isinstance(exc, AuthenticationError):
        return HTTPException(status_code=401, detail=f"大模型鉴权失败: {exc}")
    if isinstance(exc, RateLimitError):
        return HTTPException(status_code=429, detail=f"大模型限流: {exc}")
    if isinstance(exc, APIConnectionError):
        return HTTPException(status_code=503, detail=f"无法连接大模型服务: {exc}")
    if isinstance(exc, APIError):
        return HTTPException(status_code=502, detail=f"大模型接口错误: {exc}")
    if isinstance(exc, UnsupportedMultimodalModelError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, EmptyMultimodalResponseError):
        return HTTPException(status_code=502, detail=str(exc))
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, ValueError):
        msg = str(exc).strip()
        if "余额不足" in msg or "402" in msg:
            return HTTPException(
                status_code=402,
                detail="修茈市场模型余额不足，请在「模型支付」充值后重试。",
            )
        if "平台错误" in msg:
            return HTTPException(status_code=502, detail=msg)
    logger.exception("xcagi ai chat compat unexpected error")
    return HTTPException(status_code=500, detail=f"对话处理失败: {exc}")


from app.fastapi_routes.domains.conversation.reply_helpers import (
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
    raw = os.environ.get("XCAGI_CHAT_STREAM_IDLE_NOTICE_SEC", "5").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 5.0
    return max(3.0, min(value, 60.0))


def _xcagi_chat_timeout_error_payload(timeout: float) -> dict:
    msg = f"对话处理超时（>{int(timeout)} 秒）。可缩短问题后重试，或由管理员调大环境变量 XCAGI_CHAT_TIMEOUT_SEC。"
    return {
        "success": False,
        "message": msg,
        "response": msg,
        "data": {"text": msg, "response": msg},
    }


from app.fastapi_routes.domains.conversation.stream_helpers import (
    _sse_event_line as _sse_event_line,
)
from app.fastapi_routes.domains.conversation.stream_helpers import (
    _thinking_steps_from_planner_stream_text as _thinking_steps_from_planner_stream_text,
)
from app.fastapi_routes.domains.conversation.stream_helpers import (
    _xcagi_guarded_planner_stream_events as _xcagi_guarded_planner_stream_events,
)
from app.fastapi_routes.domains.conversation.stream_helpers import (
    _xcagi_planner_stream_bytes as _xcagi_planner_stream_bytes,
)
from app.fastapi_routes.domains.conversation.stream_helpers import (
    _xcagi_planner_stream_bytes_async as _xcagi_planner_stream_bytes_async,
)
from app.fastapi_routes.domains.conversation.stream_helpers import (
    strip_planner_stream_markers as strip_planner_stream_markers,
)
