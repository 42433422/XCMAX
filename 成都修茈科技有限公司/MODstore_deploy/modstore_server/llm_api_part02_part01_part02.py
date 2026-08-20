# mypy: disable-error-code="attr-defined, misc, no-any-return, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib
from modstore_server.llm_api_part02_part01_part01 import LlmPriceDTO


def _facade():
    return importlib.import_module("modstore_server.llm_api")


def _upsert_ai_model_price(db: _facade().Session, body: LlmPriceDTO) -> _facade().AiModelPrice:
    row = (
        db.query(_facade().AiModelPrice)
        .filter(
            _facade().AiModelPrice.provider == body.provider.strip(),
            _facade().AiModelPrice.model == body.model.strip(),
        )
        .first()
    )
    if not row:
        row = _facade().AiModelPrice(provider=body.provider.strip(), model=body.model.strip())
        db.add(row)
    row.label = body.label.strip()
    row.input_price_per_1k = float(body.input_price_per_1k)
    row.output_price_per_1k = float(body.output_price_per_1k)
    row.min_charge = float(body.min_charge)
    row.enabled = bool(body.enabled)
    return row


@_facade().router.get("/pricing")
async def llm_pricing(
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    settings = _facade().billing_settings_dict(db)
    rows = db.query(_facade().AiModelPrice).filter(_facade().AiModelPrice.enabled.is_(True)).all()
    return {
        **settings,
        "items": [
            {
                **_facade()._price_row_to_dict(r),
                **_facade().pricing_public_dict(db, r.provider, r.model, priced_row=r),
            }
            for r in rows
        ],
    }


@_facade().router.get("/admin/pricing")
async def llm_admin_list_pricing(
    provider: _facade().Optional[str] = _facade().Query(None, max_length=64),
    q: _facade().Optional[str] = _facade().Query(None, max_length=128),
    limit: int = _facade().Query(500, ge=1, le=2000),
    offset: int = _facade().Query(0, ge=0),
    db: _facade().Session = _facade().Depends(_facade().get_db),
    admin: _facade().User = _facade().Depends(_facade()._require_admin),
):
    query = db.query(_facade().AiModelPrice)
    if provider:
        query = query.filter(_facade().AiModelPrice.provider == provider.strip())
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            _facade().AiModelPrice.model.ilike(like) | _facade().AiModelPrice.label.ilike(like)
        )
    total = query.count()
    rows = (
        query.order_by(_facade().AiModelPrice.provider.asc(), _facade().AiModelPrice.model.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "ok": True,
        "total": total,
        "items": [_facade()._price_row_to_dict(r) for r in rows],
        "settings": _facade().billing_settings_dict(db),
    }


@_facade().router.put("/admin/pricing")
async def llm_admin_put_price(
    body: LlmPriceDTO,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    admin: _facade().User = _facade().Depends(_facade()._require_admin),
):
    row = _facade()._upsert_ai_model_price(db, body)
    db.commit()
    return {
        "ok": True,
        "provider": row.provider,
        "model": row.model,
        "item": _facade()._price_row_to_dict(row),
    }


class LlmBillingSettingsDTO(_facade().BaseModel):
    service_fee_multiplier: _facade().Optional[float] = _facade().Field(None, ge=1, le=10)
    official_markup_multiplier: _facade().Optional[float] = _facade().Field(None, ge=1, le=10)
    default_input_price_per_1k: _facade().Optional[float] = _facade().Field(None, ge=0)
    default_output_price_per_1k: _facade().Optional[float] = _facade().Field(None, ge=0)
    default_min_charge: _facade().Optional[float] = _facade().Field(None, ge=0)


@_facade().router.put("/admin/pricing/settings")
async def llm_admin_put_pricing_settings(
    body: LlmBillingSettingsDTO,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    admin: _facade().User = _facade().Depends(_facade()._require_admin),
):
    row = _facade().get_or_create_billing_settings(db)
    if body.service_fee_multiplier is not None:
        row.service_fee_multiplier = float(body.service_fee_multiplier)
    if body.official_markup_multiplier is not None:
        row.official_markup_multiplier = float(body.official_markup_multiplier)
    if body.default_input_price_per_1k is not None:
        row.default_input_price_per_1k = float(body.default_input_price_per_1k)
    if body.default_output_price_per_1k is not None:
        row.default_output_price_per_1k = float(body.default_output_price_per_1k)
    if body.default_min_charge is not None:
        row.default_min_charge = float(body.default_min_charge)
    db.commit()
    return {"ok": True, "settings": _facade().billing_settings_dict(db)}


class LlmPriceBatchTemplateDTO(_facade().BaseModel):
    input_price_per_1k: float = _facade().Field(0.006, ge=0)
    output_price_per_1k: float = _facade().Field(0.018, ge=0)
    min_charge: float = _facade().Field(0.02, ge=0)
    label_prefix: str = ""


class LlmPriceBatchDTO(_facade().BaseModel):
    provider: str = _facade().Field(..., min_length=2, max_length=64)
    mode: str = _facade().Field("unpriced_only", pattern="^(unpriced_only|all_catalog)$")
    model_ids: _facade().Optional[_facade().List[str]] = None
    template: LlmPriceBatchTemplateDTO = _facade().Field(default_factory=LlmPriceBatchTemplateDTO)


@_facade().router.post("/admin/pricing/batch")
async def llm_admin_batch_pricing(
    body: LlmPriceBatchDTO,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    admin: _facade().User = _facade().Depends(_facade()._require_admin),
):
    prov = body.provider.strip()
    if prov not in _facade().KNOWN_PROVIDERS:
        raise _facade().HTTPException(400, "unknown provider")
    if body.model_ids:
        target_ids = [m.strip() for m in body.model_ids if m and m.strip()]
    else:
        block = await _facade().get_models_for_provider(db, admin.id, prov, force_refresh=False)
        target_ids = [str(x) for x in block.get("models") or [] if x]
    if not target_ids:
        raise _facade().HTTPException(400, "该厂商目录为空，请先刷新模型列表")
    existing = {
        (r.provider, r.model)
        for r in db.query(_facade().AiModelPrice)
        .filter(_facade().AiModelPrice.provider == prov)
        .all()
    }
    tpl = body.template
    written = 0
    for mid in target_ids:
        if body.mode == "unpriced_only" and (prov, mid) in existing:
            continue
        label = f"{tpl.label_prefix}{mid}".strip() if tpl.label_prefix else mid
        _facade()._upsert_ai_model_price(
            db,
            _facade().LlmPriceDTO(
                provider=prov,
                model=mid,
                label=label,
                input_price_per_1k=tpl.input_price_per_1k,
                output_price_per_1k=tpl.output_price_per_1k,
                min_charge=tpl.min_charge,
                enabled=True,
            ),
        )
        written += 1
    db.commit()
    return {"ok": True, "provider": prov, "written": written, "mode": body.mode}


class LlmOfficialSyncDTO(_facade().BaseModel):
    provider: str = _facade().Field(..., min_length=2, max_length=64)
    model_ids: _facade().Optional[_facade().List[str]] = None
    sources: _facade().Optional[_facade().List[str]] = _facade().Field(
        default_factory=lambda: ["curated", "openrouter"]
    )
    apply_markup: bool = False


@_facade().router.get("/admin/pricing/official-sources")
async def llm_admin_official_sources(
    provider: str = _facade().Query(..., min_length=2, max_length=64),
    admin: _facade().User = _facade().Depends(_facade()._require_admin),
):
    if provider.strip() not in _facade().KNOWN_PROVIDERS:
        raise _facade().HTTPException(400, "unknown provider")
    return {
        "ok": True,
        **_facade().list_official_sources_for_provider(provider.strip()),
    }


@_facade().router.post("/admin/pricing/sync-official")
async def llm_admin_sync_official_prices(
    body: LlmOfficialSyncDTO,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    admin: _facade().User = _facade().Depends(_facade()._require_admin),
):
    prov = body.provider.strip()
    if prov not in _facade().KNOWN_PROVIDERS:
        raise _facade().HTTPException(400, "unknown provider")
    if body.model_ids:
        target_ids = [m.strip() for m in body.model_ids if m and m.strip()]
    else:
        block = await _facade().get_models_for_provider(db, admin.id, prov, force_refresh=False)
        target_ids = [str(x) for x in block.get("models") or [] if x]
    if not target_ids:
        raise _facade().HTTPException(400, "该厂商目录为空，请先刷新模型列表")
    result = await _facade().sync_official_prices_for_provider(
        db, prov, target_ids, sources=body.sources
    )
    if body.apply_markup:
        markup = _facade().official_markup_multiplier(db)
        apply_result = _facade().apply_official_markup_to_rows(db, prov, target_ids, markup)
        result["apply_markup"] = apply_result
    db.commit()
    return {"ok": True, **result}


class LlmOfficialApplyMarkupDTO(_facade().BaseModel):
    provider: str = _facade().Field(..., min_length=2, max_length=64)
    model_ids: _facade().Optional[_facade().List[str]] = None
    multiplier: _facade().Optional[float] = _facade().Field(None, ge=1, le=10)


@_facade().router.post("/admin/pricing/apply-official-markup")
async def llm_admin_apply_official_markup(
    body: LlmOfficialApplyMarkupDTO,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    admin: _facade().User = _facade().Depends(_facade()._require_admin),
):
    prov = body.provider.strip()
    if prov not in _facade().KNOWN_PROVIDERS:
        raise _facade().HTTPException(400, "unknown provider")
    if body.model_ids:
        target_ids = [m.strip() for m in body.model_ids if m and m.strip()]
    else:
        block = await _facade().get_models_for_provider(db, admin.id, prov, force_refresh=False)
        target_ids = [str(x) for x in block.get("models") or [] if x]
    if not target_ids:
        raise _facade().HTTPException(400, "该厂商目录为空")
    markup_val = (
        body.multiplier
        if body.multiplier is not None
        else float(_facade().official_markup_multiplier(db))
    )
    try:
        result = _facade().apply_official_markup_to_rows(
            db, prov, target_ids, _facade().Decimal(str(markup_val))
        )
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e
    db.commit()
    return {"ok": True, **result, "settings": _facade().billing_settings_dict(db)}


@_facade().router.delete("/admin/pricing")
async def llm_admin_disable_pricing(
    provider: str = _facade().Query(..., min_length=2, max_length=64),
    model: str = _facade().Query(..., min_length=1, max_length=256),
    db: _facade().Session = _facade().Depends(_facade().get_db),
    admin: _facade().User = _facade().Depends(_facade()._require_admin),
):
    row = (
        db.query(_facade().AiModelPrice)
        .filter(
            _facade().AiModelPrice.provider == provider.strip(),
            _facade().AiModelPrice.model == model.strip(),
        )
        .first()
    )
    if not row:
        raise _facade().HTTPException(404, "定价记录不存在")
    row.enabled = False
    db.commit()
    return {"ok": True, "provider": row.provider, "model": row.model}


@_facade().router.get("/conversations")
async def llm_conversations(
    limit: int = _facade().Query(30, ge=1, le=100),
    offset: int = _facade().Query(0, ge=0),
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    rows = (
        db.query(_facade().ChatConversation)
        .filter(_facade().ChatConversation.user_id == user.id)
        .order_by(_facade().ChatConversation.updated_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "items": [
            {
                "id": r.id,
                "title": r.title,
                "provider": r.provider,
                "model": r.model,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]
    }
