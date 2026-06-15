"""Planner 工具结果 → 前端可消费字段（下载链接等）。"""

from __future__ import annotations

from typing import Any

_CLIENT_KEYS = (
    "download_url",
    "file_name",
    "doc_name",
    "file_path",
    "pickup_token",
    "order_number",
    "record_id",
    "message",
)


def _pick_client_fields(src: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in _CLIENT_KEYS:
        val = src.get(key)
        if val is None or val == "":
            continue
        out[key] = val
    return out


def flatten_tool_result_dict_for_client(raw: dict[str, Any] | None) -> dict[str, Any]:
    """将工具 handler 返回的 JSON 压平为 compat chat ``data.*`` 字段。"""
    if not isinstance(raw, dict) or not raw:
        return {}

    out = _pick_client_fields(raw)
    nested = raw.get("data")
    if isinstance(nested, dict):
        for key, val in _pick_client_fields(nested).items():
            out.setdefault(key, val)

    document = raw.get("document")
    if isinstance(document, dict):
        for key, val in _pick_client_fields(document).items():
            out.setdefault(key, val)

    if raw.get("success") is not None:
        out["tool_success"] = raw.get("success")
    tool_key = str(raw.get("tool_key") or raw.get("tool_name") or "").strip()
    if tool_key:
        out["tool_key"] = tool_key

    if raw.get("error"):
        out["tool_error"] = str(raw.get("error"))[:500]

    return out


__all__ = ["flatten_tool_result_dict_for_client"]
