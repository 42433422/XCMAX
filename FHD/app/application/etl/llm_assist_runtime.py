"""Configuration, result value and outage circuit for ETL LLM assistance."""

from __future__ import annotations

import os
import threading
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

_CIRCUIT_LOCK = threading.Lock()
_CIRCUIT_OPEN_UNTIL: dict[str, tuple[float, str]] = {}
_OWNER_CALL_LOCKS: dict[str, threading.Lock] = {}
_REQUEST_LLM_ENABLED: ContextVar[bool] = ContextVar("etl_request_llm_enabled", default=True)


@dataclass(slots=True)
class LlmAssistResult:
    used_llm: bool = False
    degraded: bool = False
    degradation_code: str = ""
    model: str = ""
    billing: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)

    def public_metadata(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "used_llm": self.used_llm,
            "advisory_only": True,
            "degraded": self.degraded,
        }
        if self.degradation_code:
            result["degradation_code"] = self.degradation_code
        if self.model:
            result["model"] = self.model
        if self.billing:
            result["billing"] = dict(self.billing)
        return result


def etl_llm_mode() -> str:
    if not _REQUEST_LLM_ENABLED.get():
        return "off"
    raw = str(os.environ.get("FHD_ETL_LLM") or "auto").strip().lower()
    if raw in {"0", "false", "no", "off", "disabled"}:
        return "off"
    if raw in {"1", "true", "yes", "on", "enabled"}:
        return "on"
    return "auto"


def bind_request_llm_enabled(enabled: bool) -> Token[bool]:
    return _REQUEST_LLM_ENABLED.set(bool(enabled))


def reset_request_llm_enabled(token: Token[bool]) -> None:
    _REQUEST_LLM_ENABLED.reset(token)


def etl_llm_timeout_seconds() -> float:
    raw = str(os.environ.get("FHD_ETL_LLM_TIMEOUT") or "30").strip()
    try:
        return min(60.0, max(1.0, float(raw)))
    except ValueError:
        return 30.0


def etl_row_advice_limit() -> int:
    raw = str(os.environ.get("FHD_ETL_LLM_ROW_ADVICE_LIMIT") or "20").strip()
    try:
        return min(100, max(0, int(raw)))
    except ValueError:
        return 20


def degradation_code(exc: BaseException) -> str:
    message = str(exc).lower()
    if "quota exhausted" in message or "额度" in message or "429" in message:
        return "ETL_LLM_QUOTA_EXHAUSTED"
    return "ETL_LLM_UNAVAILABLE"


def circuit_key() -> str:
    try:
        from app.application.etl.llm_session_provider import current_etl_llm_owner

        owner_user_id = current_etl_llm_owner()
    except RECOVERABLE_ERRORS:
        owner_user_id = None
    return f"owner:{owner_user_id}" if owner_user_id is not None else "process"


def circuit_cooldown_seconds(code: str) -> float:
    env_name = (
        "FHD_ETL_LLM_QUOTA_COOLDOWN_SECONDS"
        if code == "ETL_LLM_QUOTA_EXHAUSTED"
        else "FHD_ETL_LLM_FAILURE_COOLDOWN_SECONDS"
    )
    default = 300.0 if code == "ETL_LLM_QUOTA_EXHAUSTED" else 30.0
    raw = str(os.environ.get(env_name) or default).strip()
    try:
        return min(3600.0, max(1.0, float(raw)))
    except ValueError:
        return default


def circuit_degradation(key: str) -> str:
    now = time.monotonic()
    with _CIRCUIT_LOCK:
        state = _CIRCUIT_OPEN_UNTIL.get(key)
        if state is None:
            return ""
        expires_at, code = state
        if expires_at <= now:
            _CIRCUIT_OPEN_UNTIL.pop(key, None)
            return ""
        return code


def open_circuit(key: str, code: str) -> None:
    with _CIRCUIT_LOCK:
        _CIRCUIT_OPEN_UNTIL[key] = (
            time.monotonic() + circuit_cooldown_seconds(code),
            code,
        )


def owner_call_lock(key: str) -> threading.Lock:
    with _CIRCUIT_LOCK:
        lock = _OWNER_CALL_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _OWNER_CALL_LOCKS[key] = lock
        return lock


def clear_etl_llm_circuit() -> None:
    with _CIRCUIT_LOCK:
        _CIRCUIT_OPEN_UNTIL.clear()
