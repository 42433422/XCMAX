"""员工 ReAct / agent loop 退出状态公约（FHD ↔ MODstore 语义对齐）。

成功仅 ``completed``；其余失败类不得被记为 ``ok: True`` / ``success: True``。
"""

from __future__ import annotations

from typing import Any

EXIT_COMPLETED = "completed"
EXIT_MAX_ITERATIONS = "max_iterations"
EXIT_MAX_ROUNDS = "max_rounds"
EXIT_STUCK_REPEATING = "stuck_repeating_action"
EXIT_WALL_TIME = "wall_time_limit"
EXIT_LLM_ERROR = "llm_error"
EXIT_LLM_UNAVAILABLE = "llm_unavailable"

FAILURE_EXIT_STATUSES = frozenset(
    {
        EXIT_MAX_ITERATIONS,
        EXIT_MAX_ROUNDS,
        EXIT_STUCK_REPEATING,
        EXIT_WALL_TIME,
        EXIT_LLM_ERROR,
        EXIT_LLM_UNAVAILABLE,
    }
)


def is_failure_exit_status(status: Any) -> bool:
    return str(status or "").strip() in FAILURE_EXIT_STATUSES


def is_success_exit_status(status: Any) -> bool:
    return str(status or "").strip() == EXIT_COMPLETED


def extract_exit_status(payload: dict[str, Any] | None) -> str:
    data = payload if isinstance(payload, dict) else {}
    direct = str(data.get("exit_status") or "").strip()
    if direct:
        return direct
    nested = data.get("result")
    if isinstance(nested, dict):
        nested_status = str(nested.get("exit_status") or "").strip()
        if nested_status:
            return nested_status
        outputs = nested.get("outputs")
        if isinstance(outputs, list):
            for item in outputs:
                if not isinstance(item, dict):
                    continue
                out = item.get("output") if isinstance(item.get("output"), dict) else item
                if isinstance(out, dict):
                    st = str(out.get("exit_status") or "").strip()
                    if st:
                        return st
    outputs = data.get("outputs")
    if isinstance(outputs, list):
        for item in outputs:
            if not isinstance(item, dict):
                continue
            out = item.get("output") if isinstance(item.get("output"), dict) else item
            if isinstance(out, dict):
                st = str(out.get("exit_status") or "").strip()
                if st:
                    return st
    return ""


def is_max_iterations_reached(payload: dict[str, Any] | None) -> bool:
    data = payload if isinstance(payload, dict) else {}
    if data.get("max_iterations_reached") is True:
        return True
    nested = data.get("result")
    if isinstance(nested, dict) and nested.get("max_iterations_reached") is True:
        return True
    status = extract_exit_status(data)
    return status in {EXIT_MAX_ITERATIONS, EXIT_MAX_ROUNDS}


__all__ = [
    "EXIT_COMPLETED",
    "EXIT_LLM_ERROR",
    "EXIT_LLM_UNAVAILABLE",
    "EXIT_MAX_ITERATIONS",
    "EXIT_MAX_ROUNDS",
    "EXIT_STUCK_REPEATING",
    "EXIT_WALL_TIME",
    "FAILURE_EXIT_STATUSES",
    "extract_exit_status",
    "is_failure_exit_status",
    "is_max_iterations_reached",
    "is_success_exit_status",
]
