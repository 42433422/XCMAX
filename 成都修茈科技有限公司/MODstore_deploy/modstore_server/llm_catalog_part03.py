# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.llm_catalog")


async def get_models_for_provider(
    session, user_id: int, provider: str, *, force_refresh: bool = False
) -> _facade().Dict[str, _facade().Any]:
    """Compatibility entry point for callers owning their database session."""
    api_key, base_url = resolve_catalog_credentials(session, user_id, provider)
    return await get_models_for_credentials(
        user_id, provider, api_key=api_key, base_url=base_url, force_refresh=force_refresh
    )


def resolve_catalog_credentials(session, user_id: int, provider: str):
    """Read credential values without retaining ORM rows or a database session."""
    api_key, _src = _facade().resolve_api_key(session, user_id, provider)
    base_url = (
        _facade().resolve_base_url(session, user_id, provider)
        if api_key and provider in _facade().OAI_COMPAT_OPENAI_STYLE_PROVIDERS
        else None
    )
    return api_key, base_url


async def get_models_for_credentials(
    user_id: int, provider: str, *, api_key, base_url, force_refresh: bool = False
) -> _facade().Dict[str, _facade().Any]:
    """Fetch a catalog after the caller has released its credential connection."""
    if not api_key:
        models = _facade()._merge_fallback(provider, [])
        detailed = _facade()._models_detailed(provider, models)
        return {
            "models": models,
            "models_detailed": detailed,
            "runtime_models": _facade()._runtime_model_ids(detailed),
            "source": "fallback_only",
            "fetched_at": None,
            "error": "no_api_key",
            "from_cache": False,
        }
    ck = _facade()._cache_key(user_id, provider, api_key)
    now = _facade().time.monotonic()
    if force_refresh:
        last = _facade()._last_force_refresh.get(user_id, 0.0)
        if now - last < _facade()._FORCE_REFRESH_MIN_INTERVAL:
            force_refresh = False
        else:
            _facade()._last_force_refresh[user_id] = now
    if not force_refresh and ck in _facade()._cache:
        ent = _facade()._cache[ck]
        if now - ent["mono"] < _facade()._CACHE_TTL_SEC:
            return {
                "models": ent["models"],
                "models_detailed": ent.get("models_detailed")
                or _facade()._models_detailed(provider, ent["models"]),
                "runtime_models": ent.get("runtime_models")
                or _facade()._runtime_model_ids(
                    ent.get("models_detailed")
                    or _facade()._models_detailed(provider, ent["models"])
                ),
                "source": ent.get("source", "cache"),
                "fetched_at": ent.get("fetched_at_wall"),
                "error": ent.get("error"),
                "from_cache": True,
            }
    remote: _facade().List[str] = []
    remote_records: _facade().List[_facade().Dict[str, _facade().Any]] = []
    err: _facade().Optional[str] = None
    src = "remote"
    if provider == "minimax" and _facade().is_minimax_token_plan_key(api_key):
        raw_base = base_url
        remote_records, err = await _facade()._fetch_minimax_token_plan_records(
            api_key, base_url=raw_base
        )
    elif provider in _facade().OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
        raw_base = base_url
        b = (raw_base or _facade().openai_compat_default_root(provider)).rstrip("/")
        if not (b.endswith("/v1") or b.endswith("/v2") or b.endswith("/v3") or b.endswith("/v4")):
            b = b + "/v1"
        remote_records, err = await _facade()._fetch_openai_compatible_records(
            b, api_key, provider=provider
        )
    elif provider == "anthropic":
        remote_records, err = await _facade()._fetch_anthropic_records(api_key)
    elif provider == "google":
        remote_records, err = await _facade()._fetch_google_records(api_key)
    else:
        return {
            "models": [],
            "models_detailed": [],
            "runtime_models": [],
            "source": "unknown_provider",
            "fetched_at": None,
            "error": "unknown",
            "from_cache": False,
        }
    remote = sorted(
        {
            _facade()._model_id(item)
            for item in remote_records
            if _facade()._model_id(item) and (not _facade()._model_id(item).startswith("ft:"))
        }
    )
    merged = _facade()._merge_fallback(provider, remote)
    detailed = _facade()._models_detailed(provider, merged, remote_records)
    runtime_models = _facade()._runtime_model_ids(detailed)
    fb = _facade()._load_fallback().get(provider) or []
    if not remote:
        if merged and fb:
            if err:
                src = "fallback_after_error"
            else:
                src = "static_fallback_merged"
                err = err or "catalog_static_fallback_only"
        elif err:
            src = "fallback_after_error"
    wall = _facade()._dt.datetime.now(_facade()._dt.UTC).replace(microsecond=0).isoformat() + "Z"
    _facade()._cache[ck] = {
        "mono": now,
        "models": merged,
        "models_detailed": detailed,
        "runtime_models": runtime_models,
        "error": err,
        "source": src,
        "fetched_at_wall": wall,
    }
    return {
        "models": merged,
        "models_detailed": detailed,
        "runtime_models": runtime_models,
        "source": src,
        "fetched_at": wall,
        "error": err,
        "from_cache": False,
    }
