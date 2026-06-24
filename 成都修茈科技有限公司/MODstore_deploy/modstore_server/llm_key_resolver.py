"""解析平台环境变量密钥与用户 BYOK（用户优先）。"""

from __future__ import annotations

from typing import Optional, Tuple

from sqlalchemy.orm import Session

from modstore_server import model_registry
from modstore_server.llm_crypto import decrypt_secret, fernet_configured, mask_api_key
from modstore_server.models import UserLlmCredential

# 厂商连接信息（清单/默认 base_url/openai 风格/平台密钥/base_url 解析）全部来自模型统一 SSOT：
# FHD/config/models.yaml → modstore_server/config/models.generated.json（见 model_registry）。
# 保留原符号名与类型（KNOWN_PROVIDERS=tuple 且顺序敏感、OAI_COMPAT_OPENAI_STYLE_PROVIDERS=frozenset），
# 全仓 ~137 处引用零改动。新增/改厂商：改 models.yaml + `ssot sync models --apply`。
KNOWN_PROVIDERS = model_registry.known_providers()
OPENAI_COMPAT_DEFAULT_ROOT: dict[str, str] = model_registry.openai_compat_default_roots()
OAI_COMPAT_OPENAI_STYLE_PROVIDERS = frozenset(model_registry.openai_style_providers())


def openai_compat_default_root(provider: str) -> str:
    return OPENAI_COMPAT_DEFAULT_ROOT.get(provider, "https://api.openai.com")


def platform_api_key(provider: str) -> Optional[str]:
    """平台环境变量密钥（按 SSOT env_keys 顺序取首个非空）。"""
    return model_registry.platform_api_key(provider)


def platform_base_url(provider: str) -> Optional[str]:
    """OpenAI 兼容系 base_url（env 覆盖优先，否则默认根，去尾斜杠）；
    anthropic/google 等非 openai 风格返回 None。"""
    return model_registry.platform_base_url(provider)


def _load_user_row(session: Session, user_id: int, provider: str) -> Optional[UserLlmCredential]:
    return (
        session.query(UserLlmCredential)
        .filter(UserLlmCredential.user_id == user_id, UserLlmCredential.provider == provider)
        .first()
    )


def resolve_api_key(session: Session, user_id: int, provider: str) -> Tuple[Optional[str], str]:
    """返回 (api_key, source) source 为 user_override | platform | none"""
    row = _load_user_row(session, user_id, provider)
    if row and row.api_key_encrypted and fernet_configured():
        try:
            k = decrypt_secret(row.api_key_encrypted).strip()
            if k:
                return k, "user_override"
        except ValueError:
            pass
    pk = platform_api_key(provider)
    if pk:
        return pk, "platform"
    return None, "none"


def resolve_base_url(session: Session, user_id: int, provider: str) -> Optional[str]:
    """OpenAI 兼容系：用户 base_url 优先，否则平台。anthropic/google 返回 None。"""
    row = _load_user_row(session, user_id, provider)
    if row and row.base_url_encrypted and fernet_configured():
        try:
            u = decrypt_secret(row.base_url_encrypted).strip().rstrip("/")
            if u:
                return u
        except ValueError:
            pass
    return platform_base_url(provider)


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
