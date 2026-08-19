# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.llm_api")


async def resolve_default_llm_route(
    db: _facade().Session, user_id: int
) -> dict[str, _facade().Any]:
    """与 ``GET /api/llm/resolve-chat-default`` 同源：解析账户默认 vendor + model。"""
    import asyncio
    from modstore_server.models import User as UserModel
    from modstore_server.models import get_session_factory

    uid = int(user_id)

    def _load_prefs_and_keys() -> tuple[str, str, dict[str, str]]:
        sf = get_session_factory()
        with sf() as _db:
            urow = _db.query(UserModel).filter(UserModel.id == uid).first()
            prefs: _facade().Dict[str, _facade().Any] = {}
            raw = ((urow.default_llm_json if urow else None) or "").strip()
            if raw:
                try:
                    loaded = _facade().json.loads(raw)
                    if isinstance(loaded, dict):
                        prefs = loaded
                except _facade().json.JSONDecodeError:
                    prefs = {}
            pref_p = str(prefs.get("provider") or "").strip()
            pref_m = str(prefs.get("model") or "").strip()
            keys: dict[str, str] = {}
            for p in _facade().KNOWN_PROVIDERS:
                (k, _) = _facade().resolve_api_key(_db, uid, p)
                if k:
                    keys[p] = k
        return (pref_p, pref_m, keys)

    (pref_p, pref_m, keys) = await asyncio.to_thread(_load_prefs_and_keys)

    async def first_model_id(provider: str) -> str:
        block = await _facade().get_models_for_provider(db, uid, provider, force_refresh=False)
        mids = list(block.get("runtime_models") or block.get("models") or [])
        return str(mids[0]).strip() if mids else ""

    if pref_p in _facade().KNOWN_PROVIDERS and pref_m and (pref_p in keys):
        return {"ok": True, "provider": pref_p, "model": pref_m, "source": "preference"}
    if pref_p in _facade().KNOWN_PROVIDERS and pref_p in keys:
        m0 = await first_model_id(pref_p)
        if m0:
            return {"ok": True, "provider": pref_p, "model": m0, "source": "preference_first_model"}
    for p in _facade().KNOWN_PROVIDERS:
        if p not in keys:
            continue
        m0 = await first_model_id(p)
        if m0:
            return {"ok": True, "provider": p, "model": m0, "source": "fallback"}
    raise _facade().HTTPException(
        400,
        "未配置任何可用 LLM 密钥（平台环境变量或 BYOK）。请在钱包页为至少一个厂商配置密钥，或将账户默认供应商改为已配置密钥的厂商；若已保存 BYOK，请确认服务端已配置 MODSTORE_LLM_MASTER_KEY。",
    )


def _membership_meta(plan_id: str | None) -> _facade().Dict[str, _facade().Any]:
    pid = (plan_id or "").strip()
    tier_map = {
        "plan_basic": ("basic", "VIP", False),
        "plan_pro": ("pro", "VIP+", True),
        "plan_enterprise": ("enterprise", "svip", True),
    }
    (tier, label, can_byok) = tier_map.get(pid, ("free", "普通用户", False))
    return {"tier": tier, "label": label, "is_member": bool(pid), "can_byok": can_byok}


def _active_plan_id(db: _facade().Session, user_id: int) -> str:
    from modstore_server.models import UserPlan

    row = (
        db.query(UserPlan)
        .filter(UserPlan.user_id == user_id, UserPlan.is_active.is_(True))
        .order_by(UserPlan.id.desc())
        .first()
    )
    return str(row.plan_id) if row else ""


def _require_byok_membership(db: _facade().Session, user: _facade().User) -> None:
    if user.is_admin:
        return
    plan_id = _facade()._active_plan_id(db, user.id)
    if plan_id not in _facade()._BYOK_PLAN_IDS:
        meta = _facade()._membership_meta(plan_id)
        raise _facade().HTTPException(
            403,
            f"BYOK 是 VIP+ 及以上能力，当前身份为「{meta['label']}」。请升级会员后再绑定自己的 API Key。",
        )


def _provider_labels() -> _facade().Dict[str, str]:
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


@_facade().router.get("/status")
async def llm_status(user: _facade().User = _facade().Depends(_facade()._get_current_user)):
    import asyncio
    from modstore_server.models import get_session_factory

    user_id = int(user.id)

    def _sync_status() -> dict:
        sf = get_session_factory()
        with sf() as db:
            out = []
            for p in _facade().KNOWN_PROVIDERS:
                st = _facade().credential_status(db, user_id, p)
                st["label"] = _facade()._provider_labels().get(p, p)
                out.append(st)
        return {"providers": out, "fernet_configured": _facade().fernet_configured()}

    return await asyncio.to_thread(_sync_status)


@_facade().router.get("/resolve-chat-default")
async def resolve_chat_default(
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """
    供工作台「自动」模式与需求规划使用：用与 /chat 相同的 resolve_api_key 选出
    provider + model，避免仅依赖前端 /status 与目录推断导致与后端不一致。

    顺序：①账户默认且该厂商有密钥且已填 model；②默认厂商有密钥则取其目录首模；
    ③按 KNOWN_PROVIDERS 顺序第一个「有密钥且能拉到模型 id」的厂商。
    """
    return await _facade().resolve_default_llm_route(db, int(user.id))
