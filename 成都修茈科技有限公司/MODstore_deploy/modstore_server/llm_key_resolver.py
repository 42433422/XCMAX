"""解析平台环境变量密钥与用户 BYOK（用户优先）。"""

from __future__ import annotations

import os
from typing import Optional, Tuple

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


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def platform_api_key(provider: str) -> Optional[str]:
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
        k = _env("MINIMAX_API_KEY")
        return k or None
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


def platform_base_url(provider: str) -> Optional[str]:
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
