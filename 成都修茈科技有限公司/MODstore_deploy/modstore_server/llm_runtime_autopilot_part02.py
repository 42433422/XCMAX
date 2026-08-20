# mypy: disable-error-code="attr-defined, no-any-return, union-attr, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.llm_runtime_autopilot")


async def reconcile_llm_route_autopilot(
    *, triggered_by: str = "manual", force: bool = False
) -> dict[str, _facade().Any]:
    """Probe the effective route and automatically move away from hard failure/quota exhaustion."""
    event: dict[str, _facade().Any] = {
        "ok": True,
        "checked_at": _facade()._now_iso(),
        "triggered_by": str(triggered_by or "manual")[:64],
        "enabled": _facade().autopilot_enabled(),
        "action": "noop",
        "policy": {
            "failure_threshold": _facade()._failure_threshold(),
            "minimum_residence_seconds": _facade()._minimum_residence_seconds(),
            "max_candidate_probes": _facade()._max_candidate_probes(),
        },
    }
    if not event["enabled"] and (not force):
        event.update({"action": "disabled", "reason": "autopilot_disabled"})
        return _facade()._record(event)
    from modstore_server.llm_quota_monitor import (
        classify_probe_result,
        platform_quota_snapshot,
    )
    from modstore_server.llm_runtime_route import (
        current_runtime_route,
        platform_model_catalog,
        probe_runtime_route,
        rollback_runtime_route,
        switch_runtime_route,
    )
    from modstore_server.services.llm import resolve_platform_bench_llm

    persisted_current = current_runtime_route()
    expected_revision = (
        str(persisted_current.get("revision") or "") if isinstance(persisted_current, dict) else ""
    )
    try:
        catalog = await platform_model_catalog(refresh=False)
        quota = await platform_quota_snapshot(live_probe=False, catalog=catalog)
    except _facade().BOUNDARY_ERRORS as exc:
        event.update(
            {
                "ok": False,
                "action": "observation_failed",
                "reason": f"{type(exc).__name__}: {exc}",
            }
        )
        return _facade()._record(event)
    quota_map = _facade()._quota_by_provider(quota)
    current_provider, current_model = resolve_platform_bench_llm()
    current = {"provider": current_provider, "model": current_model}
    event["current"] = current
    event["quota"] = {
        provider: {
            "state": row.get("state"),
            "visibility": row.get("visibility"),
            "remaining_percent": row.get("remaining_percent"),
        }
        for (provider, row) in quota_map.items()
    }
    current_quota = quota_map.get(str(current_provider or "")) or {}
    quota_state = str(current_quota.get("state") or "")
    current_probe = current_quota.get("probe") if isinstance(current_quota, dict) else None
    if quota_state in {"exhausted", "warning"}:
        current_probe = {
            "ok": False,
            "status": 429,
            "error": f"exact quota state: {quota_state}",
        }
    if not isinstance(current_probe, dict) and current_provider and current_model:
        current_probe = await probe_runtime_route(current_provider, current_model)
    current_probe = (
        current_probe
        if isinstance(current_probe, dict)
        else {"ok": False, "error": "no effective platform route"}
    )
    current_state = classify_probe_result(current_probe)
    if quota_state == "exhausted":
        current_state = "exhausted"
    elif quota_state == "warning":
        current_state = "warning"
    event["current_health"] = {
        "state": current_state,
        "ok": bool(current_probe.get("ok")),
        "status": current_probe.get("status"),
        "error": str(current_probe.get("error") or "")[:300],
    }
    if current_state == "healthy":
        event.update({"action": "kept", "reason": "current_route_healthy"})
        return _facade()._record(event)
    if current_state == "warning":
        event.update({"action": "kept_warning", "reason": "transient_rate_limit"})
        return _facade()._record(event)
    if current_state == "error":
        consecutive_failures = (
            _facade()._consecutive_route_errors(
                str(current_provider or ""), str(current_model or "")
            )
            + 1
        )
        event["current_health"]["consecutive_failures"] = consecutive_failures
        if consecutive_failures < _facade()._failure_threshold() and (not force):
            event.update({"action": "observed_unhealthy", "reason": "failure_threshold_not_met"})
            return _facade()._record(event)
    residence_seconds = _facade()._route_residence_seconds(persisted_current)
    if residence_seconds is not None:
        event["current"]["residence_seconds"] = round(residence_seconds, 3)
    if (
        current_state != "exhausted"
        and residence_seconds is not None
        and (residence_seconds < _facade()._minimum_residence_seconds())
        and (not force)
    ):
        event.update({"action": "observed_unhealthy", "reason": "minimum_residence_not_met"})
        return _facade()._record(event)
    blocks = {
        str(row.get("provider") or ""): row
        for row in catalog.get("providers") or []
        if isinstance(row, dict) and row.get("configured")
    }
    provider_order = [*dict.fromkeys([*_facade()._provider_order(), *blocks.keys()])]
    attempts: list[dict[str, _facade().Any]] = []
    selected: _facade().Optional[tuple[str, str]] = None
    probe_count = 0
    probe_limit_reached = False
    for provider in provider_order:
        block = blocks.get(provider)
        if not block:
            continue
        provider_quota = quota_map.get(provider) or {}
        if provider_quota.get("state") == "exhausted":
            attempts.append(
                {
                    "provider": provider,
                    "model": "",
                    "ok": False,
                    "reason": "quota_exhausted",
                }
            )
            continue
        for model in _facade()._ordered_models(provider, list(block.get("runtime_models") or [])):
            if provider == current_provider and model == current_model:
                continue
            if probe_count >= _facade()._max_candidate_probes():
                probe_limit_reached = True
                break
            probe_count += 1
            probe = await probe_runtime_route(provider, model)
            attempt_state = classify_probe_result(probe)
            attempts.append(
                {
                    "provider": provider,
                    "model": model,
                    "ok": bool(probe.get("ok")),
                    "state": attempt_state,
                    "status": probe.get("status"),
                    "error": str(probe.get("error") or "")[:240],
                }
            )
            if probe.get("ok"):
                selected = (provider, model)
                break
        if selected:
            break
        if probe_limit_reached:
            break
    event["attempts"] = attempts
    event["candidate_probe_count"] = probe_count
    if not selected:
        event.update(
            {
                "ok": False,
                "action": "degraded_no_candidate",
                "reason": f"current_{current_state}_and_no_healthy_api_route",
                "cli_fallback_available": True,
            }
        )
        return _facade()._record(event)
    target_provider, target_model = selected
    switched = await switch_runtime_route(
        target_provider,
        target_model,
        actor="llm-ops-engineer/autopilot",
        reason=f"autopilot: current route {current_state}; trigger={triggered_by}",
        refresh_catalog=False,
        force=False,
        expected_revision=expected_revision,
    )
    event["switch"] = switched
    if not switched.get("ok"):
        if switched.get("conflict") or switched.get("error") == "route_revision_conflict":
            event.update(
                {
                    "action": "concurrent_change_detected",
                    "reason": "route_revision_conflict",
                }
            )
        else:
            event.update(
                {
                    "ok": False,
                    "action": "switch_failed",
                    "reason": switched.get("error"),
                }
            )
        return _facade()._record(event)
    post_probe = await probe_runtime_route(target_provider, target_model)
    event["post_switch_health"] = post_probe
    if not post_probe.get("ok"):
        switched_current = (
            switched.get("current") if isinstance(switched.get("current"), dict) else {}
        )
        switched_event = switched.get("event") if isinstance(switched.get("event"), dict) else {}
        switched_revision = str(
            switched_current.get("revision") or switched_event.get("revision") or ""
        )
        rollback = await rollback_runtime_route(
            actor="llm-ops-engineer/autopilot",
            reason="post-switch health verification failed",
            force=True,
            expected_revision=switched_revision,
        )
        event["rollback"] = rollback
        if rollback.get("ok"):
            event.update(
                {
                    "ok": False,
                    "action": "rolled_back",
                    "reason": "post_switch_health_failed",
                }
            )
        else:
            event.update(
                {
                    "ok": False,
                    "action": "rollback_failed",
                    "reason": rollback.get("error") or "post_switch_health_failed",
                }
            )
        return _facade()._record(event)
    event.update(
        {
            "action": "switched",
            "reason": f"current_{current_state}",
            "target": {"provider": target_provider, "model": target_model},
        }
    )
    return _facade()._record(event)


def run_llm_route_autopilot(
    *, triggered_by: str = "scheduler", force: bool = False
) -> dict[str, _facade().Any]:
    return _facade().asyncio.run(
        _facade().reconcile_llm_route_autopilot(triggered_by=triggered_by, force=force)
    )
