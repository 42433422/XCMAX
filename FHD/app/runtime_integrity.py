"""Runtime integrity state shared by health, desktop status and release acceptance.

Startup code must report optional degradation and required component failures
here instead of merely logging a warning.  This keeps a packaged desktop app
from advertising a synthetic all-green state when routes or integrations are
missing from the bundle.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from fastapi import FastAPI

_ISSUE_LOCK = threading.Lock()
_PROCESS_ISSUES: dict[str, dict[str, Any]] = {}


def record_runtime_component(
    app: FastAPI,
    name: str,
    *,
    ok: bool,
    required: bool = False,
    detail: str = "",
) -> None:
    """Record the latest state of a startup/runtime component on the app."""
    components = dict(getattr(app.state, "runtime_components", {}) or {})
    components[name] = {
        "ok": bool(ok),
        "required": bool(required),
        "detail": str(detail or "").strip(),
    }
    app.state.runtime_components = components


def record_runtime_issue(
    key: str,
    detail: str,
    *,
    required: bool = False,
    ttl_seconds: float = 300.0,
) -> None:
    """Record a process-level issue that expires unless observed again."""
    with _ISSUE_LOCK:
        _PROCESS_ISSUES[key] = {
            "ok": False,
            "required": bool(required),
            "detail": str(detail or key).strip(),
            "expires_at": time.monotonic() + max(float(ttl_seconds), 1.0),
        }


def clear_runtime_issue(key: str) -> None:
    with _ISSUE_LOCK:
        _PROCESS_ISSUES.pop(key, None)


def _active_process_issues() -> dict[str, dict[str, Any]]:
    now = time.monotonic()
    with _ISSUE_LOCK:
        expired = [key for key, value in _PROCESS_ISSUES.items() if value["expires_at"] <= now]
        for key in expired:
            _PROCESS_ISSUES.pop(key, None)
        return {
            key: {k: v for k, v in value.items() if k != "expires_at"}
            for key, value in _PROCESS_ISSUES.items()
        }


def runtime_integrity_snapshot(app: FastAPI | None = None) -> dict[str, Any]:
    components: dict[str, dict[str, Any]] = {}
    if app is not None:
        components.update(dict(getattr(app.state, "runtime_components", {}) or {}))
    components.update(_active_process_issues())

    failures = [
        {"component": name, **value}
        for name, value in sorted(components.items())
        if not bool(value.get("ok"))
    ]
    blockers = [failure for failure in failures if bool(failure.get("required"))]
    status = "unhealthy" if blockers else "degraded" if failures else "healthy"
    return {
        "status": status,
        "components": components,
        "failures": failures,
        "blockers": blockers,
        "degraded_reasons": [
            str(failure.get("detail") or failure["component"]) for failure in failures
        ],
    }


def neuro_degraded_reasons(neuro: object) -> list[str]:
    """Extract user-actionable degradation from the Neuro/LLM health payload."""
    if not isinstance(neuro, dict) or neuro.get("enabled") is False:
        return []
    reasons: list[str] = []
    if neuro.get("error"):
        reasons.append("NEURO_HEALTH_UNAVAILABLE")
    if neuro.get("status") not in (None, "healthy"):
        reasons.append("NEURO_BUS_UNHEALTHY")
    if neuro.get("running") is False:
        reasons.append("NEURO_BUS_NOT_RUNNING")
    cognition = neuro.get("cognition")
    if isinstance(cognition, dict):
        cognition_state = cognition.get("cognition")
        if isinstance(cognition_state, dict) and cognition_state.get("llm_port_available") is False:
            reasons.append("LLM_RUNTIME_UNAVAILABLE")
        evolution = cognition.get("evolution")
        if isinstance(evolution, dict) and evolution.get("error"):
            reasons.append("NEURO_EVOLUTION_UNAVAILABLE")
    return list(dict.fromkeys(reasons))


# A missing process-wide LLM port is a capability fact. Desktop chat uses the
# signed-in account's model route, so this must not flip /api/health and
# /api/desktop/status to different degraded flags.
_NON_BLOCKING_NEURO_REASONS = frozenset({"LLM_RUNTIME_UNAVAILABLE"})


def llm_port_capability(neuro: object) -> dict[str, object] | None:
    """Report cognition.llm_port_available without treating it as process failure."""
    if not isinstance(neuro, dict) or neuro.get("enabled") is False:
        return None
    cognition = neuro.get("cognition")
    if not isinstance(cognition, dict):
        return None
    state = cognition.get("cognition")
    if not isinstance(state, dict) or "llm_port_available" not in state:
        return None
    ready = state.get("llm_port_available") is True
    return {"ready": ready, "status": "ready" if ready else "not_ready"}


def merge_public_degradation(payload: dict[str, Any], neuro: object) -> None:
    """Apply the same neuro degradation rules to health and desktop status."""
    reasons = [str(item) for item in payload.get("degradedReasons") or []]
    for reason in neuro_degraded_reasons(neuro):
        if reason not in _NON_BLOCKING_NEURO_REASONS:
            reasons.append(reason)
    payload["degradedReasons"] = list(dict.fromkeys(reasons))
    capability = llm_port_capability(neuro)
    if capability is not None:
        capabilities = dict(payload.get("capabilities") or {})
        capabilities["cognition.llm_port_available"] = capability
        payload["capabilities"] = capabilities
    runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
    blockers = runtime.get("blockers") if isinstance(runtime, dict) else None
    if blockers:
        payload["status"] = "unhealthy"
    elif payload["degradedReasons"]:
        if payload.get("status") != "unhealthy":
            payload["status"] = "degraded"
    elif payload.get("status") == "degraded" and isinstance(runtime, dict) and runtime.get("status") == "healthy":
        payload["status"] = "healthy"


__all__ = [
    "clear_runtime_issue",
    "llm_port_capability",
    "merge_public_degradation",
    "neuro_degraded_reasons",
    "record_runtime_component",
    "record_runtime_issue",
    "runtime_integrity_snapshot",
]
