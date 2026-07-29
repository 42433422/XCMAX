"""Fail-closed handler selection for reviewed duty burn-in executions."""

from __future__ import annotations

from typing import Any, Dict, Iterable


def select_reviewed_burn_in_handlers(
    actions: Dict[str, Any],
    handlers: list[str],
    *,
    dangerous_handlers: Iterable[str],
    capability_handlers: Iterable[str],
) -> Dict[str, Any]:
    """Select the narrow burn-in handler set without changing normal runtime."""

    dangerous_set = set(dangerous_handlers)
    capability_set = set(capability_handlers)
    raw = actions.get("burn_in_handlers")
    explicit = raw is not None
    if explicit and not isinstance(raw, list):
        return {
            "error": {
                "eligible": False,
                "reason": "burn_in_handlers_invalid",
                "handlers": handlers,
            }
        }
    selected = (
        [str(item).strip() for item in raw or [] if isinstance(item, str) and str(item).strip()]
        if explicit
        else handlers
    )
    unsupported = sorted(set(selected) - capability_set) if explicit else []
    if unsupported:
        return {
            "error": {
                "eligible": False,
                "reason": "unsupported_burn_in_handler:" + ",".join(unsupported),
                "handlers": handlers,
                "burn_in_handlers": selected,
            }
        }
    dangerous = sorted((set(handlers) | set(selected)) & dangerous_set)
    if dangerous:
        return {
            "error": {
                "eligible": False,
                "reason": "dangerous_handler:" + ",".join(dangerous),
                "handlers": handlers,
            }
        }
    executable = sorted(set(selected) & capability_set)
    if not executable:
        return {
            "error": {
                "eligible": False,
                "reason": "no_safe_executable_handler",
                "handlers": handlers,
            }
        }
    return {
        "capability_handlers": executable,
        "burn_in_handlers_explicit": explicit,
    }


def bind_reviewed_burn_in_handlers(
    config: Dict[str, Any],
    eligibility: Dict[str, Any],
) -> Dict[str, Any]:
    """Bind an eligible explicit burn-in to its reviewed handler set."""

    if not (
        eligibility.get("eligible") is True and eligibility.get("burn_in_handlers_explicit") is True
    ):
        return config
    selected = [
        str(item).strip()
        for item in eligibility.get("capability_handlers") or []
        if isinstance(item, str) and str(item).strip()
    ]
    if not selected:
        raise RuntimeError("reviewed burn-in has no executable handlers")

    bound = dict(config)
    actions = dict(bound.get("actions")) if isinstance(bound.get("actions"), dict) else {}
    if isinstance(actions.get("actions"), dict):
        nested = dict(actions["actions"])
        nested["handlers"] = selected
        actions["actions"] = nested
    else:
        actions["handlers"] = selected
    bound["actions"] = actions
    return bound
