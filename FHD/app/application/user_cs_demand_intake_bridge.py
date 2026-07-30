"""需求采集员工结果归一化与 pipeline 标记。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _employee_data(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data") if isinstance(result, dict) else None
    return data if isinstance(data, dict) else {}


def _employee_result_ok(result: dict[str, Any]) -> bool:
    if not isinstance(result, dict) or not result.get("success"):
        return False
    data = _employee_data(result)
    return data.get("ok") is not False and data.get("success") is not False


def _employee_demand_items_ready(result: dict[str, Any]) -> bool:
    items = _employee_data(result).get("items")
    return bool(items) and isinstance(items, list) and isinstance(items[0], dict)


def _normalize_employee_failure(result: dict[str, Any], default: str) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"success": False, "error": default, "data": {"ok": False, "error": default}}
    data = dict(_employee_data(result))
    error = str(data.get("error") or data.get("summary") or result.get("error") or default)[:500]
    data.setdefault("ok", False)
    data.setdefault("error", error)
    return {**result, "success": False, "error": error, "data": data}


def normalize_demand_intake_result(
    result: dict[str, Any],
    *,
    signed_url: str,
    fallback_url: str,
) -> tuple[dict[str, Any], bool]:
    employee_ok = _employee_result_ok(result)
    if employee_ok and signed_url:
        data = _employee_data(result)
        items = list(data.get("items") or [])
        if items and isinstance(items[0], dict):
            items[0] = {**items[0], "form_url": signed_url}
            text = items[0].get("message_text")
            if isinstance(text, str) and signed_url not in text:
                items[0]["message_text"] = text.replace(fallback_url, signed_url)
            data["items"] = items
            data["form_url"] = signed_url
            result["data"] = data
    employee_ok = employee_ok and _employee_demand_items_ready(result)
    if not employee_ok:
        result = _normalize_employee_failure(result, "demand_intake_failed")
    return result, employee_ok


def mark_demand_intake_sent(market_user_id: int) -> dict[str, Any]:
    from app.services.user_cs_pipeline import load_pipeline, save_pipeline

    doc = load_pipeline(int(market_user_id))
    doc["intake_sent"] = True
    current_stage = str(doc.get("stage") or "idle")
    next_stage = "intake" if current_stage in {"idle", "connected"} else current_stage
    doc["stage"] = next_stage
    timeline = list(doc.get("timeline") or [])
    timeline.append(
        {
            "stage": next_stage,
            "at": datetime.now(UTC).isoformat(),
            "source": "demand_intake",
        }
    )
    doc["timeline"] = timeline[-30:]
    return save_pipeline(doc)
