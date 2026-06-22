"""Incident-aware LLM model routing.

The router maps incident type/scope/role to provider/model with a simple
cost-capability-success tradeoff. Operators can override all defaults with
``MODSTORE_INCIDENT_MODEL_ROUTE_JSON``.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Tuple


def _load_route_json() -> Dict[str, Any]:
    raw = (os.environ.get("MODSTORE_INCIDENT_MODEL_ROUTE_JSON") or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _route_from_env(prefix: str) -> Dict[str, str]:
    provider = (os.environ.get(f"{prefix}_PROVIDER") or "").strip()
    model = (os.environ.get(f"{prefix}_MODEL") or "").strip()
    if provider and model and provider.lower() != "auto" and model.lower() != "auto":
        return {"provider": provider, "model": model}
    return {}


def _payload_scope(payload: Dict[str, Any]) -> str:
    return str(payload.get("scope") or payload.get("source_scope") or "").strip().lower()


def route_for_incident(
    *,
    event_type: str,
    payload: Dict[str, Any],
    role: str = "",
) -> Dict[str, Any]:
    routes = _load_route_json()
    scope = _payload_scope(payload)
    role_key = str(role or "").strip().lower()
    keys = [
        f"{event_type}:{scope}:{role_key}",
        f"{event_type}:{scope}",
        f"{event_type}:{role_key}",
        str(event_type or ""),
        f"scope:{scope}",
        f"role:{role_key}",
    ]
    for key in keys:
        row = routes.get(key)
        if isinstance(row, dict) and row.get("provider") and row.get("model"):
            return {
                "model": str(row.get("model")),
                "provider": str(row.get("provider")),
                "reason": f"route_json:{key}",
                "role": role_key,
            }

    et = str(event_type or "").lower()
    if role_key == "verify":
        route = _route_from_env("MODSTORE_INCIDENT_MODEL_VERIFY")
        if route:
            return {**route, "reason": "verify_route", "role": role_key}
    if role_key == "fix" or et in {"security.alert", "ci.failed", "on_quality_fail"}:
        route = _route_from_env("MODSTORE_INCIDENT_MODEL_HIGH")
        if route:
            return {**route, "reason": "high_capability_route", "role": role_key}
    route = _route_from_env("MODSTORE_INCIDENT_MODEL_LOW")
    if route:
        return {**route, "reason": "low_cost_route", "role": role_key}
    return {"model": "auto", "provider": "auto", "reason": "executor_auto", "role": role_key}


def bench_override_for_route(route: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    provider = str(route.get("provider") or "").strip()
    model = str(route.get("model") or "").strip()
    if not provider or not model or provider.lower() == "auto" or model.lower() == "auto":
        return None
    return provider, model


__all__ = ["bench_override_for_route", "route_for_incident"]
