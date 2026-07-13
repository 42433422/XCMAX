"""Small render helpers shared by workflow response builders."""

from __future__ import annotations

import json
from typing import Any


def workflow_output_preview(output: Any, max_chars: int = 700) -> str:
    if output is None:
        return ""
    value = output
    if isinstance(output, dict):
        value = {
            key: item
            for key, item in output.items()
            if key
            in {
                "success",
                "message",
                "error",
                "employee_id",
                "exists",
                "created",
                "unit_name",
                "matched_count",
                "redirect",
            }
        }
        data = output.get("data")
        if isinstance(data, list):
            value["row_count"] = len(data)
            value["rows"] = data[:5]
        elif isinstance(data, dict):
            value["data"] = {
                key: item
                for key, item in data.items()
                if key
                in {
                    "summary",
                    "result",
                    "error",
                    "success",
                    "registered_tool_count",
                    "available_employee_ids",
                }
            } or str(data)[:260]
        elif data is not None:
            value["data"] = data
        raw = output.get("raw")
        if raw is not None and "data" not in value:
            value["raw"] = str(raw)[:260]
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    text = text.strip()
    if len(text) > max_chars:
        return text[:max_chars] + "..."
    return text


def workflow_output_message(output: Any) -> str:
    if not isinstance(output, dict):
        return ""
    return str(output.get("message") or output.get("error") or "").strip()
