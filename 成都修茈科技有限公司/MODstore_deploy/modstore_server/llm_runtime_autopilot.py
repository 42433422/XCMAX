"""Active health/quota loop for the platform-funded AI employee route."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_LOCK = threading.Lock()
_MAX_LEDGER_LINES = 500


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def autopilot_enabled() -> bool:
    # Fail closed in every environment. Production must opt in explicitly.
    return _env_bool("MODSTORE_LLM_AUTOPILOT_ENABLED", False)


def _failure_threshold() -> int:
    return max(1, _env_int("MODSTORE_LLM_AUTOPILOT_FAILURE_THRESHOLD", 3))


def _minimum_residence_seconds() -> int:
    return max(0, _env_int("MODSTORE_LLM_AUTOPILOT_MIN_RESIDENCE_SECONDS", 900))


def _max_candidate_probes() -> int:
    return max(1, min(_env_int("MODSTORE_LLM_AUTOPILOT_MAX_CANDIDATE_PROBES", 4), 20))


def autopilot_ledger_path() -> Path:
    root = (
        os.environ.get("MODSTORE_RUNTIME_DIR")
        or os.environ.get("MODSTORE_DATA_DIR")
        or "/tmp/modstore_data"
    )
    return Path(root).expanduser().resolve() / "llm" / "route_autopilot.jsonl"


def _secret_safe(value: Any) -> Any:
    from modstore_server.llm_quota_monitor import scrub_llm_error

    if isinstance(value, dict):
        return {str(key): _secret_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_secret_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_secret_safe(item) for item in value]
    if isinstance(value, str):
        return scrub_llm_error(value)
    return value


def _read_audit_events() -> list[dict[str, Any]]:
    path = autopilot_ledger_path()
    if not path.is_file():
        return []
    try:
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError):
        return []
    return [row for row in rows if isinstance(row, dict)][-_MAX_LEDGER_LINES:]


def _write_audit(event: dict[str, Any]) -> None:
    event = _secret_safe(event)
    path = autopilot_ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        lines: list[str] = []
        if path.is_file():
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                lines = []
        lines.append(json.dumps(event, ensure_ascii=False, sort_keys=True))
        lines = lines[-_MAX_LEDGER_LINES:]
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp, path)


def _record(event: dict[str, Any]) -> dict[str, Any]:
    safe_event = _secret_safe(event)
    _write_audit(safe_event)
    return safe_event


def _consecutive_route_errors(provider: str, model: str) -> int:
    count = 0
    for row in reversed(_read_audit_events()):
        current = row.get("current") if isinstance(row.get("current"), dict) else {}
        health = (
            row.get("current_health")
            if isinstance(row.get("current_health"), dict)
            else {}
        )
        if (
            str(current.get("provider") or "") != provider
            or str(current.get("model") or "") != model
            or str(health.get("state") or "") != "error"
        ):
            break
        count += 1
    return count


def _route_residence_seconds(current: dict[str, Any] | None) -> float | None:
    if not isinstance(current, dict):
        return None
    raw = str(current.get("switched_at") or "").strip()
    if not raw:
        return None
    try:
        switched_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if switched_at.tzinfo is None:
            switched_at = switched_at.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - switched_at).total_seconds())
    except ValueError:
        return None


def autopilot_status() -> dict[str, Any]:
    path = autopilot_ledger_path()
    if not path.is_file():
        return {
            "ok": True,
            "enabled": autopilot_enabled(),
            "last_run": None,
            "ledger_path": str(path),
            "policy": {
                "failure_threshold": _failure_threshold(),
                "minimum_residence_seconds": _minimum_residence_seconds(),
                "max_candidate_probes": _max_candidate_probes(),
            },
        }
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
        last = _secret_safe(json.loads(lines[-1])) if lines else None
    except (OSError, json.JSONDecodeError):
        last = None
    return {
        "ok": True,
        "enabled": autopilot_enabled(),
        "last_run": last,
        "ledger_path": str(path),
        "policy": {
            "failure_threshold": _failure_threshold(),
            "minimum_residence_seconds": _minimum_residence_seconds(),
            "max_candidate_probes": _max_candidate_probes(),
        },
    }


def _provider_order() -> list[str]:
    raw = os.environ.get(
        "MODSTORE_LLM_AUTOPILOT_PROVIDER_ORDER",
        "minimax,xiaomi,deepseek,openai,anthropic,google,"
        "siliconflow,dashscope,moonshot,openrouter,groq,together",
    )
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def _ordered_models(provider: str, models: list[str]) -> list[str]:
    from modstore_server.services.llm import _BENCH_DEFAULT_MODELS

    preferred = str(_BENCH_DEFAULT_MODELS.get(provider) or "")
    unique = list(dict.fromkeys(str(model) for model in models if str(model)))
    if preferred in unique:
        return [preferred, *[model for model in unique if model != preferred]]
    return unique


def _quota_by_provider(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("provider") or ""): row
        for row in snapshot.get("providers") or []
        if isinstance(row, dict) and str(row.get("provider") or "")
    }


async def reconcile_llm_route_autopilot(
    *,
    triggered_by: str = "manual",
    force: bool = False,
) -> dict[str, Any]:
    """Probe the effective route and automatically move away from hard failure/quota exhaustion."""

    event: dict[str, Any] = {
        "ok": True,
        "checked_at": _now_iso(),
        "triggered_by": str(triggered_by or "manual")[:64],
        "enabled": autopilot_enabled(),
        "action": "noop",
        "policy": {
            "failure_threshold": _failure_threshold(),
            "minimum_residence_seconds": _minimum_residence_seconds(),
            "max_candidate_probes": _max_candidate_probes(),
        },
    }
    if not event["enabled"] and not force:
        event.update({"action": "disabled", "reason": "autopilot_disabled"})
        return _record(event)

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
        str(persisted_current.get("revision") or "")
        if isinstance(persisted_current, dict)
        else ""
    )
    try:
        catalog = await platform_model_catalog(refresh=False)
        # Read exact quota without probing every configured provider. Only the
        # effective route (and, on failure, bounded candidates) receives a real
        # model request, so an almost exhausted fallback is not burned every
        # five minutes merely for observation.
        quota = await platform_quota_snapshot(live_probe=False, catalog=catalog)
    except Exception as exc:  # noqa: BLE001
        event.update(
            {
                "ok": False,
                "action": "observation_failed",
                "reason": f"{type(exc).__name__}: {exc}",
            }
        )
        return _record(event)
    quota_map = _quota_by_provider(quota)
    current_provider, current_model = resolve_platform_bench_llm()
    current = {
        "provider": current_provider,
        "model": current_model,
    }
    event["current"] = current
    event["quota"] = {
        provider: {
            "state": row.get("state"),
            "visibility": row.get("visibility"),
            "remaining_percent": row.get("remaining_percent"),
        }
        for provider, row in quota_map.items()
    }

    current_quota = quota_map.get(str(current_provider or "")) or {}
    quota_state = str(current_quota.get("state") or "")
    current_probe = (
        current_quota.get("probe") if isinstance(current_quota, dict) else None
    )
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
        else {
            "ok": False,
            "error": "no effective platform route",
        }
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
        return _record(event)

    # A generic 429 is rate pressure, not proof of quota exhaustion. Switching
    # on it creates provider thrash, so record it and retry on the next cadence.
    if current_state == "warning":
        event.update({"action": "kept_warning", "reason": "transient_rate_limit"})
        return _record(event)

    if current_state == "error":
        consecutive_failures = (
            _consecutive_route_errors(
                str(current_provider or ""), str(current_model or "")
            )
            + 1
        )
        event["current_health"]["consecutive_failures"] = consecutive_failures
        if consecutive_failures < _failure_threshold() and not force:
            event.update(
                {
                    "action": "observed_unhealthy",
                    "reason": "failure_threshold_not_met",
                }
            )
            return _record(event)

    residence_seconds = _route_residence_seconds(persisted_current)
    if residence_seconds is not None:
        event["current"]["residence_seconds"] = round(residence_seconds, 3)
    if (
        current_state != "exhausted"
        and residence_seconds is not None
        and residence_seconds < _minimum_residence_seconds()
        and not force
    ):
        event.update(
            {
                "action": "observed_unhealthy",
                "reason": "minimum_residence_not_met",
            }
        )
        return _record(event)

    blocks = {
        str(row.get("provider") or ""): row
        for row in catalog.get("providers") or []
        if isinstance(row, dict) and row.get("configured")
    }
    provider_order = [*dict.fromkeys([*_provider_order(), *blocks.keys()])]
    attempts: list[dict[str, Any]] = []
    selected: Optional[tuple[str, str]] = None
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
        for model in _ordered_models(provider, list(block.get("runtime_models") or [])):
            if provider == current_provider and model == current_model:
                continue
            if probe_count >= _max_candidate_probes():
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
        return _record(event)

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
        if (
            switched.get("conflict")
            or switched.get("error") == "route_revision_conflict"
        ):
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
        return _record(event)

    post_probe = await probe_runtime_route(target_provider, target_model)
    event["post_switch_health"] = post_probe
    if not post_probe.get("ok"):
        switched_current = (
            switched.get("current") if isinstance(switched.get("current"), dict) else {}
        )
        switched_event = (
            switched.get("event") if isinstance(switched.get("event"), dict) else {}
        )
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
        return _record(event)

    event.update(
        {
            "action": "switched",
            "reason": f"current_{current_state}",
            "target": {"provider": target_provider, "model": target_model},
        }
    )
    return _record(event)


def run_llm_route_autopilot(
    *,
    triggered_by: str = "scheduler",
    force: bool = False,
) -> dict[str, Any]:
    return asyncio.run(
        reconcile_llm_route_autopilot(triggered_by=triggered_by, force=force)
    )


__all__ = [
    "autopilot_enabled",
    "autopilot_ledger_path",
    "autopilot_status",
    "reconcile_llm_route_autopilot",
    "run_llm_route_autopilot",
]
