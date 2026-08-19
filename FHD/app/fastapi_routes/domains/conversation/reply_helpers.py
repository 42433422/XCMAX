"""Compatibility reply payload projection."""

from __future__ import annotations

import logging
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


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
