# mypy: disable-error-code="attr-defined, misc, no-any-return, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.llm_api")


def _read_catalog_credentials(user_id: int, provider: str):
    from modstore_server.llm_catalog import resolve_catalog_credentials
    from modstore_server.models import get_session_factory

    with get_session_factory()() as session:
        return resolve_catalog_credentials(session, user_id, provider)


async def _fetch_catalog_provider_block(
    user_id: int, provider: str, *, force_refresh: bool
) -> _facade().Dict[str, _facade().Any]:
    """Fetch providers concurrently without holding database connections across awaits."""
    from modstore_server.llm_catalog import get_models_for_credentials

    labels = _facade()._provider_labels()
    empty = {
        "provider": provider,
        "label": labels.get(provider, provider),
        "models": [],
        "models_detailed": [],
        "runtime_models": [],
        "media_counts": _facade().media_counts_from_detailed([]),
        "supports_openai_images": provider in _facade().OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
        "fetched_at": None,
        "from_cache": False,
    }
    try:
        async with _facade().asyncio.timeout(_facade()._CATALOG_PROVIDER_TIMEOUT_SEC):
            api_key, base_url = await _facade().asyncio.to_thread(
                _read_catalog_credentials, user_id, provider
            )
            block = await get_models_for_credentials(
                user_id,
                provider,
                api_key=api_key,
                base_url=base_url,
                force_refresh=force_refresh,
            )
        mids: _facade().List[str] = list(block.get("models") or [])
        detailed = list(block.get("models_detailed") or [])
        if not detailed:
            detailed = _facade().build_models_detailed(provider, mids)
        return {
            **empty,
            "models": mids,
            "models_detailed": detailed,
            "runtime_models": list(block.get("runtime_models") or []),
            "media_counts": _facade().media_counts_from_detailed(detailed),
            "supports_openai_images": provider in _facade().OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
            "fetched_at": block.get("fetched_at"),
            "error": block.get("error"),
            "from_cache": block.get("from_cache", False),
            "fetch_source": block.get("source"),
        }
    except _facade().asyncio.TimeoutError:
        return {**empty, "error": "provider_timeout", "fetch_source": "timeout"}
    except RECOVERABLE_ERRORS as e:
        _facade().logger.exception("llm_catalog provider %s failed", provider)
        return {
            **empty,
            "error": f"internal: {e.__class__.__name__}",
            "fetch_source": "error",
        }


@_facade().router.get("/catalog")
async def llm_catalog(
    refresh: int = _facade().Query(0, ge=0, le=1),
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    force = bool(refresh)
    providers_out = list(
        await _facade().asyncio.gather(
            *[
                _facade()._fetch_catalog_provider_block(user.id, p, force_refresh=force)
                for p in _facade().KNOWN_PROVIDERS
            ]
        )
    )
    prefs: _facade().Dict[str, str] = {}
    urow = db.query(_facade().User).filter(_facade().User.id == user.id).first()
    raw = ((urow.default_llm_json if urow else None) or "").strip()
    if raw:
        try:
            prefs = _facade().json.loads(raw)
            if not isinstance(prefs, dict):
                prefs = {}
        except _facade().json.JSONDecodeError:
            prefs = {}
    _facade().merge_catalog_capabilities(db, providers_out)
    try:
        _facade().merge_catalog_pricing(db, providers_out)
    except RECOVERABLE_ERRORS:
        _facade().logger.exception(
            "merge_catalog_pricing failed (catalog still returned without pricing)"
        )
    settings = _facade().billing_settings_dict(db)
    return {
        "cache_ttl_seconds": 600,
        "category_labels": _facade().category_labels_zh(),
        "providers": providers_out,
        "preferences": {
            "provider": prefs.get("provider") or "openai",
            "model": prefs.get("model") or "",
        },
        "fernet_configured": _facade().fernet_configured(),
        "gate_hints": {
            "platform_catalog_gate": _facade().platform_catalog_gate_enabled(),
            "byok_catalog_gate": _facade().byok_catalog_gate_enabled(),
            "platform_require_priced": _facade().platform_require_priced_row(),
        },
        "billing_settings": settings,
    }


class PlatformRuntimeRouteDTO(_facade().BaseModel):
    provider: str = _facade().Field(..., min_length=2, max_length=64)
    model: str = _facade().Field(..., min_length=1, max_length=256)
    reason: str = _facade().Field("", max_length=1000)
    refresh_catalog: bool = False
    force: bool = False


class PlatformRuntimeRollbackDTO(_facade().BaseModel):
    reason: str = _facade().Field("", max_length=1000)
    force: bool = False


@_facade().router.get("/admin/runtime-route")
async def get_platform_runtime_route(
    admin: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """Current platform-funded AI employee route plus effective fallback."""
    from modstore_server.llm_key_resolver import KNOWN_PROVIDERS, platform_api_key
    from modstore_server.llm_runtime_route import (
        read_runtime_route_state,
        rollback_target,
    )
    from modstore_server.services.llm import resolve_platform_bench_llm

    provider, model = resolve_platform_bench_llm()
    return {
        "ok": True,
        "scope": "platform_ai_employees",
        "state": read_runtime_route_state(),
        "effective": {"provider": provider, "model": model},
        "configured_providers": [p for p in KNOWN_PROVIDERS if platform_api_key(p)],
        "rollback": rollback_target(),
        "actor": f"admin:{admin.id}",
    }


@_facade().router.get("/admin/runtime-route/catalog")
async def get_platform_runtime_route_catalog(
    provider: _facade().Optional[str] = _facade().Query(None, max_length=64),
    refresh: int = _facade().Query(0, ge=0, le=1),
    admin: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """Selectable models from the same source as ``GET /api/llm/catalog``."""
    from modstore_server.llm_runtime_route import platform_model_catalog

    _ = admin
    result = await platform_model_catalog(provider, refresh=bool(refresh))
    if not result.get("ok"):
        raise _facade().HTTPException(400, str(result.get("error") or "catalog failed"))
    return result


@_facade().router.get("/admin/runtime-route/quota")
async def get_platform_runtime_route_quota(
    live_probe: int = _facade().Query(0, ge=0, le=1),
    admin: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """Secret-safe provider quota and usage status for the admin control plane."""
    from modstore_server.llm_quota_monitor import platform_quota_snapshot

    result = await platform_quota_snapshot(live_probe=bool(live_probe))
    result["scope"] = "platform_ai_employees"
    result["actor"] = f"admin:{admin.id}"
    return result


@_facade().router.get("/admin/runtime-route/autopilot")
async def get_platform_runtime_route_autopilot(
    admin: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """Read-only autopilot policy and latest decision receipt."""
    from modstore_server.llm_runtime_autopilot import autopilot_status

    result = autopilot_status()
    result["scope"] = "platform_ai_employees"
    result["actor"] = f"admin:{admin.id}"
    return result


@_facade().router.put("/admin/runtime-route")
async def put_platform_runtime_route(
    body: PlatformRuntimeRouteDTO,
    admin: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """Health-check and atomically switch the next platform employee LLM call."""
    from modstore_server.llm_runtime_route import switch_runtime_route

    result = await switch_runtime_route(
        body.provider,
        body.model,
        actor=f"admin:{admin.id}",
        reason=body.reason,
        refresh_catalog=body.refresh_catalog,
        force=body.force,
    )
    if not result.get("ok"):
        raise _facade().HTTPException(400, detail=result)
    return result


@_facade().router.post("/admin/runtime-route/rollback")
async def post_platform_runtime_route_rollback(
    body: PlatformRuntimeRollbackDTO,
    admin: _facade().User = _facade().Depends(_facade()._require_admin),
):
    from modstore_server.llm_runtime_route import rollback_runtime_route

    result = await rollback_runtime_route(
        actor=f"admin:{admin.id}", reason=body.reason, force=body.force
    )
    if not result.get("ok"):
        raise _facade().HTTPException(400, detail=result)
    return result


class LlmCredentialDTO(_facade().BaseModel):
    api_key: str = _facade().Field(..., min_length=4, max_length=4096)
    base_url: _facade().Optional[str] = _facade().Field(None, max_length=2048)


class LlmBareKeyDetectDTO(_facade().BaseModel):
    """无标签裸密钥：在已知厂商上并行试拉 /models，命中后再入库。"""

    api_key: str = _facade().Field(..., min_length=8, max_length=4096)


@_facade().router.post("/credentials/detect-bare")
async def post_detect_bare_credential(
    body: LlmBareKeyDetectDTO,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    _facade()._require_byok_membership(db, user)
    if not _facade().fernet_configured():
        raise _facade().HTTPException(503, "服务端未配置 MODSTORE_LLM_MASTER_KEY，无法保存 BYOK")
    key = body.api_key.strip()
    if not key:
        raise _facade().HTTPException(400, "api_key 为空")
    provider = await _facade().probe_first_matching_provider(key)
    if not provider:
        raise _facade().HTTPException(
            400,
            "无法在已知厂商中通过拉取模型列表验证该密钥。请改用手动格式：厂商id=密钥（如 deepseek=sk-…）或环境变量名（如 OPENAI_API_KEY=…）。",
        )
    try:
        enc_key = _facade().encrypt_secret(key)
    except RuntimeError as e:
        raise _facade().HTTPException(503, str(e)) from e
    row = (
        db.query(_facade().UserLlmCredential)
        .filter(
            _facade().UserLlmCredential.user_id == user.id,
            _facade().UserLlmCredential.provider == provider,
        )
        .first()
    )
    if row:
        row.api_key_encrypted = enc_key
        row.base_url_encrypted = None
    else:
        row = _facade().UserLlmCredential(
            user_id=user.id,
            provider=provider,
            api_key_encrypted=enc_key,
            base_url_encrypted=None,
        )
        db.add(row)
    db.commit()
    _facade().clear_all_catalog_cache()
    label = _facade()._provider_labels().get(provider, provider)
    return {"ok": True, "provider": provider, "message": f"已识别为「{label}」并保存"}


@_facade().router.put("/credentials/{provider}")
async def put_llm_credentials(
    provider: str,
    body: LlmCredentialDTO,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    if provider not in _facade().KNOWN_PROVIDERS:
        raise _facade().HTTPException(400, "unknown provider")
    _facade()._require_byok_membership(db, user)
    if not _facade().fernet_configured():
        raise _facade().HTTPException(503, "服务端未配置 MODSTORE_LLM_MASTER_KEY，无法保存 BYOK")
    key = body.api_key.strip()
    if not key:
        raise _facade().HTTPException(400, "api_key 为空")
    bu = (body.base_url or "").strip() or None
    try:
        enc_key = _facade().encrypt_secret(key)
        enc_base = _facade().encrypt_secret(bu) if bu else None
    except RuntimeError as e:
        raise _facade().HTTPException(503, str(e)) from e
    row = (
        db.query(_facade().UserLlmCredential)
        .filter(
            _facade().UserLlmCredential.user_id == user.id,
            _facade().UserLlmCredential.provider == provider,
        )
        .first()
    )
    if row:
        row.api_key_encrypted = enc_key
        row.base_url_encrypted = enc_base
    else:
        row = _facade().UserLlmCredential(
            user_id=user.id,
            provider=provider,
            api_key_encrypted=enc_key,
            base_url_encrypted=enc_base,
        )
        db.add(row)
    db.commit()
    _facade().clear_all_catalog_cache()
    return {"ok": True, "provider": provider}


@_facade().router.delete("/credentials/{provider}")
async def delete_llm_credentials(
    provider: str,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    if provider not in _facade().KNOWN_PROVIDERS:
        raise _facade().HTTPException(400, "unknown provider")
    row = (
        db.query(_facade().UserLlmCredential)
        .filter(
            _facade().UserLlmCredential.user_id == user.id,
            _facade().UserLlmCredential.provider == provider,
        )
        .first()
    )
    if row:
        db.delete(row)
        db.commit()
        _facade().clear_all_catalog_cache()
    return {"ok": True}


class LlmPreferenceDTO(_facade().BaseModel):
    provider: str = _facade().Field(..., min_length=2, max_length=32)
    model: str = _facade().Field(..., min_length=1, max_length=256)


class LlmPriceDTO(_facade().BaseModel):
    provider: str = _facade().Field(..., min_length=2, max_length=64)
    model: str = _facade().Field(..., min_length=1, max_length=256)
    label: str = ""
    input_price_per_1k: float = _facade().Field(0.006, ge=0)
    output_price_per_1k: float = _facade().Field(0.018, ge=0)
    min_charge: float = _facade().Field(0.02, ge=0)
    enabled: bool = True


@_facade().router.put("/preferences")
async def put_llm_preferences(
    body: LlmPreferenceDTO,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    if body.provider not in _facade().KNOWN_PROVIDERS:
        raise _facade().HTTPException(400, "unknown provider")
    u = db.query(_facade().User).filter(_facade().User.id == user.id).first()
    if not u:
        raise _facade().HTTPException(401, "用户不存在")
    u.default_llm_json = _facade().json.dumps(
        {"provider": body.provider, "model": body.model.strip()}, ensure_ascii=False
    )
    db.commit()
    return {"ok": True, "preferences": _facade().json.loads(u.default_llm_json)}


def _price_row_to_dict(r: _facade().AiModelPrice) -> _facade().Dict[str, _facade().Any]:
    return {
        "provider": r.provider,
        "model": r.model,
        "label": r.label or r.model,
        "input_price_per_1k": float(r.input_price_per_1k or 0),
        "output_price_per_1k": float(r.output_price_per_1k or 0),
        "min_charge": float(r.min_charge or 0),
        "official_input_price_per_1k": (
            float(r.official_input_price_per_1k)
            if r.official_input_price_per_1k is not None
            else None
        ),
        "official_output_price_per_1k": (
            float(r.official_output_price_per_1k)
            if r.official_output_price_per_1k is not None
            else None
        ),
        "official_min_charge": (
            float(r.official_min_charge) if r.official_min_charge is not None else None
        ),
        "official_source": str(r.official_source or ""),
        "official_synced_at": r.official_synced_at.isoformat() if r.official_synced_at else None,
        "enabled": bool(r.enabled),
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }
