# mypy: disable-error-code="union-attr"
"""Unified, secret-safe quota and usage snapshots for platform LLM routes."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlsplit

from sqlalchemy import case, func

from modstore_server.llm_key_resolver import (
    is_minimax_token_plan_key,
    normalize_minimax_api_key,
    platform_api_key,
    platform_base_url,
)
from modstore_server.operational_errors import BOUNDARY_ERRORS

_BEARER_RE = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}")
_API_KEY_RE = re.compile(r"(?i)\b(?:sk|tp)-[a-z0-9_-]{8,}")
_ASSIGNED_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|token|secret|password)"
    r"(\s*[:=]\s*)[\"']?([^\s,;\"'}]+)"
)


def scrub_llm_error(value: Any) -> str:
    """Remove credential-shaped values before errors reach APIs or ledgers."""

    text = str(value or "")
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _API_KEY_RE.sub("[REDACTED]", text)
    return _ASSIGNED_SECRET_RE.sub(r"\1\2[REDACTED]", text)


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _minimax_remains_url(base_url: Optional[str] = None) -> str:
    explicit = (os.environ.get("MINIMAX_TOKEN_PLAN_REMAINS_URL") or "").strip()
    if explicit:
        return explicit
    base = str(base_url or platform_base_url("minimax") or "").strip()
    parsed = urlsplit(base if "://" in base else f"//{base}")
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if hostname == "minimaxi.com" or hostname.endswith(".minimaxi.com"):
        return "https://www.minimaxi.com/v1/token_plan/remains"
    return "https://www.minimax.io/v1/token_plan/remains"


def _quota_state(remaining_percent: Optional[int]) -> str:
    if remaining_percent is None:
        return "unknown"
    if remaining_percent <= 0:
        return "exhausted"
    warning_percent = max(1, min(_env_int("MODSTORE_LLM_QUOTA_WARNING_PERCENT", 15), 99))
    return "warning" if remaining_percent <= warning_percent else "healthy"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _bounded_percent(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return max(0, min(int(float(value)), 100))
    except (TypeError, ValueError):
        return None


def _remaining_from_counts(usage: Any, total: Any) -> int | None:
    total_count = _safe_int(total)
    if total_count <= 0:
        return None
    usage_count = max(0, _safe_int(usage))
    return max(0, min(round((total_count - usage_count) * 100 / total_count), 100))


def _status_is_exhausted(value: Any) -> bool:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return normalized in {
        "exhausted",
        "depleted",
        "used_up",
        "unavailable",
        "disabled",
        "inactive",
    }


def parse_minimax_token_plan_remains(payload: Any) -> dict[str, Any]:
    """Normalize MiniMax's official ``token_plan/remains`` response."""

    envelope = payload if isinstance(payload, dict) else {}
    nested = envelope.get("data") if isinstance(envelope.get("data"), dict) else None
    data = nested or envelope
    base_resp = (
        envelope.get("base_resp")
        if isinstance(envelope.get("base_resp"), dict)
        else data.get("base_resp") if isinstance(data.get("base_resp"), dict) else {}
    )
    status_code = _safe_int(base_resp.get("status_code"))
    if status_code:
        return {
            "state": "error",
            "visibility": "exact",
            "error_code": status_code,
            "error": scrub_llm_error(base_resp.get("status_msg") or "quota api error")[:300],
            "resources": [],
            "remaining_percent": None,
        }

    resources: list[dict[str, Any]] = []
    for row in data.get("model_remains") or []:
        if not isinstance(row, dict):
            continue
        interval_usage = _safe_int(row.get("current_interval_usage_count"))
        interval_total = _safe_int(row.get("current_interval_total_count"))
        weekly_usage = _safe_int(row.get("current_weekly_usage_count"))
        weekly_total = _safe_int(row.get("current_weekly_total_count"))
        interval_percent = _bounded_percent(row.get("current_interval_remaining_percent"))
        weekly_percent = _bounded_percent(row.get("current_weekly_remaining_percent"))
        if interval_percent is None:
            interval_percent = _remaining_from_counts(interval_usage, interval_total)
        if weekly_percent is None:
            weekly_percent = _remaining_from_counts(weekly_usage, weekly_total)
        percents = [value for value in (interval_percent, weekly_percent) if value is not None]
        remaining_percent = min(percents) if percents else None
        if _status_is_exhausted(row.get("current_interval_status")) or (
            _status_is_exhausted(row.get("current_weekly_status"))
        ):
            remaining_percent = 0
        resources.append(
            {
                "resource": str(row.get("model_name") or "unknown"),
                "state": _quota_state(remaining_percent),
                "remaining_percent": remaining_percent,
                "interval_usage": interval_usage,
                "interval_total": interval_total,
                "interval_reset_at_ms": _safe_int(row.get("end_time")),
                "weekly_usage": weekly_usage,
                "weekly_total": weekly_total,
                "weekly_reset_at_ms": _safe_int(row.get("weekly_end_time")),
            }
        )
    general = next(
        (row for row in resources if row["resource"].strip().lower() == "general"),
        None,
    )
    primary = general or (resources[0] if resources else None)
    remaining_percent = primary.get("remaining_percent") if primary else None
    return {
        "state": _quota_state(remaining_percent),
        "visibility": "exact",
        "remaining_percent": remaining_percent,
        "resources": resources,
        "error": "" if resources else "empty quota response",
    }


async def fetch_minimax_token_plan_quota(
    api_key: str,
    *,
    base_url: Optional[str] = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    from modstore_server.infrastructure.http_clients import get_external_client

    url = _minimax_remains_url(base_url)
    try:
        response = await get_external_client().get(
            url,
            headers={
                "Authorization": f"Bearer {normalize_minimax_api_key(api_key)}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
        if response.status_code >= 400:
            return {
                "state": "error",
                "visibility": "exact",
                "remaining_percent": None,
                "resources": [],
                "error": f"http {response.status_code}",
                "source": "minimax_token_plan_remains_api",
            }
        out = parse_minimax_token_plan_remains(response.json())
        out["source"] = "minimax_token_plan_remains_api"
        return out
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001
        return {
            "state": "error",
            "visibility": "exact",
            "remaining_percent": None,
            "resources": [],
            "error": scrub_llm_error(f"{type(exc).__name__}: {exc}")[:300],
            "source": "minimax_token_plan_remains_api",
        }


def classify_probe_result(result: dict[str, Any]) -> str:
    if result.get("ok"):
        return "healthy"
    status = result.get("status")
    error = scrub_llm_error(result.get("error")).lower()
    if status in (402, 403) and any(x in error for x in ("balance", "credit", "quota")):
        return "exhausted"
    if status == 429 and any(
        x in error for x in ("quota exhausted", "usage limit", "insufficient", "limit exceeded")
    ):
        return "exhausted"
    if status == 429:
        return "warning"
    return "error"


def _local_usage_by_provider(hours: int = 24) -> dict[str, dict[str, Any]]:
    from modstore_server.models import LlmCallLog, get_session_factory

    cutoff = datetime.now(UTC) - timedelta(hours=max(1, hours))
    sf = get_session_factory()
    with sf() as session:
        rows = (
            session.query(
                LlmCallLog.provider,
                func.count(LlmCallLog.id),
                func.sum(LlmCallLog.total_tokens),
                func.sum(LlmCallLog.charge_amount),
                func.sum(case((LlmCallLog.status == "failed", 1), else_=0)),
            )
            .filter(LlmCallLog.created_at >= cutoff)
            .group_by(LlmCallLog.provider)
            .all()
        )
    return {
        str(provider): {
            "window_hours": max(1, hours),
            "calls": int(calls or 0),
            "tokens": int(tokens or 0),
            "charge_amount": float(charge or 0),
            "failed_calls": int(failed or 0),
        }
        for provider, calls, tokens, charge, failed in rows
    }


async def platform_quota_snapshot(
    *,
    live_probe: bool = False,
    catalog: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Return exact provider quota when available, otherwise explicit inference."""

    from modstore_server.llm_runtime_route import (
        platform_model_catalog,
        probe_runtime_route,
    )
    from modstore_server.services.llm import _BENCH_DEFAULT_MODELS

    model_catalog = catalog or await platform_model_catalog(refresh=False)
    try:
        local_usage = _local_usage_by_provider(24)
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001
        local_usage = {"_error": {"error": scrub_llm_error(f"{type(exc).__name__}: {exc}")[:200]}}

    providers: list[dict[str, Any]] = []
    for block in model_catalog.get("providers") or []:
        if not isinstance(block, dict) or not block.get("configured"):
            continue
        provider = str(block.get("provider") or "")
        key = platform_api_key(provider) or ""
        quota: dict[str, Any]
        if provider == "minimax" and is_minimax_token_plan_key(key):
            quota = await fetch_minimax_token_plan_quota(
                key,
                base_url=platform_base_url(provider),
            )
        else:
            quota = {
                "state": "unknown",
                "visibility": "usage_only",
                "remaining_percent": None,
                "resources": [],
                "error": "provider does not expose a supported remaining-quota API",
                "source": "local_usage_and_live_probe",
            }

        runtime_models = [str(x) for x in block.get("runtime_models") or [] if str(x)]
        preferred = _BENCH_DEFAULT_MODELS.get(provider, "")
        probe_model = (
            preferred
            if preferred in runtime_models
            else (runtime_models[0] if runtime_models else "")
        )
        probe: dict[str, Any] | None = None
        if live_probe and probe_model:
            probe = await probe_runtime_route(provider, probe_model)
            probe_state = classify_probe_result(probe)
            if probe_state in {"exhausted", "warning", "error"}:
                quota["state"] = probe_state
                quota["inferred_from_probe"] = True
            elif quota.get("state") == "unknown":
                quota["state"] = "healthy"
                quota["inferred_from_probe"] = True
        safe_probe = None
        if isinstance(probe, dict):
            safe_probe = dict(probe)
            safe_probe["error"] = scrub_llm_error(safe_probe.get("error"))[:500]
        providers.append(
            {
                "provider": provider,
                "configured": True,
                "state": quota.get("state"),
                "visibility": quota.get("visibility"),
                "remaining_percent": quota.get("remaining_percent"),
                "resources": quota.get("resources") or [],
                "source": quota.get("source"),
                "error": scrub_llm_error(quota.get("error"))[:500],
                "probe_model": probe_model,
                "probe": safe_probe,
                "local_usage_24h": local_usage.get(provider)
                or {
                    "window_hours": 24,
                    "calls": 0,
                    "tokens": 0,
                    "charge_amount": 0.0,
                    "failed_calls": 0,
                },
            }
        )

    return {
        "ok": True,
        "checked_at": _now_iso(),
        "live_probe": bool(live_probe),
        "providers": providers,
        "healthy_providers": [
            row["provider"] for row in providers if row.get("state") == "healthy"
        ],
        "exhausted_providers": [
            row["provider"] for row in providers if row.get("state") == "exhausted"
        ],
        "policy": "exact_quota_then_live_probe_then_local_usage",
    }


__all__ = [
    "classify_probe_result",
    "fetch_minimax_token_plan_quota",
    "parse_minimax_token_plan_remains",
    "platform_quota_snapshot",
    "scrub_llm_error",
]
