"""大模型目录、BYOK、偏好与聊天代理 API。"""

from __future__ import annotations

import asyncio
import json
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user, _require_admin
from modstore_server.infrastructure.db import get_db
from modstore_server.llm_billing import (
    JavaWalletClient,
    WalletHold,
    authorization_header,
    billing_settings_dict,
    calculate_charge,
    calculate_image_charge,
    enforce_risk_limits,
    estimate_image_preauthorization,
    estimate_preauthorization,
    estimate_unit_preauthorization,
    get_or_create_billing_settings,
    merge_catalog_pricing,
    new_request_id,
    official_markup_multiplier,
    pricing_public_dict,
    save_failure_log,
    save_image_call_log,
    save_success_log,
    usage_from_response,
)
from modstore_server.llm_catalog import (
    clear_all_catalog_cache,
    get_models_for_provider,
    probe_first_matching_provider,
)
from modstore_server.llm_chat_proxy import chat_dispatch, chat_dispatch_stream, image_dispatch
from modstore_server.llm_crypto import encrypt_secret, fernet_configured
from modstore_server.llm_key_resolver import (
    KNOWN_PROVIDERS,
    OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
    credential_status,
    resolve_api_key,
    resolve_base_url,
)
from modstore_server.llm_model_gates import (
    byok_catalog_gate_enabled,
    merge_catalog_capabilities,
    platform_catalog_gate_enabled,
    platform_require_priced_row,
)
from modstore_server.llm_model_taxonomy import (
    build_models_detailed,
    category_labels_zh,
    media_counts_from_detailed,
)
from modstore_server.llm_official_price_sync import (
    apply_official_markup_to_rows,
    list_official_sources_for_provider,
    sync_official_prices_for_provider,
)
from modstore_server.models import (
    AiModelPrice,
    ChatConversation,
    ChatMessage,
    LlmBillingSettings,
    LlmCallLog,
    User,
    UserLlmCredential,
)
from modstore_server.multimodal_llm import (
    messages_use_openai_multipart_content,
    validate_multimodal_payload_size,
)
from modstore_server.pptx_export import build_pptx_from_markdown

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/llm", tags=["llm"])

_BYOK_PLAN_IDS = {"plan_pro", "plan_enterprise"}


async def resolve_default_llm_route(db: Session, user_id: int) -> dict[str, Any]:
    """与 ``GET /api/llm/resolve-chat-default`` 同源：解析账户默认 vendor + model。"""
    import asyncio

    from modstore_server.models import User as UserModel
    from modstore_server.models import get_session_factory

    uid = int(user_id)

    def _load_prefs_and_keys() -> tuple[str, str, dict[str, str]]:
        sf = get_session_factory()
        with sf() as _db:
            urow = _db.query(UserModel).filter(UserModel.id == uid).first()
            prefs: Dict[str, Any] = {}
            raw = ((urow.default_llm_json if urow else None) or "").strip()
            if raw:
                try:
                    loaded = json.loads(raw)
                    if isinstance(loaded, dict):
                        prefs = loaded
                except json.JSONDecodeError:
                    prefs = {}
            pref_p = str(prefs.get("provider") or "").strip()
            pref_m = str(prefs.get("model") or "").strip()
            keys: dict[str, str] = {}
            for p in KNOWN_PROVIDERS:
                k, _ = resolve_api_key(_db, uid, p)
                if k:
                    keys[p] = k
        return pref_p, pref_m, keys

    pref_p, pref_m, keys = await asyncio.to_thread(_load_prefs_and_keys)

    async def first_model_id(provider: str) -> str:
        block = await get_models_for_provider(db, uid, provider, force_refresh=False)
        mids = list(block.get("models") or [])
        return str(mids[0]).strip() if mids else ""

    if pref_p in KNOWN_PROVIDERS and pref_m and pref_p in keys:
        return {"ok": True, "provider": pref_p, "model": pref_m, "source": "preference"}

    if pref_p in KNOWN_PROVIDERS and pref_p in keys:
        m0 = await first_model_id(pref_p)
        if m0:
            return {"ok": True, "provider": pref_p, "model": m0, "source": "preference_first_model"}

    for p in KNOWN_PROVIDERS:
        if p not in keys:
            continue
        m0 = await first_model_id(p)
        if m0:
            return {"ok": True, "provider": p, "model": m0, "source": "fallback"}

    raise HTTPException(
        400,
        "未配置任何可用 LLM 密钥（平台环境变量或 BYOK）。请在钱包页为至少一个厂商配置密钥，"
        "或将账户默认供应商改为已配置密钥的厂商；若已保存 BYOK，请确认服务端已配置 MODSTORE_LLM_MASTER_KEY。",
    )


async def run_billed_llm_chat(
    request: Request,
    db: Session,
    user: User,
    *,
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: Optional[int] = None,
    conversation_id: Optional[int] = None,
) -> dict[str, Any]:
    """执行一轮 LLM 对话并完成钱包预授权/结算（与 ``POST /api/llm/chat`` 行为一致）。"""
    if provider not in KNOWN_PROVIDERS:
        raise HTTPException(400, "unknown provider")
    api_key, key_source = resolve_api_key(db, user.id, provider)
    if not api_key:
        raise HTTPException(
            400,
            f"供应商「{provider}」未配置可用 API Key（平台环境变量或 BYOK）。"
            f"请在钱包页为该厂商保存密钥，或将默认模型切换到已有密钥的厂商；"
            f"仅配置了其它厂商（如 DeepSeek）时，请把 LLM 默认供应商改为该厂商或切到「自选」。",
        )
    is_byok = key_source == "user_override"
    base = (
        resolve_base_url(db, user.id, provider)
        if provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
        else None
    )
    msgs = messages
    if not msgs:
        raise HTTPException(400, "messages 不能为空")
    size_err = validate_multimodal_payload_size(msgs)
    if size_err:
        raise HTTPException(400, size_err)
    if (
        messages_use_openai_multipart_content(msgs)
        and provider not in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
    ):
        raise HTTPException(
            400,
            "多模态消息仅支持 OpenAI 兼容供应商（含 SiliconFlow、DashScope 等 chat/completions 网关）；"
            "请更换 provider 或改发纯文本。",
        )
    model = model.strip()
    request_id = new_request_id()
    enforce_risk_limits(db, user.id, provider, model, msgs, request)
    wallet = JavaWalletClient()
    if is_byok:
        hold = WalletHold(hold_no=f"byok-{request_id}", amount=Decimal("0"), enabled=False)
    else:
        preauth_amount = estimate_preauthorization(db, provider, model, msgs, max_tokens)
        hold = await wallet.preauthorize(
            authorization_header(request), preauth_amount, provider, model, request_id
        )
    charge = Decimal("0")
    try:
        result = await chat_dispatch(
            provider,
            api_key=api_key,
            base_url=base,
            model=model,
            messages=msgs,
            max_tokens=max_tokens,
        )
        if not result.get("ok"):
            err = result.get("error") or "upstream error"
            save_failure_log(
                db,
                user_id=user.id,
                provider=provider,
                model=model,
                error=str(err),
                hold_no=hold.hold_no,
            )
            raise HTTPException(502, err)
        content = result.get("content", "")
        usage = usage_from_response(result.get("usage") or {}, msgs, content)
        if is_byok:
            charge = Decimal("0")
        else:
            charge = calculate_charge(db, provider, model, usage)
            await wallet.settle(authorization_header(request), hold, charge, request_id)
        conversation_row_id = save_success_log(
            db,
            user_id=user.id,
            provider=provider,
            model=model,
            messages=msgs,
            content=content,
            usage=usage,
            charge=charge,
            hold_no=hold.hold_no,
            conversation_id=conversation_id,
        )
    except HTTPException as exc:
        try:
            await wallet.release(authorization_header(request), hold, str(exc.detail), request_id)
        except Exception:
            logger.exception("failed to release LLM wallet hold")
        raise
    except Exception as exc:
        try:
            save_failure_log(
                db,
                user_id=user.id,
                provider=provider,
                model=model,
                error=str(exc),
                hold_no=hold.hold_no,
            )
            await wallet.release(authorization_header(request), hold, str(exc), request_id)
        except Exception:
            logger.exception("failed to release LLM wallet hold after unexpected error")
        raise
    return {
        "ok": True,
        "content": content,
        "conversation_id": conversation_row_id,
        "usage": usage.__dict__,
        "charge_amount": float(charge),
        "hold_no": hold.hold_no,
        "key_source": key_source,
        "billed": not is_byok,
        "provider": provider,
        "model": model,
        "request_id": request_id,
    }


def _membership_meta(plan_id: str | None) -> Dict[str, Any]:
    pid = (plan_id or "").strip()
    tier_map = {
        "plan_basic": ("basic", "VIP", False),
        "plan_pro": ("pro", "VIP+", True),
        "plan_enterprise": ("enterprise", "svip", True),
    }
    tier, label, can_byok = tier_map.get(pid, ("free", "普通用户", False))
    return {
        "tier": tier,
        "label": label,
        "is_member": bool(pid),
        "can_byok": can_byok,
    }


def _active_plan_id(db: Session, user_id: int) -> str:
    from modstore_server.models import UserPlan

    row = (
        db.query(UserPlan)
        .filter(UserPlan.user_id == user_id, UserPlan.is_active == True)
        .order_by(UserPlan.id.desc())
        .first()
    )
    return str(row.plan_id) if row else ""


def _require_byok_membership(db: Session, user: User) -> None:
    if user.is_admin:
        return
    plan_id = _active_plan_id(db, user.id)
    if plan_id not in _BYOK_PLAN_IDS:
        meta = _membership_meta(plan_id)
        raise HTTPException(
            403,
            f"BYOK 是 VIP+ 及以上能力，当前身份为「{meta['label']}」。请升级会员后再绑定自己的 API Key。",
        )


def _provider_labels() -> Dict[str, str]:
    return {
        "openai": "OpenAI",
        "deepseek": "DeepSeek",
        "anthropic": "Anthropic",
        "google": "Google Gemini",
        "siliconflow": "SiliconFlow",
        "groq": "Groq",
        "together": "Together AI",
        "openrouter": "OpenRouter",
        "dashscope": "阿里云百炼",
        "moonshot": "月之暗面 Kimi",
        "xiaomi": "小米 MiMo",
        "minimax": "MiniMax",
        "doubao": "豆包",
        "wenxin": "百度文心 / 千帆",
        "hunyuan": "腾讯混元",
        "zhipu": "智谱 GLM",
        "xunfei": "讯飞星火",
        "yi": "零一万物",
        "stepfun": "阶跃星辰",
        "baichuan": "百川智能",
        "sensetime": "商汤日日新",
    }


@router.get("/status")
async def llm_status(
    user: User = Depends(_get_current_user),
):
    import asyncio

    from modstore_server.models import get_session_factory

    user_id = int(user.id)

    def _sync_status() -> dict:
        sf = get_session_factory()
        with sf() as db:
            out = []
            for p in KNOWN_PROVIDERS:
                st = credential_status(db, user_id, p)
                st["label"] = _provider_labels().get(p, p)
                out.append(st)
        return {"providers": out, "fernet_configured": fernet_configured()}

    return await asyncio.to_thread(_sync_status)


@router.get("/resolve-chat-default")
async def resolve_chat_default(
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """
    供工作台「自动」模式与需求规划使用：用与 /chat 相同的 resolve_api_key 选出
    provider + model，避免仅依赖前端 /status 与目录推断导致与后端不一致。

    顺序：①账户默认且该厂商有密钥且已填 model；②默认厂商有密钥则取其目录首模；
    ③按 KNOWN_PROVIDERS 顺序第一个「有密钥且能拉到模型 id」的厂商。
    """
    return await resolve_default_llm_route(db, int(user.id))


_CATALOG_PROVIDER_TIMEOUT_SEC = 12.0


async def _fetch_catalog_provider_block(
    user_id: int,
    provider: str,
    *,
    force_refresh: bool,
) -> Dict[str, Any]:
    """单厂商目录块；独立 DB Session，可与其它厂商并行拉取。"""
    from modstore_server.models import get_session_factory

    labels = _provider_labels()
    empty = {
        "provider": provider,
        "label": labels.get(provider, provider),
        "models": [],
        "models_detailed": [],
        "media_counts": media_counts_from_detailed([]),
        "supports_openai_images": provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
        "fetched_at": None,
        "from_cache": False,
    }
    try:
        sf = get_session_factory()
        with sf() as sess:
            block = await asyncio.wait_for(
                get_models_for_provider(sess, user_id, provider, force_refresh=force_refresh),
                timeout=_CATALOG_PROVIDER_TIMEOUT_SEC,
            )
        mids: List[str] = list(block.get("models") or [])
        detailed = build_models_detailed(provider, mids)
        return {
            **empty,
            "models": mids,
            "models_detailed": detailed,
            "media_counts": media_counts_from_detailed(detailed),
            "supports_openai_images": provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
            "fetched_at": block.get("fetched_at"),
            "error": block.get("error"),
            "from_cache": block.get("from_cache", False),
            "fetch_source": block.get("source"),
        }
    except asyncio.TimeoutError:
        return {**empty, "error": "provider_timeout", "fetch_source": "timeout"}
    except Exception as e:  # noqa: BLE001
        logger.exception("llm_catalog provider %s failed", provider)
        return {
            **empty,
            "error": f"internal: {e.__class__.__name__}",
            "fetch_source": "error",
        }


@router.get("/catalog")
async def llm_catalog(
    refresh: int = Query(0, ge=0, le=1),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    force = bool(refresh)
    providers_out = list(
        await asyncio.gather(
            *[
                _fetch_catalog_provider_block(user.id, p, force_refresh=force)
                for p in KNOWN_PROVIDERS
            ]
        )
    )
    prefs: Dict[str, str] = {}
    urow = db.query(User).filter(User.id == user.id).first()
    raw = ((urow.default_llm_json if urow else None) or "").strip()
    if raw:
        try:
            prefs = json.loads(raw)
            if not isinstance(prefs, dict):
                prefs = {}
        except json.JSONDecodeError:
            prefs = {}
    merge_catalog_capabilities(db, providers_out)
    try:
        merge_catalog_pricing(db, providers_out)
    except Exception:
        logger.exception("merge_catalog_pricing failed (catalog still returned without pricing)")
    settings = billing_settings_dict(db)
    return {
        "cache_ttl_seconds": 600,
        "category_labels": category_labels_zh(),
        "providers": providers_out,
        "preferences": {
            "provider": prefs.get("provider") or "openai",
            "model": prefs.get("model") or "",
        },
        "fernet_configured": fernet_configured(),
        "gate_hints": {
            "platform_catalog_gate": platform_catalog_gate_enabled(),
            "byok_catalog_gate": byok_catalog_gate_enabled(),
            "platform_require_priced": platform_require_priced_row(),
        },
        "billing_settings": settings,
    }


class LlmCredentialDTO(BaseModel):
    api_key: str = Field(..., min_length=4, max_length=4096)
    base_url: Optional[str] = Field(None, max_length=2048)


class LlmBareKeyDetectDTO(BaseModel):
    """无标签裸密钥：在已知厂商上并行试拉 /models，命中后再入库。"""

    api_key: str = Field(..., min_length=8, max_length=4096)


@router.post("/credentials/detect-bare")
async def post_detect_bare_credential(
    body: LlmBareKeyDetectDTO,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    _require_byok_membership(db, user)
    if not fernet_configured():
        raise HTTPException(503, "服务端未配置 MODSTORE_LLM_MASTER_KEY，无法保存 BYOK")
    key = body.api_key.strip()
    if not key:
        raise HTTPException(400, "api_key 为空")
    provider = await probe_first_matching_provider(key)
    if not provider:
        raise HTTPException(
            400,
            "无法在已知厂商中通过拉取模型列表验证该密钥。请改用手动格式："
            "厂商id=密钥（如 deepseek=sk-…）或环境变量名（如 OPENAI_API_KEY=…）。",
        )
    try:
        enc_key = encrypt_secret(key)
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e

    row = (
        db.query(UserLlmCredential)
        .filter(UserLlmCredential.user_id == user.id, UserLlmCredential.provider == provider)
        .first()
    )
    if row:
        row.api_key_encrypted = enc_key
        row.base_url_encrypted = None
    else:
        row = UserLlmCredential(
            user_id=user.id,
            provider=provider,
            api_key_encrypted=enc_key,
            base_url_encrypted=None,
        )
        db.add(row)
    db.commit()
    clear_all_catalog_cache()
    label = _provider_labels().get(provider, provider)
    return {"ok": True, "provider": provider, "message": f"已识别为「{label}」并保存"}


@router.put("/credentials/{provider}")
async def put_llm_credentials(
    provider: str,
    body: LlmCredentialDTO,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    if provider not in KNOWN_PROVIDERS:
        raise HTTPException(400, "unknown provider")
    _require_byok_membership(db, user)
    if not fernet_configured():
        raise HTTPException(503, "服务端未配置 MODSTORE_LLM_MASTER_KEY，无法保存 BYOK")
    key = body.api_key.strip()
    if not key:
        raise HTTPException(400, "api_key 为空")
    bu = (body.base_url or "").strip() or None
    try:
        enc_key = encrypt_secret(key)
        enc_base = encrypt_secret(bu) if bu else None
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e

    row = (
        db.query(UserLlmCredential)
        .filter(UserLlmCredential.user_id == user.id, UserLlmCredential.provider == provider)
        .first()
    )
    if row:
        row.api_key_encrypted = enc_key
        row.base_url_encrypted = enc_base
    else:
        row = UserLlmCredential(
            user_id=user.id,
            provider=provider,
            api_key_encrypted=enc_key,
            base_url_encrypted=enc_base,
        )
        db.add(row)
    db.commit()
    clear_all_catalog_cache()
    return {"ok": True, "provider": provider}


@router.delete("/credentials/{provider}")
async def delete_llm_credentials(
    provider: str,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    if provider not in KNOWN_PROVIDERS:
        raise HTTPException(400, "unknown provider")
    row = (
        db.query(UserLlmCredential)
        .filter(UserLlmCredential.user_id == user.id, UserLlmCredential.provider == provider)
        .first()
    )
    if row:
        db.delete(row)
        db.commit()
        clear_all_catalog_cache()
    return {"ok": True}


class LlmPreferenceDTO(BaseModel):
    provider: str = Field(..., min_length=2, max_length=32)
    model: str = Field(..., min_length=1, max_length=256)


class LlmPriceDTO(BaseModel):
    provider: str = Field(..., min_length=2, max_length=64)
    model: str = Field(..., min_length=1, max_length=256)
    label: str = ""
    input_price_per_1k: float = Field(0.006, ge=0)
    output_price_per_1k: float = Field(0.018, ge=0)
    min_charge: float = Field(0.02, ge=0)
    enabled: bool = True


@router.put("/preferences")
async def put_llm_preferences(
    body: LlmPreferenceDTO,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    if body.provider not in KNOWN_PROVIDERS:
        raise HTTPException(400, "unknown provider")
    u = db.query(User).filter(User.id == user.id).first()
    if not u:
        raise HTTPException(401, "用户不存在")
    u.default_llm_json = json.dumps(
        {"provider": body.provider, "model": body.model.strip()}, ensure_ascii=False
    )
    db.commit()
    return {"ok": True, "preferences": json.loads(u.default_llm_json)}


def _price_row_to_dict(r: AiModelPrice) -> Dict[str, Any]:
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


def _upsert_ai_model_price(db: Session, body: LlmPriceDTO) -> AiModelPrice:
    row = (
        db.query(AiModelPrice)
        .filter(
            AiModelPrice.provider == body.provider.strip(), AiModelPrice.model == body.model.strip()
        )
        .first()
    )
    if not row:
        row = AiModelPrice(provider=body.provider.strip(), model=body.model.strip())
        db.add(row)
    row.label = body.label.strip()
    row.input_price_per_1k = float(body.input_price_per_1k)
    row.output_price_per_1k = float(body.output_price_per_1k)
    row.min_charge = float(body.min_charge)
    row.enabled = bool(body.enabled)
    return row


@router.get("/pricing")
async def llm_pricing(
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    settings = billing_settings_dict(db)
    rows = db.query(AiModelPrice).filter(AiModelPrice.enabled == True).all()
    return {
        **settings,
        "items": [
            {
                **_price_row_to_dict(r),
                **pricing_public_dict(db, r.provider, r.model, priced_row=r),
            }
            for r in rows
        ],
    }


@router.get("/admin/pricing")
async def llm_admin_list_pricing(
    provider: Optional[str] = Query(None, max_length=64),
    q: Optional[str] = Query(None, max_length=128),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
):
    query = db.query(AiModelPrice)
    if provider:
        query = query.filter(AiModelPrice.provider == provider.strip())
    if q:
        like = f"%{q.strip()}%"
        query = query.filter((AiModelPrice.model.ilike(like)) | (AiModelPrice.label.ilike(like)))
    total = query.count()
    rows = (
        query.order_by(AiModelPrice.provider.asc(), AiModelPrice.model.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "ok": True,
        "total": total,
        "items": [_price_row_to_dict(r) for r in rows],
        "settings": billing_settings_dict(db),
    }


@router.put("/admin/pricing")
async def llm_admin_put_price(
    body: LlmPriceDTO,
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
):
    row = _upsert_ai_model_price(db, body)
    db.commit()
    return {
        "ok": True,
        "provider": row.provider,
        "model": row.model,
        "item": _price_row_to_dict(row),
    }


class LlmBillingSettingsDTO(BaseModel):
    service_fee_multiplier: Optional[float] = Field(None, ge=1, le=10)
    official_markup_multiplier: Optional[float] = Field(None, ge=1, le=10)
    default_input_price_per_1k: Optional[float] = Field(None, ge=0)
    default_output_price_per_1k: Optional[float] = Field(None, ge=0)
    default_min_charge: Optional[float] = Field(None, ge=0)


@router.put("/admin/pricing/settings")
async def llm_admin_put_pricing_settings(
    body: LlmBillingSettingsDTO,
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
):
    row = get_or_create_billing_settings(db)
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
    return {"ok": True, "settings": billing_settings_dict(db)}


class LlmPriceBatchTemplateDTO(BaseModel):
    input_price_per_1k: float = Field(0.006, ge=0)
    output_price_per_1k: float = Field(0.018, ge=0)
    min_charge: float = Field(0.02, ge=0)
    label_prefix: str = ""


class LlmPriceBatchDTO(BaseModel):
    provider: str = Field(..., min_length=2, max_length=64)
    mode: str = Field("unpriced_only", pattern="^(unpriced_only|all_catalog)$")
    model_ids: Optional[List[str]] = None
    template: LlmPriceBatchTemplateDTO = Field(default_factory=LlmPriceBatchTemplateDTO)


@router.post("/admin/pricing/batch")
async def llm_admin_batch_pricing(
    body: LlmPriceBatchDTO,
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
):
    prov = body.provider.strip()
    if prov not in KNOWN_PROVIDERS:
        raise HTTPException(400, "unknown provider")
    if body.model_ids:
        target_ids = [m.strip() for m in body.model_ids if m and m.strip()]
    else:
        block = await get_models_for_provider(db, admin.id, prov, force_refresh=False)
        target_ids = [str(x) for x in (block.get("models") or []) if x]
    if not target_ids:
        raise HTTPException(400, "该厂商目录为空，请先刷新模型列表")
    existing = {
        (r.provider, r.model)
        for r in db.query(AiModelPrice).filter(AiModelPrice.provider == prov).all()
    }
    tpl = body.template
    written = 0
    for mid in target_ids:
        if body.mode == "unpriced_only" and (prov, mid) in existing:
            continue
        label = f"{tpl.label_prefix}{mid}".strip() if tpl.label_prefix else mid
        _upsert_ai_model_price(
            db,
            LlmPriceDTO(
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


class LlmOfficialSyncDTO(BaseModel):
    provider: str = Field(..., min_length=2, max_length=64)
    model_ids: Optional[List[str]] = None
    sources: Optional[List[str]] = Field(default_factory=lambda: ["curated", "openrouter"])
    apply_markup: bool = False


@router.get("/admin/pricing/official-sources")
async def llm_admin_official_sources(
    provider: str = Query(..., min_length=2, max_length=64),
    admin: User = Depends(_require_admin),
):
    if provider.strip() not in KNOWN_PROVIDERS:
        raise HTTPException(400, "unknown provider")
    return {"ok": True, **list_official_sources_for_provider(provider.strip())}


@router.post("/admin/pricing/sync-official")
async def llm_admin_sync_official_prices(
    body: LlmOfficialSyncDTO,
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
):
    prov = body.provider.strip()
    if prov not in KNOWN_PROVIDERS:
        raise HTTPException(400, "unknown provider")
    if body.model_ids:
        target_ids = [m.strip() for m in body.model_ids if m and m.strip()]
    else:
        block = await get_models_for_provider(db, admin.id, prov, force_refresh=False)
        target_ids = [str(x) for x in (block.get("models") or []) if x]
    if not target_ids:
        raise HTTPException(400, "该厂商目录为空，请先刷新模型列表")
    result = await sync_official_prices_for_provider(db, prov, target_ids, sources=body.sources)
    if body.apply_markup:
        markup = official_markup_multiplier(db)
        apply_result = apply_official_markup_to_rows(db, prov, target_ids, markup)
        result["apply_markup"] = apply_result
    db.commit()
    return {"ok": True, **result}


class LlmOfficialApplyMarkupDTO(BaseModel):
    provider: str = Field(..., min_length=2, max_length=64)
    model_ids: Optional[List[str]] = None
    multiplier: Optional[float] = Field(None, ge=1, le=10)


@router.post("/admin/pricing/apply-official-markup")
async def llm_admin_apply_official_markup(
    body: LlmOfficialApplyMarkupDTO,
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
):
    prov = body.provider.strip()
    if prov not in KNOWN_PROVIDERS:
        raise HTTPException(400, "unknown provider")
    if body.model_ids:
        target_ids = [m.strip() for m in body.model_ids if m and m.strip()]
    else:
        block = await get_models_for_provider(db, admin.id, prov, force_refresh=False)
        target_ids = [str(x) for x in (block.get("models") or []) if x]
    if not target_ids:
        raise HTTPException(400, "该厂商目录为空")
    markup_val = (
        body.multiplier if body.multiplier is not None else float(official_markup_multiplier(db))
    )
    try:
        result = apply_official_markup_to_rows(db, prov, target_ids, Decimal(str(markup_val)))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    db.commit()
    return {"ok": True, **result, "settings": billing_settings_dict(db)}


@router.delete("/admin/pricing")
async def llm_admin_disable_pricing(
    provider: str = Query(..., min_length=2, max_length=64),
    model: str = Query(..., min_length=1, max_length=256),
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
):
    row = (
        db.query(AiModelPrice)
        .filter(AiModelPrice.provider == provider.strip(), AiModelPrice.model == model.strip())
        .first()
    )
    if not row:
        raise HTTPException(404, "定价记录不存在")
    row.enabled = False
    db.commit()
    return {"ok": True, "provider": row.provider, "model": row.model}


@router.get("/conversations")
async def llm_conversations(
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    rows = (
        db.query(ChatConversation)
        .filter(ChatConversation.user_id == user.id)
        .order_by(ChatConversation.updated_at.desc())
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


@router.get("/conversations/{conversation_id}")
async def llm_conversation_detail(
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    row = (
        db.query(ChatConversation)
        .filter(ChatConversation.id == conversation_id, ChatConversation.user_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(404, "对话不存在")
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.conversation_id == row.id, ChatMessage.user_id == user.id)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .all()
    )
    return {
        "id": row.id,
        "title": row.title,
        "provider": row.provider,
        "model": row.model,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "usage": json.loads(m.usage_json or "{}"),
                "charge_amount": float(m.charge_amount or 0),
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }


@router.get("/usage")
async def llm_usage(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    rows = (
        db.query(LlmCallLog)
        .filter(LlmCallLog.user_id == user.id)
        .order_by(LlmCallLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "items": [
            {
                "id": r.id,
                "provider": r.provider,
                "model": r.model,
                "status": r.status,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "total_tokens": r.total_tokens,
                "estimated": bool(r.estimated),
                "charge_amount": float(r.charge_amount or 0),
                "hold_no": r.hold_no,
                "error": r.error,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


class ChatMessageDTO(BaseModel):
    """``content`` 可为纯文本或 OpenAI vision 多段格式（``type: text|image_url`` 数组）。"""

    role: str
    content: Union[str, List[Dict[str, Any]]]


class LlmChatDTO(BaseModel):
    provider: str
    model: str
    messages: List[ChatMessageDTO]
    max_tokens: Optional[int] = Field(None, ge=1, le=32000)
    conversation_id: Optional[int] = Field(None, ge=1)


class LlmImageDTO(BaseModel):
    provider: str
    model: str = "gpt-image-1"
    prompt: str = Field(..., min_length=1, max_length=4000)
    size: str = Field("1024x1024", max_length=32)
    n: int = Field(1, ge=1, le=4)


class LlmPptxDTO(BaseModel):
    title: str = Field("AI 生成 PPT", max_length=120)
    markdown: str = Field(..., min_length=1, max_length=60000)
    filename: str = Field("ai-presentation.pptx", max_length=160)


@router.post("/chat")
async def llm_chat(
    request: Request,
    body: LlmChatDTO,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    msgs = [{"role": m.role, "content": m.content} for m in body.messages]
    out = await run_billed_llm_chat(
        request,
        db,
        user,
        provider=body.provider,
        model=body.model.strip(),
        messages=msgs,
        max_tokens=body.max_tokens,
        conversation_id=body.conversation_id,
    )
    return {
        "ok": out["ok"],
        "content": out["content"],
        "conversation_id": out["conversation_id"],
        "usage": out["usage"],
        "charge_amount": out["charge_amount"],
        "hold_no": out["hold_no"],
        "key_source": out["key_source"],
        "billed": out["billed"],
    }


def _sse(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
async def llm_chat_stream(
    request: Request,
    body: LlmChatDTO,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    if body.provider not in KNOWN_PROVIDERS:
        raise HTTPException(400, "unknown provider")
    api_key, key_source = resolve_api_key(db, user.id, body.provider)
    if not api_key:
        raise HTTPException(
            400,
            f"供应商「{body.provider}」未配置可用 API Key（平台环境变量或 BYOK）。",
        )
    is_byok = key_source == "user_override"
    base = (
        resolve_base_url(db, user.id, body.provider)
        if body.provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
        else None
    )
    msgs = [{"role": m.role, "content": m.content} for m in body.messages]
    if not msgs:
        raise HTTPException(400, "messages 不能为空")
    size_err = validate_multimodal_payload_size(msgs)
    if size_err:
        raise HTTPException(400, size_err)
    if (
        messages_use_openai_multipart_content(msgs)
        and body.provider not in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
    ):
        raise HTTPException(
            400,
            "多模态消息仅支持 OpenAI 兼容供应商；请更换 provider 或改发纯文本。",
        )
    model = body.model.strip()
    request_id = new_request_id()
    enforce_risk_limits(db, user.id, body.provider, model, msgs, request)
    wallet = JavaWalletClient()
    if is_byok:
        hold = WalletHold(hold_no=f"byok-{request_id}", amount=Decimal("0"), enabled=False)
    else:
        preauth_amount = estimate_preauthorization(db, body.provider, model, msgs, body.max_tokens)
        hold = await wallet.preauthorize(
            authorization_header(request), preauth_amount, body.provider, model, request_id
        )

    async def gen():
        parts: List[str] = []
        upstream_usage: Dict[str, Any] = {}
        try:
            yield _sse(
                "meta",
                {
                    "ok": True,
                    "request_id": request_id,
                    "hold_no": hold.hold_no,
                    "key_source": key_source,
                    "billed": not is_byok,
                },
            )
            async for ev in chat_dispatch_stream(
                body.provider,
                api_key=api_key,
                base_url=base,
                model=model,
                messages=msgs,
                max_tokens=body.max_tokens,
            ):
                if ev.get("type") == "error":
                    err = ev.get("error") or "upstream error"
                    save_failure_log(
                        db,
                        user_id=user.id,
                        provider=body.provider,
                        model=model,
                        error=str(err),
                        hold_no=hold.hold_no,
                    )
                    try:
                        await wallet.release(
                            authorization_header(request), hold, str(err), request_id
                        )
                    except Exception:
                        logger.exception(
                            "failed to release LLM wallet hold after stream upstream error"
                        )
                    yield _sse(
                        "error", {"ok": False, "error": str(err), "status": ev.get("status")}
                    )
                    return
                if ev.get("type") == "usage":
                    upstream_usage = ev.get("usage") or {}
                    continue
                if ev.get("type") == "delta":
                    delta = str(ev.get("delta") or "")
                    if delta:
                        parts.append(delta)
                        yield _sse("delta", {"delta": delta})
            content = "".join(parts)
            usage = usage_from_response(upstream_usage, msgs, content)
            if is_byok:
                charge = Decimal("0")
            else:
                charge = calculate_charge(db, body.provider, model, usage)
                await wallet.settle(authorization_header(request), hold, charge, request_id)
            conversation_id = save_success_log(
                db,
                user_id=user.id,
                provider=body.provider,
                model=model,
                messages=msgs,
                content=content,
                usage=usage,
                charge=charge,
                hold_no=hold.hold_no,
                conversation_id=body.conversation_id,
            )
            yield _sse(
                "done",
                {
                    "ok": True,
                    "content": content,
                    "conversation_id": conversation_id,
                    "usage": usage.__dict__,
                    "charge_amount": float(charge),
                    "hold_no": hold.hold_no,
                    "key_source": key_source,
                    "billed": not is_byok,
                },
            )
        except Exception as exc:
            try:
                save_failure_log(
                    db,
                    user_id=user.id,
                    provider=body.provider,
                    model=model,
                    error=str(exc),
                    hold_no=hold.hold_no,
                )
                await wallet.release(authorization_header(request), hold, str(exc), request_id)
            except Exception:
                logger.exception("failed to release LLM wallet hold after unexpected stream error")
            yield _sse("error", {"ok": False, "error": str(exc)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/image")
async def llm_image(
    request: Request,
    body: LlmImageDTO,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """文生图：经统一钱包预授权/结算（image 模态按张计费）。
    与 run_billed_llm_chat 同构：BYOK 跳过计费；上游失败释放冻结。"""
    if body.provider not in KNOWN_PROVIDERS:
        raise HTTPException(400, "unknown provider")
    provider = body.provider
    api_key, key_source = resolve_api_key(db, user.id, provider)
    if not api_key:
        raise HTTPException(
            400,
            f"供应商「{provider}」未配置可用 API Key（平台环境变量或 BYOK）。"
            f"请在「资金与记录 → 大模型 API」为该厂商保存生图密钥，或切换到已配置的生图厂商。",
        )
    is_byok = key_source == "user_override"
    base = (
        resolve_base_url(db, user.id, provider)
        if provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
        else None
    )
    model = body.model.strip() or "gpt-image-1"
    prompt = body.prompt.strip()
    size = body.size.strip() or "1024x1024"
    n = body.n
    request_id = new_request_id()
    # 复用对话同款风控（频次/内容），用合成消息承载提示词。
    enforce_risk_limits(
        db, user.id, provider, model, [{"role": "user", "content": prompt}], request
    )

    wallet = JavaWalletClient()
    if is_byok:
        # BYOK：用户自有密钥，平台不代收费用，跳过钱包预授权/结算。
        hold = WalletHold(hold_no=f"byok-{request_id}", amount=Decimal("0"), enabled=False)
    else:
        preauth_amount = estimate_image_preauthorization(db, provider, model, n)
        hold = await wallet.preauthorize(
            authorization_header(request), preauth_amount, provider, model, request_id
        )

    charge = Decimal("0")
    try:
        result = await image_dispatch(
            provider,
            api_key=api_key,
            base_url=base,
            model=model,
            prompt=prompt,
            size=size,
            n=n,
        )
        if not result.get("ok"):
            err = result.get("error") or "image upstream error"
            save_failure_log(
                db,
                user_id=user.id,
                provider=provider,
                model=model,
                error=str(err),
                hold_no=hold.hold_no,
            )
            raise HTTPException(502, err)
        images = result.get("images") or []
        billed_count = len(images) or n  # 按实际产出张数结算，无产出时回退请求张数
        if is_byok:
            charge = Decimal("0")
        else:
            charge = calculate_image_charge(db, provider, model, billed_count)
            await wallet.settle(authorization_header(request), hold, charge, request_id)
        save_image_call_log(
            db,
            user_id=user.id,
            provider=provider,
            model=model,
            count=billed_count,
            charge=charge,
            hold_no=hold.hold_no,
        )
    except HTTPException as exc:
        try:
            await wallet.release(authorization_header(request), hold, str(exc.detail), request_id)
        except Exception:
            logger.exception("failed to release image wallet hold")
        raise
    except Exception as exc:
        try:
            save_failure_log(
                db,
                user_id=user.id,
                provider=provider,
                model=model,
                error=str(exc),
                hold_no=hold.hold_no,
            )
            await wallet.release(authorization_header(request), hold, str(exc), request_id)
        except Exception:
            logger.exception("failed to release image wallet hold after unexpected error")
        raise

    return {
        "ok": True,
        "images": images,
        "provider": provider,
        "model": model,
        "key_source": key_source,
        "charge_amount": float(charge),
        "billed": not is_byok,
        "hold_no": hold.hold_no,
        "request_id": request_id,
    }


@router.post("/pptx")
async def llm_pptx(body: LlmPptxDTO, user: User = Depends(_get_current_user)):
    # 仅要求登录，内容来自用户当前生成的大纲；不额外消耗模型。
    try:
        blob = build_pptx_from_markdown(body.markdown, title=body.title)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    filename = (
        (body.filename or "ai-presentation.pptx").strip().replace("\\", "_").replace("/", "_")
    )
    if not filename.lower().endswith(".pptx"):
        filename += ".pptx"
    quoted = quote(filename)
    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"},
    )
