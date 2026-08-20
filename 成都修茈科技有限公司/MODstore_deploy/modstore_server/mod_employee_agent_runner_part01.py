# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.mod_employee_agent_runner")


def _bounded_env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(str(_facade().os.environ.get(name) or default).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _default_max_rounds() -> int:
    return _facade()._bounded_env_int(
        "MODSTORE_EMPLOYEE_AGENT_MAX_ROUNDS", 4, minimum=1, maximum=10
    )


def _llm_timeout_seconds() -> float:
    return float(
        _facade()._bounded_env_int(
            "MODSTORE_EMPLOYEE_AGENT_LLM_TIMEOUT_SECONDS", 45, minimum=10, maximum=120
        )
    )
