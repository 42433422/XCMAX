"""Request models and response mapping for XCAGI compatibility chat."""

from __future__ import annotations

import importlib
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException
from openai import APIConnectionError, APIError, AuthenticationError, RateLimitError
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.application.workflow.multimodal_user_content import (
    EmptyMultimodalResponseError,
    UnsupportedMultimodalModelError,
)


def _facade():
    return importlib.import_module("app.fastapi_routes.xcagi_compat_chat_helpers")


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
        default=None, validation_alias=AliasChoices("system_prompt", "system", "instructions")
    )
    mode: str | None = Field(default=None, validation_alias=AliasChoices("mode", "llm_mode"))
    db_read_token: str | None = Field(
        default=None, description="兼容旧客户端字段；当前版本不需要数据库查看授权。"
    )
    db_write_token: str | None = Field(
        default=None, description="兼容旧客户端字段；当前版本不需要数据库写入授权。"
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
        default=None, validation_alias=AliasChoices("system_prompt", "system", "instructions")
    )
    mode: str | None = Field(default=None, validation_alias=AliasChoices("mode", "llm_mode"))
    db_read_token: str | None = Field(default=None)
    db_write_token: str | None = Field(default=None)
    user_id: str | None = None
    source: str | None = None


def _market_connection_label() -> str:
    raw = (
        _facade().os.environ.get("XCAGI_MARKET_BASE_URL")
        or _facade().os.environ.get("MODSTORE_PLATFORM_URL")
        or ""
    )
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
                detail=f"无法连接修茈平台 LLM（{_facade()._market_connection_label()}）",
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
                status_code=402, detail="修茈市场模型余额不足，请在「模型支付」充值后重试。"
            )
        if "平台错误" in msg:
            return HTTPException(status_code=502, detail=msg)
    _facade().logger.exception("xcagi ai chat compat unexpected error")
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
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.debug("compat: last tool result unavailable", exc_info=True)
    err_code = str(last_result.get("error") or "").strip()
    err_msg = str(last_result.get("message") or "").strip()
    tool_key = str(last_result.get("tool_key") or "").strip()
    if err_code or last_result.get("success") is False:
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
