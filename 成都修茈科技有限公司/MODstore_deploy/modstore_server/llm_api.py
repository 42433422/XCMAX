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
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user, _require_admin
from modstore_server.infrastructure.db import get_db
from modstore_server.llm_billed_chat import run_billed_llm_chat, stream_billed_llm_chat
from modstore_server.llm_billing import (
    JavaWalletClient,
    WalletHold,
    authorization_header,
    billing_settings_dict,
    calculate_charge,
    enforce_risk_limits,
    estimate_preauthorization,
    get_or_create_billing_settings,
    merge_catalog_pricing,
    new_request_id,
    official_markup_multiplier,
    pricing_public_dict,
    save_failure_log,
    save_success_log,
    usage_from_response,
)
from modstore_server.llm_catalog import (
    clear_all_catalog_cache,
    get_models_for_provider,
    probe_first_matching_provider,
)
from modstore_server.llm_chat_proxy import (
    chat_dispatch,
    chat_dispatch_stream,
    image_dispatch,
    video_dispatch,
)
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


from modstore_server.operational_errors import RECOVERABLE_ERRORS


async def resolve_default_llm_route(
    db: Session,
    user_id: int,
    *,
    provider: str = "",
    model: str = "",
    platform_only: bool = False,
) -> dict[str, Any]:
    """Resolve a chat-capable route and bind its credentials before any catalog await."""
    import asyncio

    from modstore_server.llm_catalog import get_models_for_credentials
    from modstore_server.llm_key_resolver import (
        chat_route_snapshot,
        chat_route_token,
        platform_credentials,
        resolve_credentials,
    )
    from modstore_server.llm_model_taxonomy import classify_model
    from modstore_server.models import User as UserModel
    from modstore_server.models import get_session_factory
    from modstore_server.platform_model_config import read_state

    uid = int(user_id)

    def invalid(message: str, code: str = "INVALID_CHAT_PREFERENCE"):
        raise HTTPException(
            400,
            {
                "code": code,
                "message": message,
                "recovery": (
                    "choose_chat_model_or_follow_platform"
                    if code in {"INVALID_CHAT_PREFERENCE", "NO_BYOK_CHAT_MODEL"}
                    else None
                ),
            },
        )

    if platform_only and (provider or model):
        invalid("平台模式不能同时指定个人供应商或模型", "PLATFORM_ROUTE_CONFLICT")

    def load():
        state = read_state()
        if platform_only:
            return {"mode": "platform"}, {}, state
        with get_session_factory()() as session:
            urow = session.query(UserModel).filter(UserModel.id == uid).first()
            try:
                prefs = json.loads((urow.default_llm_json if urow else None) or "{}")
            except (ValueError, TypeError):
                prefs = {}
            if not isinstance(prefs, dict):
                prefs = {}
            credentials = {
                p: resolve_credentials(session, uid, p, platform_state=state)
                for p in KNOWN_PROVIDERS
            }
        return prefs, credentials, state

    prefs, credentials, state = await asyncio.to_thread(load)
    explicit_query = bool(provider or model)
    mode = "explicit" if explicit_query else str(prefs.get("mode") or "")
    pref_p = (
        provider.strip().lower()
        if explicit_query
        else str(prefs.get("provider") or "").strip().lower()
    )
    pref_m = model.strip() if explicit_query else str(prefs.get("model") or "").strip()
    explicit = bool(provider or model or (mode != "platform" and (pref_p or pref_m)))

    async def select(p: str, m: str, source: str, *, platform_only: bool = False):
        key, base, key_source = credentials.get(p, (None, None, "none"))
        if platform_only:
            key, base = platform_credentials(p, state=state)
            key_source = "platform" if key else "none"
        if not key:
            return None
        if m:
            if classify_model(p, m) not in {"llm", "vlm"}:
                if platform_only:
                    invalid(
                        "平台默认模型不支持聊天，请管理员配置聊天模型",
                        "INVALID_PLATFORM_CHAT_MODEL",
                    )
                invalid("所选模型不支持聊天，请选择聊天模型或明确恢复跟随平台")
        else:
            block = await get_models_for_credentials(
                uid, p, api_key=key, base_url=base, force_refresh=False
            )
            # Empty runtime_models is authoritative: never fall back to the full catalog.
            mids = block.get("runtime_models")
            if mids is None:
                mids = [
                    r["id"]
                    for r in block.get("models_detailed", [])
                    if r.get("runtime_selectable") is True
                ]
            m = next(
                (str(mid).strip() for mid in mids if classify_model(p, str(mid)) in {"llm", "vlm"}),
                "",
            )
            if not m:
                return None
        snapshot = chat_route_snapshot(p, m, key, base, key_source, source)
        return {
            "ok": True,
            **snapshot.public_metadata(),
            "source": source,
            "route_token": chat_route_token(snapshot, uid),
        }

    if explicit:
        if pref_p not in KNOWN_PROVIDERS:
            invalid("账户默认供应商无效，请重新选择聊天模型或跟随平台")
        if mode == "byok" and credentials[pref_p][2] != "user_override":
            invalid("所选 BYOK 不可用，未切换到收费平台", "NO_BYOK_CHAT_MODEL")
        selected = await select(pref_p, pref_m, "explicit" if provider else "preference")
        if selected:
            return selected
        invalid("账户所选供应商没有可用聊天模型或密钥，请重新选择；未切换到收费平台")
    byok = [p for p, (_, _, source) in credentials.items() if source == "user_override"]
    if mode != "platform" and byok:
        for p in byok:
            selected = await select(p, "", "byok")
            if selected:
                return selected
        invalid(
            "BYOK 未提供可用聊天模型，请选择其他 BYOK 模型或明确恢复跟随平台", "NO_BYOK_CHAT_MODEL"
        )
    configured = state["providers"].get(state.get("default_provider"))
    if configured:
        selected = await select(
            configured["provider"],
            configured["model"],
            "platform_configuration",
            platform_only=True,
        )
        if selected:
            return selected
    for p in KNOWN_PROVIDERS:
        selected = await select(p, "", "fallback", platform_only=True)
        if selected:
            return selected
    if platform_only:
        invalid("没有可用的平台聊天模型，请联系管理员配置平台模型", "NO_PLATFORM_CHAT_MODEL")
    invalid("没有可用的聊天模型，请联系管理员配置聊天模型或配置 BYOK", "NO_CHAT_MODEL")


def _membership_meta(plan_id: str | None) -> Dict[str, Any]:
    pid = (plan_id or "").strip()
    tier_map = {
        "plan_basic": ("basic", "VIP", False),
        "plan_pro": ("pro", "VIP+", True),
        "plan_enterprise": ("enterprise", "svip", True),
    }
    tier, label, can_byok = tier_map.get(pid, ("free", "普通用户", False))
    return {"tier": tier, "label": label, "is_member": bool(pid), "can_byok": can_byok}


def _active_plan_id(db: Session, user_id: int) -> str:
    from modstore_server.models import UserPlan

    row = (
        db.query(UserPlan)
        .filter(UserPlan.user_id == user_id, UserPlan.is_active.is_(True))
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
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
    provider: str = "",
    model: str = "",
    platform_only: bool = False,
):
    """Resolve account selection (or an explicit route) with a short-lived tool-round snapshot."""
    response.headers["Cache-Control"] = "no-store"
    return await resolve_default_llm_route(
        db, int(user.id), provider=provider, model=model, platform_only=platform_only
    )


def _read_catalog_credentials(user_id: int, provider: str):
    from modstore_server.llm_catalog import resolve_catalog_credentials
    from modstore_server.models import get_session_factory

    with get_session_factory()() as session:
        return resolve_catalog_credentials(session, user_id, provider)


async def _fetch_catalog_provider_block(
    user_id: int, provider: str, *, force_refresh: bool
) -> Dict[str, Any]:
    """Fetch providers concurrently without holding database connections across awaits."""
    from modstore_server.llm_catalog import get_models_for_credentials

    labels = _provider_labels()
    empty = {
        "provider": provider,
        "label": labels.get(provider, provider),
        "models": [],
        "models_detailed": [],
        "runtime_models": [],
        "media_counts": media_counts_from_detailed([]),
        "supports_openai_images": provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
        "fetched_at": None,
        "from_cache": False,
    }
    try:
        async with asyncio.timeout(_CATALOG_PROVIDER_TIMEOUT_SEC):
            api_key, base_url = await asyncio.to_thread(
                _read_catalog_credentials, user_id, provider
            )
            block = await get_models_for_credentials(
                user_id,
                provider,
                api_key=api_key,
                base_url=base_url,
                force_refresh=force_refresh,
            )
        mids: List[str] = list(block.get("models") or [])
        detailed = list(block.get("models_detailed") or [])
        if not detailed:
            detailed = build_models_detailed(provider, mids)
        return {
            **empty,
            "models": mids,
            "models_detailed": detailed,
            "runtime_models": list(block.get("runtime_models") or []),
            "media_counts": media_counts_from_detailed(detailed),
            "supports_openai_images": provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
            "fetched_at": block.get("fetched_at"),
            "error": block.get("error"),
            "from_cache": block.get("from_cache", False),
            "fetch_source": block.get("source"),
        }
    except asyncio.TimeoutError:
        return {**empty, "error": "provider_timeout", "fetch_source": "timeout"}
    except RECOVERABLE_ERRORS as e:
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
    except RECOVERABLE_ERRORS:
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


class PlatformRuntimeRouteDTO(BaseModel):
    provider: str = Field(..., min_length=2, max_length=64)
    model: str = Field(..., min_length=1, max_length=256)
    reason: str = Field("", max_length=1000)
    refresh_catalog: bool = False
    force: bool = False


class PlatformRuntimeRollbackDTO(BaseModel):
    reason: str = Field("", max_length=1000)
    force: bool = False


@router.get("/admin/runtime-route")
async def get_platform_runtime_route(
    admin: User = Depends(_require_admin),
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


@router.get("/admin/runtime-route/catalog")
async def get_platform_runtime_route_catalog(
    provider: Optional[str] = Query(None, max_length=64),
    refresh: int = Query(0, ge=0, le=1),
    admin: User = Depends(_require_admin),
):
    """Selectable models from the same source as ``GET /api/llm/catalog``."""
    from modstore_server.llm_runtime_route import platform_model_catalog

    _ = admin
    result = await platform_model_catalog(provider, refresh=bool(refresh))
    if not result.get("ok"):
        raise HTTPException(400, str(result.get("error") or "catalog failed"))
    return result


@router.get("/admin/runtime-route/quota")
async def get_platform_runtime_route_quota(
    live_probe: int = Query(0, ge=0, le=1),
    admin: User = Depends(_require_admin),
):
    """Secret-safe provider quota and usage status for the admin control plane."""
    from modstore_server.llm_quota_monitor import platform_quota_snapshot

    result = await platform_quota_snapshot(live_probe=bool(live_probe))
    result["scope"] = "platform_ai_employees"
    result["actor"] = f"admin:{admin.id}"
    return result


@router.get("/admin/runtime-route/autopilot")
async def get_platform_runtime_route_autopilot(
    admin: User = Depends(_require_admin),
):
    """Read-only autopilot policy and latest decision receipt."""
    from modstore_server.llm_runtime_autopilot import autopilot_status

    result = autopilot_status()
    result["scope"] = "platform_ai_employees"
    result["actor"] = f"admin:{admin.id}"
    return result


@router.put("/admin/runtime-route")
async def put_platform_runtime_route(
    body: PlatformRuntimeRouteDTO,
    admin: User = Depends(_require_admin),
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
        raise HTTPException(400, detail=result)
    return result


@router.post("/admin/runtime-route/rollback")
async def post_platform_runtime_route_rollback(
    body: PlatformRuntimeRollbackDTO,
    admin: User = Depends(_require_admin),
):
    from modstore_server.llm_runtime_route import rollback_runtime_route

    result = await rollback_runtime_route(
        actor=f"admin:{admin.id}", reason=body.reason, force=body.force
    )
    if not result.get("ok"):
        raise HTTPException(400, detail=result)
    return result


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
            "无法在已知厂商中通过拉取模型列表验证该密钥。请改用手动格式：厂商id=密钥（如 deepseek=sk-…）或环境变量名（如 OPENAI_API_KEY=…）。",
        )
    try:
        enc_key = encrypt_secret(key)
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    row = (
        db.query(UserLlmCredential)
        .filter(
            UserLlmCredential.user_id == user.id,
            UserLlmCredential.provider == provider,
        )
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
        .filter(
            UserLlmCredential.user_id == user.id,
            UserLlmCredential.provider == provider,
        )
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
        .filter(
            UserLlmCredential.user_id == user.id,
            UserLlmCredential.provider == provider,
        )
        .first()
    )
    if row:
        db.delete(row)
        db.commit()
        clear_all_catalog_cache()
    return {"ok": True}


class LlmPreferenceDTO(BaseModel):
    provider: str = Field("", max_length=32)
    model: str = Field("", max_length=256)
    mode: str | None = None


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
    if body.mode not in {None, "platform", "explicit", "byok"}:
        raise HTTPException(400, "unknown selection mode")
    if body.mode != "platform" and body.provider not in KNOWN_PROVIDERS:
        raise HTTPException(400, "unknown provider")
    if body.mode != "platform" and not body.model.strip() and body.mode != "byok":
        raise HTTPException(400, "model is required")
    u = db.query(User).filter(User.id == user.id).first()
    if not u:
        raise HTTPException(401, "用户不存在")
    u.default_llm_json = json.dumps(
        (
            {"mode": "platform"}
            if body.mode == "platform"
            else {
                "provider": body.provider,
                "model": body.model.strip(),
                "mode": body.mode or "explicit",
            }
        ),
        ensure_ascii=False,
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
            AiModelPrice.provider == body.provider.strip(),
            AiModelPrice.model == body.model.strip(),
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
    rows = db.query(AiModelPrice).filter(AiModelPrice.enabled.is_(True)).all()
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
        query = query.filter(AiModelPrice.model.ilike(like) | AiModelPrice.label.ilike(like))
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
        target_ids = [str(x) for x in block.get("models") or [] if x]
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
    return {
        "ok": True,
        **list_official_sources_for_provider(provider.strip()),
    }


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
        target_ids = [str(x) for x in block.get("models") or [] if x]
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
        target_ids = [str(x) for x in block.get("models") or [] if x]
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
        .filter(
            AiModelPrice.provider == provider.strip(),
            AiModelPrice.model == model.strip(),
        )
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
        .filter(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == user.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(404, "对话不存在")
    messages = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.conversation_id == row.id,
            ChatMessage.user_id == user.id,
        )
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
    """content 可为文本/vision 多段；extra=allow 透传 tool_calls/tool_call_id/name。"""

    model_config = ConfigDict(extra="allow")
    role: str
    content: Union[str, List[Dict[str, Any]]]


class LlmChatDTO(BaseModel):
    provider: str
    model: str
    route_token: str | None = Field(None, max_length=20000, repr=False)
    config_revision: str | None = Field(None, max_length=128)
    key_source: str | None = None
    messages: List[ChatMessageDTO]
    max_tokens: Optional[int] = Field(None, ge=1, le=32000)
    conversation_id: Optional[int] = Field(None, ge=1)
    allow_failover: bool = True
    tools: Optional[List[Any]] = Field(
        None, description="OpenAI function-calling tools 定义（透传给上游模型）"
    )
    tool_choice: Optional[Any] = Field(
        None,
        description="OpenAI tool_choice，如 'auto' 或 {'type':'function','function':{...}}",
    )


class LlmImageDTO(BaseModel):
    provider: str
    model: str = "gpt-image-1"
    prompt: str = Field(..., min_length=1, max_length=4000)
    size: str = Field("1024x1024", max_length=32)
    n: int = Field(1, ge=1, le=4)


class LlmVideoDTO(BaseModel):
    provider: str
    model: str
    prompt: str = Field(..., min_length=1, max_length=4000)
    size: str = Field("1280x720", max_length=32)
    seconds: int = Field(5, ge=1, le=30)


class LlmPptxDTO(BaseModel):
    title: str = Field("AI 生成 PPT", max_length=120)
    markdown: str = Field(..., min_length=1, max_length=60000)
    filename: str = Field("ai-presentation.pptx", max_length=160)


def _requested_chat_snapshot(db, user, body):
    from modstore_server.llm_key_resolver import read_chat_route_token, resolve_chat_route_snapshot

    if not body.route_token and body.config_revision is None:
        return None
    snapshot = (
        read_chat_route_token(body.route_token, user.id, body.provider, body.model.strip())
        if body.route_token
        else resolve_chat_route_snapshot(db, user.id, body.provider, body.model.strip())
    )
    if (
        body.config_revision is not None
        and body.config_revision != snapshot.config_revision
        or body.key_source is not None
        and body.key_source != snapshot.key_source
    ):
        raise HTTPException(
            409,
            {
                "code": "CHAT_ROUTE_CHANGED",
                "message": "模型配置已变化，请重新发送此轮对话",
            },
        )
    return snapshot


@router.post("/chat")
async def llm_chat(
    request: Request,
    body: LlmChatDTO,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    msgs = [{"role": m.role, "content": m.content} for m in body.messages]
    snapshot = _requested_chat_snapshot(db, user, body)
    out = await run_billed_llm_chat(
        request,
        db,
        user,
        provider=body.provider,
        model=body.model.strip(),
        messages=msgs,
        max_tokens=body.max_tokens,
        conversation_id=body.conversation_id,
        allow_failover=bool(body.allow_failover),
        route_snapshot=snapshot,
    )
    payload = {
        "ok": out["ok"],
        "content": out["content"],
        "conversation_id": out["conversation_id"],
        "usage": out["usage"],
        "charge_amount": out["charge_amount"],
        "hold_no": out["hold_no"],
        "key_source": out["key_source"],
        "billed": out["billed"],
        "provider": out.get("provider"),
        "model": out.get("model"),
        "route_source": out.get("route_source"),
        "config_revision": out.get("config_revision"),
        "route_state": out.get("route_state"),
    }
    if out.get("failover_from"):
        payload["failover_from"] = out["failover_from"]
        payload["failover_attempts"] = out.get("failover_attempts") or []
    return payload


@router.post("/chat/stream")
async def llm_chat_stream(
    request: Request,
    body: LlmChatDTO,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    msgs = [m.model_dump(exclude_none=True) for m in body.messages]
    snapshot = _requested_chat_snapshot(db, user, body)
    return await stream_billed_llm_chat(
        request,
        db,
        user,
        provider=body.provider,
        model=body.model.strip(),
        messages=msgs,
        max_tokens=body.max_tokens,
        conversation_id=body.conversation_id,
        allow_failover=bool(body.allow_failover),
        tools=body.tools,
        tool_choice=body.tool_choice,
        route_snapshot=snapshot,
    )


@router.post("/image")
async def llm_image(
    body: LlmImageDTO,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    if body.provider not in KNOWN_PROVIDERS:
        raise HTTPException(400, "unknown provider")
    api_key, key_source = resolve_api_key(db, user.id, body.provider)
    if not api_key:
        raise HTTPException(400, f"供应商「{body.provider}」未配置可用 API Key。")
    base = (
        resolve_base_url(db, user.id, body.provider)
        if body.provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
        else None
    )
    result = await image_dispatch(
        body.provider,
        api_key=api_key,
        base_url=base,
        model=body.model.strip() or "gpt-image-1",
        prompt=body.prompt.strip(),
        size=body.size.strip() or "1024x1024",
        n=body.n,
    )
    if not result.get("ok"):
        raise HTTPException(502, result.get("error") or "image upstream error")
    return {
        "ok": True,
        "images": result.get("images") or [],
        "provider": body.provider,
        "model": body.model,
        "key_source": key_source,
    }


@router.post("/video")
async def llm_video(
    body: LlmVideoDTO,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    if body.provider not in KNOWN_PROVIDERS:
        raise HTTPException(400, "unknown provider")
    api_key, key_source = resolve_api_key(db, user.id, body.provider)
    if not api_key:
        raise HTTPException(400, f"供应商「{body.provider}」未配置可用 API Key。")
    base = (
        resolve_base_url(db, user.id, body.provider)
        if body.provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
        else None
    )
    result = await video_dispatch(
        body.provider,
        api_key=api_key,
        base_url=base,
        model=body.model.strip(),
        prompt=body.prompt.strip(),
        size=body.size.strip() or "1280x720",
        seconds=body.seconds,
    )
    if not result.get("ok"):
        raise HTTPException(502, result.get("error") or "video upstream error")
    return {
        "ok": True,
        "provider": body.provider,
        "model": body.model,
        "key_source": key_source,
        "job_id": result.get("job_id") or "",
        "status": result.get("status") or "pending",
        "preview_url": result.get("preview_url") or "",
    }


@router.post("/pptx")
async def llm_pptx(
    body: LlmPptxDTO,
    user: User = Depends(_get_current_user),
):
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


_BYOK_PLAN_IDS = {"plan_pro", "plan_enterprise"}


_CATALOG_PROVIDER_TIMEOUT_SEC = 12.0

from modstore_server.platform_model_config_api import router as platform_model_config_router

router.include_router(platform_model_config_router)
