# mypy: disable-error-code="union-attr"
"""Persistent runtime routing for platform-funded AI employee LLM calls.

The platform model catalog (``llm_catalog.get_models_for_provider``) remains the
single source of truth for selectable models.  This module only stores the
currently selected provider/model and a bounded audit trail; it never stores or
returns API keys.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = 1
_MAX_HISTORY = 100
_LOCK = threading.RLock()


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


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


def runtime_route_path() -> Path:
    explicit = (os.environ.get("MODSTORE_LLM_RUNTIME_ROUTE_PATH") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    root = (
        os.environ.get("MODSTORE_RUNTIME_DIR")
        or os.environ.get("MODSTORE_DATA_DIR")
        or "/tmp/modstore_data"
    )
    return Path(root).expanduser().resolve() / "llm" / "runtime_route.json"


def _empty_state() -> dict[str, Any]:
    return {"schema_version": _SCHEMA_VERSION, "current": None, "history": []}


@contextmanager
def _process_file_lock(*, exclusive: bool):
    """Serialize route writes across API/scheduler workers sharing ``/data``."""

    path = runtime_route_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        try:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        except (ImportError, OSError):
            pass
        try:
            yield
        finally:
            try:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass


def _read_state_unlocked() -> dict[str, Any]:
    path = runtime_route_path()
    if not path.is_file():
        return _empty_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_state()
    if not isinstance(raw, dict):
        return _empty_state()
    current = raw.get("current") if isinstance(raw.get("current"), dict) else None
    history = raw.get("history") if isinstance(raw.get("history"), list) else []
    return {
        "schema_version": _SCHEMA_VERSION,
        "current": current,
        "history": [row for row in history if isinstance(row, dict)][-_MAX_HISTORY:],
    }


def read_runtime_route_state() -> dict[str, Any]:
    with _LOCK, _process_file_lock(exclusive=False):
        return _read_state_unlocked()


def _write_state(state: dict[str, Any]) -> None:
    path = runtime_route_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    payload = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def current_runtime_route() -> dict[str, Any] | None:
    current = read_runtime_route_state().get("current")
    if not isinstance(current, dict):
        return None
    provider = str(current.get("provider") or "").strip().lower()
    model = str(current.get("model") or "").strip()
    if not provider or not model:
        return None
    return dict(current)


def commit_runtime_route(
    provider: str | None,
    model: str | None,
    *,
    actor: str,
    reason: str,
    health: dict[str, Any] | None = None,
    source: str = "platform_catalog",
    action: str = "switch",
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Atomically commit a route (or ``None`` to restore environment fallback).

    ``expected_revision`` is a compare-and-swap guard. ``None`` preserves the
    administrative/legacy unconditional write, while ``""`` explicitly means
    that no persistent route is expected.  The autopilot always supplies this
    guard so it cannot overwrite a concurrent administrator decision.
    """

    provider_id = str(provider or "").strip().lower()
    model_id = str(model or "").strip()
    if bool(provider_id) != bool(model_id):
        raise ValueError("provider and model must either both be set or both be empty")
    actor_id = str(actor or "unknown").strip()[:128] or "unknown"
    reason_text = str(_secret_safe(str(reason or "").strip()))[:1000]
    safe_health = _secret_safe(dict(health or {}))

    with _LOCK, _process_file_lock(exclusive=True):
        state = _read_state_unlocked()
        previous = state.get("current") if isinstance(state.get("current"), dict) else None
        actual_revision = str(previous.get("revision") or "") if isinstance(previous, dict) else ""
        if expected_revision is not None and actual_revision != expected_revision:
            return {
                "ok": False,
                "conflict": True,
                "error": "route_revision_conflict",
                "expected_revision": expected_revision,
                "actual_revision": actual_revision,
                "current": _secret_safe(previous),
            }
        revision = uuid.uuid4().hex
        switched_at = _now_iso()
        current = None
        if provider_id and model_id:
            current = {
                "provider": provider_id,
                "model": model_id,
                "revision": revision,
                "switched_at": switched_at,
                "actor": actor_id,
                "reason": reason_text,
                "source": source,
                "health": safe_health,
            }
        event = {
            "revision": revision,
            "action": str(action or "switch")[:32],
            "at": switched_at,
            "actor": actor_id,
            "reason": reason_text,
            "from": previous,
            "to": current,
        }
        history = list(state.get("history") or [])
        history.append(event)
        new_state = {
            "schema_version": _SCHEMA_VERSION,
            "current": current,
            "history": history[-_MAX_HISTORY:],
        }
        _write_state(new_state)
    return {"ok": True, "current": current, "previous": previous, "event": event}


async def platform_model_catalog(
    provider: str | None = None,
    *,
    refresh: bool = False,
) -> dict[str, Any]:
    """Return selectable platform-funded models from the canonical catalog."""

    from modstore_server.llm_catalog import get_models_for_provider
    from modstore_server.llm_key_resolver import KNOWN_PROVIDERS, platform_api_key
    from modstore_server.models import get_session_factory

    target = str(provider or "").strip().lower()
    if target and target not in KNOWN_PROVIDERS:
        return {"ok": False, "error": f"unknown provider: {target}", "providers": []}
    provider_ids = [target] if target else list(KNOWN_PROVIDERS)

    async def _one(provider_id: str) -> dict[str, Any]:
        configured = bool(platform_api_key(provider_id))
        if not configured:
            return {
                "provider": provider_id,
                "configured": False,
                "models": [],
                "models_detailed": [],
                "runtime_models": [],
                "source": "no_platform_key",
                "error": "no_platform_key",
            }
        sf = get_session_factory()
        with sf() as session:
            block = await get_models_for_provider(
                session,
                0,
                provider_id,
                force_refresh=bool(refresh),
            )
        detailed = list(block.get("models_detailed") or [])
        runtime_models = [
            str(row.get("id") or "").strip()
            for row in detailed
            if isinstance(row, dict)
            and row.get("runtime_selectable") is True
            and str(row.get("id") or "").strip()
        ]
        return {
            "provider": provider_id,
            "configured": True,
            "models": [str(x).strip() for x in (block.get("models") or []) if str(x).strip()],
            "models_detailed": detailed,
            "runtime_models": runtime_models,
            "source": block.get("source"),
            "fetched_at": block.get("fetched_at"),
            "error": block.get("error"),
            "from_cache": bool(block.get("from_cache")),
        }

    blocks = list(await asyncio.gather(*[_one(pid) for pid in provider_ids]))
    return {
        "ok": True,
        "providers": blocks,
        "configured_count": sum(1 for row in blocks if row.get("configured")),
        "model_count": sum(len(row.get("models") or []) for row in blocks),
        "runtime_model_count": sum(len(row.get("runtime_models") or []) for row in blocks),
        "source": "/api/llm/catalog",
        "capability_discovery": "provider_metadata_then_versioned_inference",
    }


async def probe_runtime_route(provider: str, model: str) -> dict[str, Any]:
    from modstore_server.services.llm import chat_dispatch_via_platform_only

    result = await chat_dispatch_via_platform_only(
        provider,
        model,
        [{"role": "user", "content": "Reply OK."}],
        max_tokens=8,
    )
    return {
        "ok": bool(result.get("ok")),
        "status": result.get("status"),
        "error": str(_secret_safe(result.get("error")))[:500],
        "checked_at": _now_iso(),
    }


# Backward-compatible seam retained for existing tests and integrations.
_probe_route = probe_runtime_route


async def switch_runtime_route(
    provider: str,
    model: str,
    *,
    actor: str,
    reason: str = "",
    refresh_catalog: bool = False,
    force: bool = False,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Validate against the platform catalog, health-check, then switch."""

    from modstore_server.llm_key_resolver import KNOWN_PROVIDERS, platform_api_key

    provider_id = str(provider or "").strip().lower()
    model_id = str(model or "").strip()
    if provider_id not in KNOWN_PROVIDERS:
        return {"ok": False, "error": f"unknown provider: {provider_id}"}
    if not model_id:
        return {"ok": False, "error": "model is required"}
    if not platform_api_key(provider_id):
        return {"ok": False, "error": f"no platform api key: {provider_id}"}

    catalog = await platform_model_catalog(provider_id, refresh=refresh_catalog)
    block = (catalog.get("providers") or [{}])[0]
    available = [str(x) for x in (block.get("models") or [])]
    if model_id not in available and not force:
        return {
            "ok": False,
            "error": f"model is not in platform catalog: {provider_id}/{model_id}",
            "available_models": available[:200],
            "catalog_source": block.get("source"),
        }
    detailed = {
        str(row.get("id") or ""): row
        for row in (block.get("models_detailed") or [])
        if isinstance(row, dict) and str(row.get("id") or "")
    }
    selected_detail = detailed.get(model_id)
    if (
        isinstance(selected_detail, dict)
        and selected_detail.get("runtime_selectable") is False
        and not force
    ):
        return {
            "ok": False,
            "error": f"model cannot be used as employee chat runtime: {provider_id}/{model_id}",
            "model": selected_detail,
            "available_runtime_models": list(block.get("runtime_models") or [])[:200],
        }

    health = await _probe_route(provider_id, model_id)
    if not health.get("ok") and not force:
        return {
            "ok": False,
            "error": f"route health check failed: {provider_id}/{model_id}",
            "health": health,
        }
    committed = commit_runtime_route(
        provider_id,
        model_id,
        actor=actor,
        reason=reason,
        health=health,
        source=str(block.get("source") or "platform_catalog"),
        expected_revision=expected_revision,
    )
    committed["catalog_source"] = block.get("source")
    committed["forced"] = bool(force)
    committed["effective_for"] = "next_platform_employee_llm_call"
    return committed


def rollback_target() -> dict[str, Any]:
    state = read_runtime_route_state()
    history = state.get("history") or []
    if not history:
        return {"available": False, "target": None}
    last = history[-1] if isinstance(history[-1], dict) else {}
    return {"available": True, "target": last.get("from"), "event": last}


async def rollback_runtime_route(
    *,
    actor: str,
    reason: str = "",
    force: bool = False,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    target_info = rollback_target()
    if not target_info.get("available"):
        return {"ok": False, "error": "no runtime route history to rollback"}
    target = target_info.get("target")
    if not isinstance(target, dict):
        return commit_runtime_route(
            None,
            None,
            actor=actor,
            reason=reason or "rollback to environment fallback",
            action="rollback",
            expected_revision=expected_revision,
        )
    provider = str(target.get("provider") or "")
    model = str(target.get("model") or "")
    health = await _probe_route(provider, model)
    if not health.get("ok") and not force:
        return {
            "ok": False,
            "error": "rollback target health check failed",
            "health": health,
        }
    return commit_runtime_route(
        provider,
        model,
        actor=actor,
        reason=reason or "rollback previous runtime route",
        health=health,
        source=str(target.get("source") or "platform_catalog"),
        action="rollback",
        expected_revision=expected_revision,
    )


__all__ = [
    "commit_runtime_route",
    "current_runtime_route",
    "platform_model_catalog",
    "probe_runtime_route",
    "read_runtime_route_state",
    "rollback_runtime_route",
    "rollback_target",
    "runtime_route_path",
    "switch_runtime_route",
]
