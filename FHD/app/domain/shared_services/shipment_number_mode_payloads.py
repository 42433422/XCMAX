"""Failure payload construction for strict shipment-number mode."""

from __future__ import annotations

import difflib
from typing import Any


def build_unit_not_found_payload(typed_unit: str, all_units: list[str]) -> dict[str, Any]:
    typed = str(typed_unit or "").strip()
    if any(unit == typed for unit in all_units):
        return {}
    contains = [unit for unit in all_units if typed and (typed in unit or unit in typed)]
    fuzzy = difflib.get_close_matches(typed, all_units, n=5, cutoff=0.35) if typed else []
    suggestions: list[str] = []
    for unit in contains + fuzzy:
        if unit and unit not in suggestions:
            suggestions.append(unit)
        if len(suggestions) >= 5:
            break
    if suggestions:
        choices = "；".join(f"{index + 1}){name}" for index, name in enumerate(suggestions))
        message = f"未找到购买单位：{typed}。请确认单位名称后重试，或从候选中选择：{choices}。"
    else:
        message = f"未找到购买单位：{typed}。请先创建该购买单位，或输入已存在的单位名称后再生成。"
    return {
        "success": False,
        "message": message,
        "error_code": "purchase_unit_not_found",
        "data": {
            "input_unit_name": typed,
            "candidate_units": suggestions,
            "need_confirm_unit": True,
        },
    }


__all__ = ["build_unit_not_found_payload"]
