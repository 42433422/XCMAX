"""Allocate a cloud Para route from verified platform-provider headroom."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from typing import Any

from modstore_server.llm_quota_monitor import platform_quota_snapshot
from modstore_server.para_coding_leaderboard import SOURCES, current_coding_scores
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.runtime_async import run_coro_sync

_MODEL_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}")


BASE_CAPABILITIES = frozenset({"responses_stream", "tool_calling", "token_usage"})


def select_route(
    providers: list[dict],
    routes: dict,
    reserve: int,
    *,
    required: frozenset[str] = BASE_CAPABILITIES,
    leaderboard: Callable[[str], tuple[str, dict[str, float]] | None] | None = None,
) -> dict[str, Any]:
    """Filter by verified capabilities and quota, then compare eligible models."""
    by_provider = {row["provider"]: row for row in providers}
    required = required | BASE_CAPABILITIES
    decision = {
        "status": "waiting",
        "reason": "no_capability_match",
        "required_capabilities": sorted(required),
        "reserve_percent": reserve,
    }
    eligible = []
    for model, route in routes.items():
        if not _MODEL_NAME.fullmatch(model) or not isinstance(route, dict):
            continue
        provider, resource = route.get("provider"), route.get("resource")
        capabilities = route.get("capabilities", [])
        if (
            not isinstance(provider, str)
            or not isinstance(resource, str)
            or not resource
            or not isinstance(capabilities, list)
            or any(not isinstance(value, str) for value in capabilities)
            or not required.issubset(capabilities)
        ):
            continue
        decision["reason"] = "no_verified_headroom"
        quota = by_provider.get(provider, {})
        if quota.get("visibility") != "exact" or quota.get("state") not in {
            "healthy",
            "warning",
        }:
            continue
        resources = {row["resource"]: row for row in quota.get("resources", [])}
        quota_rows = [resources.get(resource)]
        if resource != "general" and "general" in resources:
            quota_rows.append(resources["general"])
        percentages = [row.get("remaining_percent") if row else None for row in quota_rows]
        if any(type(value) is not int or not 0 <= value <= 100 for value in percentages):
            continue
        remaining = min(value for value in percentages if value is not None)
        if remaining <= reserve:
            continue
        eligible.append(
            {
                **decision,
                "status": "admitted",
                "reason": "verified_capability_and_quota",
                "model": model,
                "provider": provider,
                "resource": resource,
                "remaining_percent": remaining,
                "headroom_percent": remaining - reserve,
            }
        )
    if not eligible:
        return decision
    eligible.sort(key=lambda row: row["headroom_percent"], reverse=True)
    finalists = [
        row for row in eligible if row["headroom_percent"] == eligible[0]["headroom_percent"]
    ]
    references, points = _benchmark_preferences(finalists, routes, leaderboard)
    ranked = sorted(range(len(finalists)), key=points.__getitem__, reverse=True)
    winner = ranked[0]
    chosen = finalists[winner]
    return {
        **chosen,
        "selection": "coding_benchmarks" if references[winner] else "quota_then_config_order",
        "benchmarks": references[winner],
        "approved_models": [
            *(finalists[index]["model"] for index in ranked),
            *(row["model"] for row in eligible[len(finalists) :]),
        ],
    }


def _benchmark_preferences(finalists, routes, leaderboard):
    """Compare ranks only within a release that covers every tied candidate."""
    refs = [[] for _ in finalists]
    points = [0 for _ in finalists]
    if not leaderboard or len(finalists) < 2:
        return refs, points
    for source in SOURCES:
        mappings = [routes[row["model"]].get("benchmark_ids", {}) for row in finalists]
        ids = [mapping.get(source) if isinstance(mapping, dict) else None for mapping in mappings]
        if not all(isinstance(model_id, str) and model_id for model_id in ids):
            continue
        snapshot = leaderboard(source)
        if not snapshot:
            continue
        release, scores = snapshot
        if not all(model_id in scores for model_id in ids):
            continue
        cohort = [scores[model_id] for model_id in ids]
        for index, score in enumerate(cohort):
            points[index] += sum(score > other for other in cohort)
            refs[index].append({"source": source, "release": release, "score": score})
    return refs, points


def platform_model_admission(profile: str = "repair") -> dict[str, Any] | None:
    """Return None for existing deployments that have not opted in."""
    if os.environ.get("MODSTORE_PARA_PLATFORM_POOL") != "1":
        return None
    try:
        routes = json.loads(os.environ.get("MODSTORE_PARA_PLATFORM_ROUTES", "{}"))
        reserve = int(os.environ.get("MODSTORE_PARA_PLATFORM_RESERVE_PERCENT", "80"))
        profiles = json.loads(os.environ.get("MODSTORE_PARA_PLATFORM_CAPABILITY_PROFILES", "{}"))
        if not isinstance(profiles, dict):
            raise ValueError("invalid Para capability profiles")
        extra = profiles.get(profile, [])
        if not isinstance(extra, list) or any(not isinstance(value, str) for value in extra):
            raise ValueError("invalid Para capability requirements")
        if not isinstance(routes, dict) or not routes or not 80 <= reserve <= 100:
            raise ValueError("invalid Para platform policy")
    except ValueError:
        return {"status": "waiting", "reason": "invalid_platform_policy"}
    try:
        # Admission needs quota, not remote model discovery. Avoid opening the
        # process-wide catalog client's connections on this short-lived loop.
        from modstore_server.llm_key_resolver import platform_api_key

        providers = {
            route.get("provider")
            for route in routes.values()
            if isinstance(route, dict) and isinstance(route.get("provider"), str)
        }
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
    decision = select_route(
        snapshot.get("providers", []),
        routes,
        reserve,
        required=frozenset(extra),
        leaderboard=current_coding_scores,
    )
    return {**decision, "checked_at": snapshot.get("checked_at"), "profile": profile}
