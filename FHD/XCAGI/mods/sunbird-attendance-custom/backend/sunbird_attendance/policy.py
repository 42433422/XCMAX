"""Private conversion policy; independent of the host approval settings."""

from typing import Any

from fastapi import HTTPException

from .rules import (
    COMPANY_FACTORY_GROUP_KEYWORDS,
    DEFAULT_WEEKDAY_SEGMENTS,
    parse_shift_ranges,
)


def normalize_policy(raw: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "company_factory_group_keywords": list(COMPANY_FACTORY_GROUP_KEYWORDS),
        "weekday_segments": [
            f"{item.start:%H:%M}-{item.end:%H:%M}" for item in DEFAULT_WEEKDAY_SEGMENTS
        ],
        "sunday_empty_schedule": True,
        "sunday_map_sqrt_to_star": True,
    }
    for key in ("sunday_empty_schedule", "sunday_map_sqrt_to_star"):
        if key in raw:
            if not isinstance(raw[key], bool):
                raise HTTPException(400, f"{key} 必须是布尔值")
            result[key] = raw[key]
    for key in ("company_factory_group_keywords", "weekday_segments"):
        if key not in raw:
            continue
        value = raw[key]
        if (
            not isinstance(value, list)
            or len(value) > 64
            or any(not isinstance(item, str) or len(item) > 128 for item in value)
        ):
            raise HTTPException(400, f"{key} 必须是文本列表")
        value = [item.strip() for item in value if item.strip()]
        if key == "weekday_segments":
            if not value:
                raise HTTPException(400, "请至少保留一个工作时段")
            try:
                if any(len(parse_shift_ranges(item)) != 1 for item in value):
                    raise ValueError("invalid segment")
            except ValueError:
                raise HTTPException(
                    400, "工作时段格式应为 08:00-12:00，结束时间晚于开始时间"
                ) from None
        result[key] = value
    return result
