"""Meeting limits and craft-workshop standby policy."""

from __future__ import annotations

import os

from modstore_server.operational_errors import RECOVERABLE_ERRORS

MAX_ALL_HANDS_EMPLOYEES = 128


def clamp_all_hands_max_employees(raw: int | float | str | None, *, default: int = 8) -> int:
    try:
        n = int(raw if raw is not None else default)
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, MAX_ALL_HANDS_EMPLOYEES))


def all_hands_employee_timeout_sec() -> float:
    """单员工汇报上限；避免末位员工 LLM/联网挂死导致 UI 长期停在 19/20。"""
    raw = (os.environ.get("MODSTORE_ALL_HANDS_EMPLOYEE_TIMEOUT_SEC") or "60").strip()
    try:
        sec = float(raw)
    except (TypeError, ValueError):
        sec = 60.0
    return max(30.0, min(sec, 900.0))


def all_hands_concurrency_default() -> int:
    """允许通过环境变量覆盖的默认并发上限。"""
    raw = (os.environ.get("MODSTORE_ALL_HANDS_CONCURRENCY") or "").strip()
    if raw.isdigit():
        return max(1, min(int(raw), 4))
    return 2


def _craft_workshop_pkg_ids() -> frozenset[str]:
    try:
        from modstore_server.duty_roster import YUANGON_AREAS

        ids = YUANGON_AREAS.get("craft-workshop", {}).get("ids") or []
        if not isinstance(ids, (list, tuple, set, frozenset)):
            raise TypeError("craft-workshop employee IDs must be a collection")
        return frozenset((str(x).strip() for x in ids if str(x).strip()))
    except RECOVERABLE_ERRORS:
        return frozenset(
            {
                "intent-analyst",
                "employee-planner",
                "artifact-generator",
                "quality-validator",
                "miniapp-builder",
                "script-binder",
                "workflow-automator",
                "pack-registrar",
                "sandbox-tester",
                "code-validator",
                "self-checker",
                "host-checker",
                "hex-quality-assessor",
            }
        )


CRAFT_WORKSHOP_STANDBY_IDS = _craft_workshop_pkg_ids()


def _should_standby_manifest_report(pkg_id: str, *, user_question: str) -> bool:
    """制作车间 + 无用户提问 → 跳过 execute_employee_task，避免流水线 JSON 告警。"""
    return not (user_question or "").strip() and pkg_id in CRAFT_WORKSHOP_STANDBY_IDS
