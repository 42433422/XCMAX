"""Compatibility facade delegating all risk semantics to autonomy_guard."""

from __future__ import annotations

import json
from typing import Any, cast

from app.domain.autonomy.autonomy_guard import get_autonomy_guard, reload_autonomy_guard


def load_risk_registry() -> dict[str, Any]:
    return get_autonomy_guard().registry_snapshot()


def invalidate_risk_registry_cache() -> None:
    reload_autonomy_guard()


def get_workflow_tools_from_registry() -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(json.dumps(load_risk_registry().get("tools") or {})))


def _resolve_action_spec(tool_id: str, action: str) -> dict[str, Any] | None:
    return get_autonomy_guard().get_action_spec(tool_id, action)


def get_action_risk(tool_id: str, action: str, *, default: str = "low") -> str:
    spec = _resolve_action_spec(tool_id, action)
    return str((spec or {}).get("risk") or default).lower()


def get_action_approval(tool_id: str, action: str) -> str | None:
    spec = _resolve_action_spec(tool_id, action)
    value = (spec or {}).get("approval")
    return str(value) if value else None


def requires_write_approval(tool_id: str, action: str = "execute") -> bool:
    return get_autonomy_guard().requires_write_approval(tool_id, action)


def requires_write_approval_for_spec(spec: dict[str, Any]) -> bool:
    return get_autonomy_guard().requires_write_approval_for_spec(spec)


def list_write_tools() -> frozenset[str]:
    return get_autonomy_guard().list_write_tools()


def list_code_write_tools() -> frozenset[str]:
    return get_autonomy_guard().list_code_write_tools()


__all__ = [
    "get_action_approval",
    "get_action_risk",
    "get_workflow_tools_from_registry",
    "invalidate_risk_registry_cache",
    "list_code_write_tools",
    "list_write_tools",
    "load_risk_registry",
    "requires_write_approval",
]
