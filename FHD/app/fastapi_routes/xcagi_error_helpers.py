"""Error helpers extracted from the XCAGI chat compatibility module."""

from __future__ import annotations

import logging
import os
import re
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException
from openai import APIConnectionError, APIError, AuthenticationError, RateLimitError

from app.application.workflow.multimodal_user_content import (
    EmptyMultimodalResponseError,
    UnsupportedMultimodalModelError,
)
from app.utils.mixin_module_sync import sync_module_functions
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class _XcagiStreamFirstResponseTimeout(TimeoutError):
    """The upstream model did not produce a first event before the deadline."""

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout
        super().__init__(
            f"模型服务在>{int(timeout)} 秒内未返回可处理结果。请稍后重试或切换可用模型。"
        )


def _market_connection_label() -> str:
    raw = os.environ.get("XCAGI_MARKET_BASE_URL") or os.environ.get("MODSTORE_PLATFORM_URL") or ""
    try:
        return urlsplit(raw).hostname or "修茈市场"
    except ValueError:
        return "修茈市场"


def _model_provider_error_detail() -> dict[str, str]:
    """Return the safe, stable public shape for non-quota provider failures.

    Platform adapters intentionally retain upstream bodies in exceptions for
    diagnostics.  Those bodies must not be copied into desktop SSE because
    they can contain opaque provider details or credential-adjacent metadata.
    """

    return {
        "code": "MODEL_PROVIDER_ERROR",
        "message": "模型服务暂时不可用，请稍后重试或切换可用模型。",
    }


def _market_429_error_detail(
    exc: BaseException, *, force_429: bool = False
) -> dict[str, str] | None:
    """Translate a provider-side 429 into a safe, actionable chat error.

    Market adapters intentionally keep the upstream body in their exception for
    diagnostics.  Do not return that body to the desktop: it can be opaque,
    unstable, and occasionally contains provider-specific implementation
    details.  The chat API instead exposes a stable code and a Chinese action.
    """

    raw_parts = [str(exc)]
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    try:
        response_text = str(getattr(response, "text", "") or "")
    except RuntimeError:  # pragma: no cover - unread streaming response
        response_text = ""
    if response_text:
        raw_parts.append(response_text[:500])
    raw = " ".join(raw_parts).lower()
    is_429 = force_429 or status_code == 429 or bool(re.search(r"(?<!\d)429(?!\d)", raw))
    if not is_429:
        return None

    quota_markers = (
        "quota exhausted",
        "quota_exhausted",
        "insufficient quota",
        "insufficient_quota",
        "配额",
        "额度",
        "余额不足",
    )
    if any(marker in raw for marker in quota_markers):
        return {
            "code": "MODEL_QUOTA_EXHAUSTED",
            "message": "模型服务配额已用尽，请在「模型支付」充值或切换可用模型后重试。",
        }
    return {
        "code": "MODEL_RATE_LIMITED",
        "message": "模型服务请求过于频繁，请稍后重试。",
    }


def _xcagi_chat_error_event(exc: HTTPException) -> dict[str, Any]:
    """Serialize a chat exception for SSE without losing a stable error code."""

    raw_detail = exc.detail
    if isinstance(raw_detail, dict):
        message = str(raw_detail.get("message") or "对话处理失败")
        code = str(raw_detail.get("code") or "").strip()
    else:
        message = str(raw_detail)
        code = ""
    payload: dict[str, Any] = {
        "type": "error",
        "message": message,
        "status_code": exc.status_code,
    }
    if code:
        payload["code"] = code
        payload["error_code"] = code
    return payload


def _xcagi_chat_http_exc(exc: BaseException) -> HTTPException:
    if isinstance(exc, _XcagiStreamFirstResponseTimeout):
        return HTTPException(
            status_code=504,
            detail={
                "code": "MODEL_FIRST_RESPONSE_TIMEOUT",
                "message": str(exc),
            },
        )
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
        market_429 = _market_429_error_detail(exc)
        if market_429 is not None:
            return HTTPException(status_code=429, detail=market_429)
        if isinstance(exc, httpx.HTTPError):
            return HTTPException(status_code=502, detail="修茈平台 LLM 请求失败")
    except ImportError:
        pass
    if isinstance(exc, AuthenticationError):
        return HTTPException(status_code=401, detail=f"大模型鉴权失败: {exc}")
    if isinstance(exc, RateLimitError):
        return HTTPException(
            status_code=429,
            detail=_market_429_error_detail(exc, force_429=True),
        )
    if isinstance(exc, APIConnectionError):
        return HTTPException(
            status_code=503,
            detail={
                "code": "MODEL_PROVIDER_UNAVAILABLE",
                "message": "模型服务暂时不可用，请稍后重试。",
            },
        )
    if isinstance(exc, APIError):
        return HTTPException(status_code=502, detail=_model_provider_error_detail())
    if isinstance(exc, UnsupportedMultimodalModelError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, EmptyMultimodalResponseError):
        return HTTPException(status_code=502, detail=str(exc))
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, ValueError):
        msg = str(exc).strip()
        market_429 = _market_429_error_detail(exc)
        if market_429 is not None:
            return HTTPException(status_code=429, detail=market_429)
        if "余额不足" in msg or "402" in msg:
            return HTTPException(
                status_code=402,
                detail="修茈市场模型余额不足，请在「模型支付」充值后重试。",
            )
        if "平台错误" in msg:
            return HTTPException(status_code=502, detail=_model_provider_error_detail())
    logger.exception("xcagi ai chat compat unexpected error")
    return HTTPException(status_code=500, detail=f"对话处理失败: {exc}")


def _xcagi_compat_reply_payload(
    reply: str | dict,
    *,
    runtime_context_update: dict[str, Any] | None = None,
    kitten_attachments: dict[str, Any] | None = None,
) -> dict:
    thinking_steps: str | None = None
    if isinstance(reply, dict):
        thinking_steps = reply.get("thinking_steps")
        text = str(reply.get("response") or reply.get("text") or "")
    else:
        text = str(reply or "")

    tool_data: dict = {}
    last_result: dict = {}
    reply_records: list[dict[str, Any]] = []
    if isinstance(reply, dict):
        raw_reply_records = reply.get("legacy_tool_records") or reply.get("_tool_records")
        if isinstance(raw_reply_records, list):
            reply_records = [item for item in raw_reply_records if isinstance(item, dict)]
    try:
        if reply_records:
            last_record = reply_records[-1]
            raw_output = last_record.get("output")
            raw = dict(raw_output) if isinstance(raw_output, dict) else {}
            raw.setdefault(
                "tool_key", last_record.get("tool_id") or last_record.get("tool_name") or ""
            )
            raw.setdefault(
                "tool_name", last_record.get("tool_name") or last_record.get("tool_id") or ""
            )
            raw.setdefault("tool_call_id", last_record.get("tool_call_id") or "")
            raw.setdefault("tool_params", dict(last_record.get("params") or {}))
            raw["_tool_records"] = reply_records
        else:
            from app.legacy.chat.legacy_chat_adapter import get_last_tool_result

            raw = get_last_tool_result()
        if isinstance(raw, dict) and raw:
            last_result = raw
            raw_records = raw.get("_tool_records")
            records = raw_records if isinstance(raw_records, list) else []
            if records:
                tool_data["legacy_tool_records"] = records
            from app.application.tools import flatten_tool_result_dict_for_client

            tool_data = flatten_tool_result_dict_for_client(raw)
            if records:
                tool_data["legacy_tool_records"] = records
            errs = raw.get("errors")
            if isinstance(errs, list) and errs:
                preview = errs[:5]
                joined = "; ".join(str(x) for x in preview if x is not None)
                tool_data["errors_preview"] = joined[:2000]
                if len(errs) > 5:
                    tool_data["errors_truncated"] = True
    except RECOVERABLE_ERRORS:
        logger.debug("compat: last tool result unavailable", exc_info=True)

    err_code = str(last_result.get("error") or "").strip()
    err_msg = str(last_result.get("message") or "").strip()
    tool_key = str(last_result.get("tool_key") or "").strip()
    if err_code or (last_result.get("success") is False):
        notice_lines = ["---", "**工具反馈**（最近一次）"]
        if tool_key:
            notice_lines.append(f"- 工具：`{tool_key}`")
        if err_code:
            notice_lines.append(f"- 错误码：`{err_code}`")
        if err_msg:
            notice_lines.append(f"- 说明：{err_msg}")
        ep = tool_data.get("errors_preview")
        if ep:
            notice_lines.append(f"- 明细摘要：{ep}")
        notice = "\n".join(notice_lines)
        if notice not in text:
            text = f"{text.rstrip()}\n\n{notice}".strip()

    data: dict[str, Any] = {
        "response": text,
        "text": text,
        "thinking_steps": thinking_steps,
        **tool_data,
    }
    if runtime_context_update is not None:
        data["runtime_context"] = runtime_context_update
    if kitten_attachments:
        for k, v in kitten_attachments.items():
            if v is not None:
                data[k] = v

    return {"success": True, "response": text, "data": data}


sync_module_functions(
    target=globals(),
    source_module="app.fastapi_routes.xcagi_compat_chat_helpers",
    function_names=(
        "_market_connection_label",
        "_model_provider_error_detail",
        "_market_429_error_detail",
        "_xcagi_chat_error_event",
        "_xcagi_chat_http_exc",
        "_xcagi_compat_reply_payload",
    ),
)
