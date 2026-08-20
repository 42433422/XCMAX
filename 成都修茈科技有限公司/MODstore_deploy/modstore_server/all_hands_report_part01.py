# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.all_hands_report")


def clamp_all_hands_max_employees(raw: int | float | str | None, *, default: int = 8) -> int:
    try:
        n = int(raw if raw is not None else default)
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, _facade().MAX_ALL_HANDS_EMPLOYEES))


def all_hands_employee_timeout_sec() -> float:
    """单员工汇报上限；避免末位员工 LLM/联网挂死导致 UI 长期停在 19/20。"""
    raw = (_facade().os.environ.get("MODSTORE_ALL_HANDS_EMPLOYEE_TIMEOUT_SEC") or "60").strip()
    try:
        sec = float(raw)
    except (TypeError, ValueError):
        sec = 60.0
    return max(30.0, min(sec, 900.0))
