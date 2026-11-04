# mypy: disable-error-code="arg-type, union-attr"
"""Resolve user BYOK or server-managed platform credentials without mixing origins."""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Tuple

from sqlalchemy.orm import Session

from modstore_server.llm_crypto import decrypt_secret, fernet_configured, mask_api_key
from modstore_server.models import UserLlmCredential

# 受支持的 provider id（与前端、catalog、chat 一致）
KNOWN_PROVIDERS = (
    "openai",
    "deepseek",
    "anthropic",
    "google",
    "siliconflow",
    # 国内常用、性价比 OpenAI 兼容（与 SiliconFlow 相邻展示）
    "dashscope",
    "moonshot",
    # 小米 MiMo：OpenAI 兼容（控制台 https://platform.xiaomimimo.com/ ）
    "xiaomi",
    "minimax",
    # 字节火山方舟（豆包等，OpenAI 兼容 /api/v3）
    "doubao",
    "wenxin",
    "hunyuan",
    "zhipu",
    "xunfei",
    "yi",
    "stepfun",
    "baichuan",
    "sensetime",
    "groq",
    "together",
    "openrouter",
)

# OpenAI 兼容：默认根 URL（不含末尾 /v1，由 catalog/chat 统一补全）
OPENAI_COMPAT_DEFAULT_ROOT: dict[str, str] = {
    "openai": "https://api.openai.com",
    "deepseek": "https://api.deepseek.com",
    # 国内 SiliconFlow 控制台与文档默认使用 .cn；海外可设 SILICONFLOW_BASE_URL=https://api.siliconflow.com
    "siliconflow": "https://api.siliconflow.cn",
    "groq": "https://api.groq.com/openai",
    "together": "https://api.together.xyz",
    "openrouter": "https://openrouter.ai/api",
    # 阿里云百炼 OpenAI 兼容（北京）；新加坡等见 DASHSCOPE_BASE_URL
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode",
    "moonshot": "https://api.moonshot.cn",
    # 小米 MiMo 国内 token 计划域名（与嵌入测试一致）；海外或专线可用 XIAOMI_BASE_URL / MIMO_BASE_URL 覆盖
    "xiaomi": "https://token-plan-cn.xiaomimimo.com",
    # MiniMax 国内线；国际可设 MINIMAX_BASE_URL=https://api.minimax.io
    "minimax": "https://api.minimaxi.com",
    # 方舟 OpenAI 兼容：根路径含 /api/v3，catalog/chat 不再追加 /v1
    "doubao": "https://ark.cn-beijing.volces.com/api/v3",
    # 国内主流厂商多数提供 OpenAI-compatible 入口；实际生产可用 *_BASE_URL 覆盖。
    "wenxin": "https://qianfan.baidubce.com/v2",
    "hunyuan": "https://api.hunyuan.cloud.tencent.com/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "xunfei": "https://spark-api-open.xf-yun.com/v1",
    "yi": "https://api.lingyiwanwu.com/v1",
    "stepfun": "https://api.stepfun.com/v1",
    "baichuan": "https://api.baichuan-ai.com/v1",
    "sensetime": "https://api.sensenova.cn/compatible-mode/v1",
}

# 使用 /v1/models + /v1/chat/completions 的厂商（与 catalog、chat 共用）
OAI_COMPAT_OPENAI_STYLE_PROVIDERS = frozenset(
    {
        "openai",
        "deepseek",
        "siliconflow",
        "groq",
        "together",
        "openrouter",
        "dashscope",
        "moonshot",
        "xiaomi",
        "minimax",
        "doubao",
        "wenxin",
        "hunyuan",
        "zhipu",
        "xunfei",
        "yi",
        "stepfun",
        "baichuan",
        "sensetime",
    },
)


def openai_compat_default_root(provider: str) -> str:
    return OPENAI_COMPAT_DEFAULT_ROOT.get(provider, "https://api.openai.com")


def is_minimax_token_plan_key(api_key: Optional[str]) -> bool:
    """识别 MiniMax Token/Coding Plan 密钥（与按量付费密钥协议不同）。"""

    normalized = normalize_minimax_api_key(api_key).lower()
    return "sk-cp-" in normalized


def normalize_minimax_api_key(api_key: Optional[str]) -> str:
    """容错处理聊天中常见的 ``minimax`` 标签与密钥粘连。"""

    from modstore_server.platform_model_config import PlatformApiKey

    value = (api_key or "").strip()
    if value.lower().startswith("minimaxsk-cp-"):
        value = value[len("minimax") :]
    if isinstance(api_key, PlatformApiKey):
        return PlatformApiKey(value, dict(api_key.configuration))
    return value


def minimax_anthropic_base_url(base_url: Optional[str] = None, *, prefer_base: bool = False) -> str:
    """返回 MiniMax Anthropic 兼容根地址（不含末尾 ``/v1``）。"""

    raw = (
        ((base_url or "").strip() if prefer_base else "")
        or _env("MINIMAX_ANTHROPIC_BASE_URL")
        or (base_url or "").strip()
        or platform_base_url("minimax")
        or openai_compat_default_root("minimax")
    ).rstrip("/")
    for suffix in ("/v1", "/v2", "/v3", "/v4"):
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)].rstrip("/")
            break
    if raw.endswith("/anthropic"):
        return raw
    return f"{raw}/anthropic"


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _environment_api_key(provider: str) -> Optional[str]:
    if provider == "openai":
        k = _env("OPENAI_API_KEY")
        return k or None
    if provider == "deepseek":
        k = _env("DEEPSEEK_API_KEY")
        return k or None
    if provider == "anthropic":
        k = _env("ANTHROPIC_API_KEY")
        return k or None
    if provider == "google":
        k = _env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY")
        return k or None
    if provider == "siliconflow":
        k = _env("SILICONFLOW_API_KEY")
        return k or None
    if provider == "groq":
        k = _env("GROQ_API_KEY")
        return k or None
    if provider == "together":
        k = _env("TOGETHER_API_KEY")
        return k or None
    if provider == "openrouter":
        k = _env("OPENROUTER_API_KEY")
        return k or None
    if provider == "dashscope":
        k = _env("DASHSCOPE_API_KEY")
        return k or None
    if provider == "moonshot":
        k = _env("MOONSHOT_API_KEY")
        return k or None
    if provider == "xiaomi":
        k = _env("XIAOMI_API_KEY") or _env("MIMO_API_KEY") or _env("XIAOMI_MIMO_API_KEY")
        return k or None
    if provider == "minimax":
        k = (
            _env("MINIMAX_TOKEN_PLAN_API_KEY")
            or _env("MINIMAX_CODING_PLAN_API_KEY")
            or _env("MINIMAX_API_KEY")
        )
        return normalize_minimax_api_key(k) or None
    if provider == "doubao":
        k = _env("DOUBAO_API_KEY") or _env("ARK_API_KEY")
        return k or None
    if provider == "wenxin":
        k = _env("WENXIN_API_KEY") or _env("QIANFAN_API_KEY") or _env("BAIDU_QIANFAN_API_KEY")
        return k or None
    if provider == "hunyuan":
        k = _env("HUNYUAN_API_KEY") or _env("TENCENT_HUNYUAN_API_KEY")
        return k or None
    if provider == "zhipu":
        k = _env("ZHIPU_API_KEY") or _env("BIGMODEL_API_KEY")
        return k or None
    if provider == "xunfei":
        k = _env("XUNFEI_API_KEY") or _env("SPARK_API_KEY")
        return k or None
    if provider == "yi":
        k = _env("YI_API_KEY") or _env("LINGYIWANWU_API_KEY")
        return k or None
    if provider == "stepfun":
        k = _env("STEPFUN_API_KEY")
        return k or None
    if provider == "baichuan":
        k = _env("BAICHUAN_API_KEY")
        return k or None
    if provider == "sensetime":
        k = _env("SENSETIME_API_KEY") or _env("SENSENOVA_API_KEY")
        return k or None
    return None


def _environment_base_url(provider: str) -> Optional[str]:
    if provider == "openai":
        u = _env("OPENAI_BASE_URL")
        return (u or openai_compat_default_root("openai")).rstrip("/")
    if provider == "deepseek":
        u = _env("DEEPSEEK_BASE_URL")
        return (u or openai_compat_default_root("deepseek")).rstrip("/")
    if provider == "siliconflow":
        u = _env("SILICONFLOW_BASE_URL")
        return (u or openai_compat_default_root("siliconflow")).rstrip("/")
    if provider == "groq":
        u = _env("GROQ_BASE_URL")
        return (u or openai_compat_default_root("groq")).rstrip("/")
    if provider == "together":
        u = _env("TOGETHER_BASE_URL")
        return (u or openai_compat_default_root("together")).rstrip("/")
    if provider == "openrouter":
        u = _env("OPENROUTER_BASE_URL")
        return (u or openai_compat_default_root("openrouter")).rstrip("/")
    if provider == "dashscope":
        u = _env("DASHSCOPE_BASE_URL")
        return (u or openai_compat_default_root("dashscope")).rstrip("/")
    if provider == "moonshot":
        u = _env("MOONSHOT_BASE_URL")
        return (u or openai_compat_default_root("moonshot")).rstrip("/")
    if provider == "xiaomi":
        u = _env("XIAOMI_BASE_URL") or _env("MIMO_BASE_URL") or _env("XIAOMI_MIMO_BASE_URL")
        return (u or openai_compat_default_root("xiaomi")).rstrip("/")
    if provider == "minimax":
        u = _env("MINIMAX_BASE_URL")
        return (u or openai_compat_default_root("minimax")).rstrip("/")
    if provider == "doubao":
        u = _env("DOUBAO_BASE_URL")
        return (u or openai_compat_default_root("doubao")).rstrip("/")
    if provider == "wenxin":
        u = _env("WENXIN_BASE_URL") or _env("QIANFAN_BASE_URL")
        return (u or openai_compat_default_root("wenxin")).rstrip("/")
    if provider == "hunyuan":
        u = _env("HUNYUAN_BASE_URL") or _env("TENCENT_HUNYUAN_BASE_URL")
        return (u or openai_compat_default_root("hunyuan")).rstrip("/")
    if provider == "zhipu":
        u = _env("ZHIPU_BASE_URL") or _env("BIGMODEL_BASE_URL")
        return (u or openai_compat_default_root("zhipu")).rstrip("/")
    if provider == "xunfei":
        u = _env("XUNFEI_BASE_URL") or _env("SPARK_BASE_URL")
        return (u or openai_compat_default_root("xunfei")).rstrip("/")
    if provider == "yi":
        u = _env("YI_BASE_URL") or _env("LINGYIWANWU_BASE_URL")
        return (u or openai_compat_default_root("yi")).rstrip("/")
    if provider == "stepfun":
        u = _env("STEPFUN_BASE_URL")
        return (u or openai_compat_default_root("stepfun")).rstrip("/")
    if provider == "baichuan":
        u = _env("BAICHUAN_BASE_URL")
        return (u or openai_compat_default_root("baichuan")).rstrip("/")
    if provider == "sensetime":
        u = _env("SENSETIME_BASE_URL") or _env("SENSENOVA_BASE_URL")
        return (u or openai_compat_default_root("sensetime")).rstrip("/")
    return None


def _load_user_row(session: Session, user_id: int, provider: str) -> Optional[UserLlmCredential]:
    return (
        session.query(UserLlmCredential)
        .filter(UserLlmCredential.user_id == user_id, UserLlmCredential.provider == provider)
        .first()
    )


def platform_credentials(
    provider: str, *, state: dict[str, Any] | None = None
) -> tuple[Optional[str], Optional[str]]:
    from modstore_server.platform_model_config import (
        PlatformApiKey,
        stored_config,
        stored_key,
    )

    row = stored_config(provider) if state is None else state["providers"].get(provider)
    if row is not None:
        return PlatformApiKey(stored_key(row), row), row["base_url"]
    key, base = _environment_api_key(provider), _environment_base_url(provider)
    if key:
        key = PlatformApiKey(
            key,
            {
                "provider": provider,
                "base_url": base,
                "model": "",
                "display_name": "",
                "revision": "",
                "source": "environment",
            },
        )
    return key, base


def platform_api_key(provider: str) -> Optional[str]:
    return platform_credentials(provider)[0]


def platform_base_url(provider: str) -> Optional[str]:
    return platform_credentials(provider)[1]


def resolve_credentials(
    session: Session, user_id: int, provider: str, *, platform_state: dict[str, Any] | None = None
) -> tuple[Optional[str], Optional[str], str]:
    """Read key and endpoint from one snapshot; a platform key never uses a BYOK URL."""
    row = _load_user_row(session, user_id, provider)
    if row and row.api_key_encrypted and not fernet_configured():
        return None, None, "user_override"
    if row and row.api_key_encrypted and fernet_configured():
        try:
            k = decrypt_secret(row.api_key_encrypted).strip()
            if k:
                if provider == "minimax":
                    k = normalize_minimax_api_key(k)
                base = _environment_base_url(provider)
                if row.base_url_encrypted:
                    # A broken BYOK endpoint must not route its key to another account's endpoint.
                    base = decrypt_secret(row.base_url_encrypted).strip().rstrip("/") or base
                return k, base, "user_override"
        except (ValueError, RuntimeError):
            return None, None, "user_override"
        return None, None, "user_override"
    pk, base = (
        platform_credentials(provider)
        if platform_state is None
        else platform_credentials(provider, state=platform_state)
    )
    if pk:
        return pk, base, "platform"
    return None, base, "none"


@dataclass(frozen=True)
class ChatRouteSnapshot:
    provider: str
    model: str
    route_source: str
    key_source: str
    config_revision: str
    api_key: str = field(repr=False)
    base_url: str | None = field(repr=False)

    def public_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            name: getattr(self, name)
            for name in ("provider", "model", "route_source", "key_source", "config_revision")
        }
        if self.provider == "xiaomi" and self.key_source == "platform":
            from modstore_server.llm_chat_proxy import _normalize_openai_base

            approved_base = "https://token-plan-cn.xiaomimimo.com/v1"
            effective_base = _normalize_openai_base(
                self.provider, self.base_url, self.api_key
            ).rstrip("/")
            if effective_base == approved_base:
                metadata["recipient"] = {
                    "id": "xiaomi-mimo-cn",
                    "provider": self.provider,
                    "api_base": approved_base,
                    "region": "CN",
                    "disclosure_version": "2026-11-01",
                }
        return metadata


def chat_route_snapshot(
    provider: str,
    model: str,
    api_key: str | None,
    base_url: str | None,
    key_source: str,
    route_source: str,
) -> ChatRouteSnapshot:
    from fastapi import HTTPException

    from modstore_server.llm_chat_proxy import normalize_model
    from modstore_server.llm_model_taxonomy import classify_model
    from modstore_server.platform_model_config import PlatformApiKey

    if provider not in KNOWN_PROVIDERS or not api_key:
        raise HTTPException(400, "所选供应商未配置可用密钥，请选择聊天模型或跟随平台")
    model = normalize_model(provider, model, base_url)
    if classify_model(provider, model) not in {"llm", "vlm"}:
        raise HTTPException(
            400,
            {
                "code": "INVALID_CHAT_PREFERENCE",
                "message": "所选模型不支持聊天，请重新选择聊天模型或跟随平台",
                "recovery": "choose_chat_model_or_follow_platform",
            },
        )
    revision = (
        str(api_key.configuration.get("revision") or "")
        if isinstance(api_key, PlatformApiKey)
        else ""
    )
    if not revision:
        revision = hashlib.sha256(
            json.dumps([provider, base_url, api_key, key_source]).encode()
        ).hexdigest()
    return ChatRouteSnapshot(provider, model, route_source, key_source, revision, api_key, base_url)


def resolve_chat_route_snapshot(
    session: Session, user_id: int, provider: str, model: str, route_source: str = "explicit"
) -> ChatRouteSnapshot:
    key, base, source = resolve_credentials(session, user_id, provider)
    return chat_route_snapshot(provider, model, key, base, source, route_source)


def chat_route_token(snapshot: ChatRouteSnapshot, user_id: int) -> str | None:
    """Carry an encrypted, user-bound route across a single tool round; never log it."""
    from modstore_server.llm_crypto import encrypt_secret

    if not fernet_configured():
        return None
    from modstore_server.platform_model_config import PlatformApiKey

    return encrypt_secret(
        json.dumps(
            {
                **snapshot.public_metadata(),
                "api_key": str(snapshot.api_key),
                "base_url": snapshot.base_url,
                "user_id": int(user_id),
                "expires": int(time.time()) + 600,
                "platform_source": (
                    snapshot.api_key.configuration["source"]
                    if isinstance(snapshot.api_key, PlatformApiKey)
                    else None
                ),
            }
        )
    )


def read_chat_route_token(token: str, user_id: int, provider: str, model: str) -> ChatRouteSnapshot:
    from fastapi import HTTPException

    from modstore_server.platform_model_config import PlatformApiKey

    try:
        payload = json.loads(decrypt_secret(token))
        if (
            payload["user_id"] != int(user_id)
            or payload["expires"] <= time.time()
            or payload["expires"] > time.time() + 601
            or payload["provider"] != provider
            or payload["model"] != model
            or payload["key_source"] not in {"platform", "user_override"}
            or not isinstance(payload["config_revision"], str)
            or not isinstance(payload["route_source"], str)
            or not isinstance(payload["base_url"], (str, type(None)))
            or not payload["config_revision"]
            or not payload["route_source"]
            or not isinstance(payload["api_key"], str)
            or not payload["api_key"]
        ):
            raise ValueError("route mismatch")
        key = payload["api_key"]
        if payload["key_source"] == "platform":
            key = PlatformApiKey(
                key,
                {
                    "provider": provider,
                    "base_url": payload["base_url"],
                    "model": model,
                    "display_name": model,
                    "revision": payload["config_revision"],
                    "source": payload.get("platform_source") or "environment",
                },
            )
        return ChatRouteSnapshot(
            provider,
            model,
            payload["route_source"],
            payload["key_source"],
            payload["config_revision"],
            key,
            payload["base_url"],
        )
    except (ValueError, RuntimeError, KeyError, TypeError):
        raise HTTPException(
            409, {"code": "CHAT_ROUTE_EXPIRED", "message": "模型配置快照已失效，请重新发送此轮对话"}
        ) from None


def resolve_api_key(session: Session, user_id: int, provider: str) -> Tuple[Optional[str], str]:
    key, _base, source = resolve_credentials(session, user_id, provider)
    return key, source


def resolve_base_url(session: Session, user_id: int, provider: str) -> Optional[str]:
    return resolve_credentials(session, user_id, provider)[1]


def credential_status(session: Session, user_id: int, provider: str) -> dict:
    has_platform = platform_api_key(provider) is not None
    row = _load_user_row(session, user_id, provider)
    has_user = bool(row and row.api_key_encrypted)
    mask = ""
    if has_user and fernet_configured():
        try:
            mask = mask_api_key(decrypt_secret(row.api_key_encrypted))
        except ValueError:
            mask = "(解密失败)"
    return {
        "provider": provider,
        "has_platform_key": has_platform,
        "has_user_override": has_user,
        "masked_key": mask,
    }
