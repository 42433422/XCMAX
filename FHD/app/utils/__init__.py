"""Utils package — lazy exports to avoid hard deps on import.

Importing ``app.utils.operational_errors`` (used by autonomy modules) must not
pull ``tenacity`` via ``retry``. Submodule access like
``from app.utils import metrics`` remains supported.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "format_money",
    "is_pro_source",
    "is_professional_mode",
    "route_normal_mode_message",
    "safe_float",
    "CircuitBreakerOpen",
    "circuit_breaker",
    "get_circuit_breaker",
    "get_logger",
    "log_operation",
    "setup_structured_logging",
    "init_metrics",
    "metrics_endpoint",
    "track_ai_request",
    "track_request_duration",
    "retry_ai_service",
    "retry_network_operation",
    "retry_on_exception",
]

_EXPORTS: dict[str, tuple[str, str]] = {
    "format_money": ("app.utils.ai_helpers", "format_money"),
    "is_pro_source": ("app.utils.ai_helpers", "is_pro_source"),
    "is_professional_mode": ("app.utils.ai_helpers", "is_professional_mode"),
    "route_normal_mode_message": ("app.utils.ai_helpers", "route_normal_mode_message"),
    "safe_float": ("app.utils.ai_helpers", "safe_float"),
    "CircuitBreakerOpen": ("app.utils.resilience.circuit_breaker", "CircuitBreakerOpen"),
    "circuit_breaker": ("app.utils.resilience.circuit_breaker", "circuit_breaker"),
    "get_circuit_breaker": ("app.utils.resilience.circuit_breaker", "get_circuit_breaker"),
    "get_logger": ("app.utils.logger", "get_logger"),
    "log_operation": ("app.utils.logger", "log_operation"),
    "setup_structured_logging": ("app.utils.logger", "setup_structured_logging"),
    "init_metrics": ("app.utils.metrics", "init_metrics"),
    "metrics_endpoint": ("app.utils.metrics", "metrics_endpoint"),
    "track_ai_request": ("app.utils.metrics", "track_ai_request"),
    "track_request_duration": ("app.utils.metrics", "track_request_duration"),
    "retry_ai_service": ("app.utils.resilience.retry", "retry_ai_service"),
    "retry_network_operation": ("app.utils.resilience.retry", "retry_network_operation"),
    "retry_on_exception": ("app.utils.resilience.retry", "retry_on_exception"),
}


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is not None:
        mod_name, attr = target
        value = getattr(import_module(mod_name), attr)
        globals()[name] = value
        return value
    if name.startswith("_"):
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    try:
        mod = import_module(f"{__name__}.{name}")
    except ModuleNotFoundError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    globals()[name] = mod
    return mod


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__, *_EXPORTS})
