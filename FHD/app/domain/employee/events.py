"""标准 AI 员工事件类型 + manifest.triggers 键映射。

员工触发（``triggers.on_error`` 等）通过 NeuroBus 订阅这些事件类型实现。
事件类型命名遵循 ``employee.<domain>.<verb>`` 约定，与既有 NeuroBus 事件风格一致。
"""

from __future__ import annotations

from typing import Any

EMPLOYEE_EVENT_PREFIX = "employee"

EVENT_TASK_FAILED = "employee.task.failed"
EVENT_QUALITY_FAILED = "employee.quality.failed"
EVENT_COVERAGE_MISSED = "employee.coverage.missed"
EVENT_TASK_COMPLETED = "employee.task.completed"

# manifest.triggers 的布尔键 → 应订阅的事件类型
TRIGGER_KEY_EVENT_MAP: dict[str, str] = {
    "on_error": EVENT_TASK_FAILED,
    "on_quality_fail": EVENT_QUALITY_FAILED,
    "on_coverage_miss": EVENT_COVERAGE_MISSED,
}

ALL_EMPLOYEE_EVENT_TYPES = (
    EVENT_TASK_FAILED,
    EVENT_QUALITY_FAILED,
    EVENT_COVERAGE_MISSED,
    EVENT_TASK_COMPLETED,
)


def _truthy(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return False


def event_types_for_triggers(triggers: dict[str, Any] | None) -> list[str]:
    """根据 manifest.triggers 的布尔开关返回应订阅的事件类型列表。"""
    if not isinstance(triggers, dict):
        return []
    out: list[str] = []
    for key, event_type in TRIGGER_KEY_EVENT_MAP.items():
        if _truthy(triggers.get(key)):
            out.append(event_type)
    return out


__all__ = [
    "ALL_EMPLOYEE_EVENT_TYPES",
    "EMPLOYEE_EVENT_PREFIX",
    "EVENT_COVERAGE_MISSED",
    "EVENT_QUALITY_FAILED",
    "EVENT_TASK_COMPLETED",
    "EVENT_TASK_FAILED",
    "TRIGGER_KEY_EVENT_MAP",
    "event_types_for_triggers",
]
