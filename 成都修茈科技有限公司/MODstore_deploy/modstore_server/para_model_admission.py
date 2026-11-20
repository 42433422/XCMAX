"""Allocate a cloud Para route from verified platform-provider headroom."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from modstore_server.llm_quota_monitor import platform_quota_snapshot
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.runtime_async import run_coro_sync

_MODEL_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}")


def select_route(providers: list[dict], routes: dict, reserve: int) -> dict[str, Any]:
    """Choose the route with the most spare quota, in configured order for ties."""
    by_provider = {row["provider"]: row for row in providers}
    selected = {"status": "waiting", "reason": "no_verified_headroom", "reserve_percent": reserve}
    best_headroom = 0
    for model, route in routes.items():
        if not _MODEL_NAME.fullmatch(model) or not isinstance(route, dict):
            continue
        provider, resource = route.get("provider"), route.get("resource")
        if not isinstance(provider, str) or not isinstance(resource, str) or not resource:
            continue
        quota = by_provider.get(provider, {})
        if quota.get("visibility") != "exact" or quota.get("state") not in {"healthy", "warning"}:
            continue
        resources = {row["resource"]: row for row in quota.get("resources", [])}
        required = [resources.get(resource)]
        if resource != "general" and "general" in resources:
            required.append(resources["general"])
        percentages = [row.get("remaining_percent") if row else None for row in required]
        if any(type(value) is not int or not 0 <= value <= 100 for value in percentages):
            continue
        remaining = min(value for value in percentages if value is not None)
        if remaining - reserve > best_headroom:
            best_headroom = remaining - reserve
            selected = {
                "status": "admitted",
                "model": model,
                "provider": provider,
                "resource": resource,
                "remaining_percent": remaining,
                "reserve_percent": reserve,
                "headroom_percent": best_headroom,
            }
    return selected


def platform_model_admission() -> dict[str, Any] | None:
    """Return None for existing deployments that have not opted in."""
    if os.environ.get("MODSTORE_PARA_PLATFORM_POOL") != "1":
        return None
    try:
        routes = json.loads(os.environ.get("MODSTORE_PARA_PLATFORM_ROUTES", "{}"))
        reserve = int(os.environ.get("MODSTORE_PARA_PLATFORM_RESERVE_PERCENT", "80"))
        if not isinstance(routes, dict) or not routes or not 80 <= reserve <= 100:
            raise ValueError("invalid Para platform policy")
    except ValueError:
        return {"status": "waiting", "reason": "invalid_platform_policy"}
    try:
        # Admission needs quota, not remote model discovery. Avoid opening the
        # process-wide catalog client's connections on this short-lived loop.
        from modstore_server.llm_key_resolver import platform_api_key

        providers: set[str] = set()
        for route in routes.values():
            if isinstance(route, dict):
                provider = route.get("provider")
                if isinstance(provider, str):
                    providers.add(provider)
        catalog = {
            "providers": [
                {"provider": provider, "configured": bool(platform_api_key(provider))}
                for provider in sorted(providers)
            ]
        }
        snapshot = run_coro_sync(
            platform_quota_snapshot(live_probe=False, catalog=catalog, isolated_http=True)
        )
    except RECOVERABLE_ERRORS:
        return {"status": "waiting", "reason": "platform_quota_unavailable"}
    decision = select_route(snapshot.get("providers", []), routes, reserve)
    return {**decision, "checked_at": snapshot.get("checked_at")}
