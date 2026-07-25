"""员工 / 模版解析用的 VLM（视觉）路由解析。

优先级：
1. ``XCAGI_EMPLOYEE_VLM_PROVIDER`` + ``XCAGI_EMPLOYEE_VLM_MODEL``
2. 当前主 chat 模型若本身具备视觉能力（目录/名称启发）
3. 已配置 provider 的内置 VLM 默认模型
"""

from __future__ import annotations

import os
import re
from typing import Any

_VISION_HINT_RE = re.compile(
    r"vision|vl-|vlm|deepseek-vl|qwen-vl|llava|omni|gpt-4o|gpt-4\.1|"
    r"gpt-4-turbo|gemini-1\.5|gemini-2|claude-3|claude-sonnet|claude-opus|"
    r"glm-4v|doubao.*vision|moonshot.*vision|多模态",
    re.IGNORECASE,
)

# provider → 默认识别向 VLM（仅在对应 API key 已配置时启用）
_DEFAULT_VLM_BY_PROVIDER: dict[str, str] = {
    "openai": "gpt-4o-mini",
    "b.ai": "gpt-4o-mini",
    "qwen": "qwen-vl-plus",
    "zhipu": "glm-4v-flash",
    "siliconflow": "Qwen/Qwen2-VL-7B-Instruct",
    "openrouter": "openai/gpt-4o-mini",
    "moonshot": "moonshot-v1-8k-vision-preview",
    "volcengine": "doubao-1.5-vision-pro",
    "xcauto": "gpt-4o-mini",
    "xiuci": "gpt-4o-mini",
}

_PROVIDER_KEY_ENVS: dict[str, tuple[str, ...]] = {
    "openai": ("OPENAI_API_KEY",),
    "b.ai": ("OPENAI_API_KEY",),
    "qwen": ("DASHSCOPE_API_KEY", "QWEN_API_KEY"),
    "zhipu": ("ZHIPU_API_KEY", "GLM_API_KEY"),
    "siliconflow": ("SILICONFLOW_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "moonshot": ("MOONSHOT_API_KEY", "KIMI_API_KEY"),
    "volcengine": ("VOLC_API_KEY", "ARK_API_KEY"),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "xcauto": ("XCAUTO_API_KEY", "XIUCI_API_KEY", "OPENAI_API_KEY"),
    "xiuci": ("XIUCI_API_KEY", "XCAUTO_API_KEY", "OPENAI_API_KEY"),
}


def model_looks_like_vlm(model: str) -> bool:
    return bool(_VISION_HINT_RE.search(str(model or "")))


def _env_has_provider_key(provider: str) -> bool:
    for key in _PROVIDER_KEY_ENVS.get(provider, ()):
        if os.environ.get(key, "").strip():
            return True
    return False


def _provider_base_url(provider: str) -> str:
    env_map = {
        "openai": "OPENAI_BASE_URL",
        "b.ai": "OPENAI_BASE_URL",
        "qwen": "DASHSCOPE_BASE_URL",
        "zhipu": "ZHIPU_BASE_URL",
        "siliconflow": "SILICONFLOW_BASE_URL",
        "openrouter": "OPENROUTER_BASE_URL",
        "moonshot": "MOONSHOT_BASE_URL",
        "volcengine": "VOLC_BASE_URL",
        "deepseek": "DEEPSEEK_BASE_URL",
        "xcauto": "XCAUTO_BASE_URL",
        "xiuci": "XIUCI_BASE_URL",
    }
    return os.environ.get(env_map.get(provider, ""), "").strip()


def list_configured_vlm_candidates() -> list[dict[str, Any]]:
    """列出当前环境可推断的 VLM 候选（不打远程目录）。"""
    rows: list[dict[str, Any]] = []
    explicit_provider = os.environ.get("XCAGI_EMPLOYEE_VLM_PROVIDER", "").strip().lower()
    explicit_model = os.environ.get("XCAGI_EMPLOYEE_VLM_MODEL", "").strip()
    if explicit_provider and explicit_model:
        rows.append(
            {
                "provider": explicit_provider,
                "model": explicit_model,
                "source": "env_explicit",
                "configured": _env_has_provider_key(explicit_provider),
            }
        )

    for provider, model in _DEFAULT_VLM_BY_PROVIDER.items():
        if not _env_has_provider_key(provider):
            continue
        override = os.environ.get(f"{provider.upper()}_VLM_MODEL", "").strip()
        rows.append(
            {
                "provider": provider,
                "model": override or model,
                "source": "provider_default",
                "configured": True,
                "base_url": _provider_base_url(provider) or None,
            }
        )

    chat_provider = os.environ.get("XCAGI_LLM_PROVIDER", "").strip().lower()
    chat_model = (
        os.environ.get("XCAGI_EMPLOYEE_LLM_MODEL", "").strip()
        or os.environ.get(f"{chat_provider.upper()}_MODEL", "").strip()
    )
    if chat_provider and chat_model and model_looks_like_vlm(chat_model):
        rows.append(
            {
                "provider": chat_provider,
                "model": chat_model,
                "source": "chat_is_vlm",
                "configured": _env_has_provider_key(chat_provider),
            }
        )

    # 去重：provider+model
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        key = (str(row.get("provider") or ""), str(row.get("model") or ""))
        if key in seen or not key[0] or not key[1]:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def resolve_vlm_route() -> dict[str, Any]:
    """解析当前应使用的 VLM 路由。"""
    explicit_provider = os.environ.get("XCAGI_EMPLOYEE_VLM_PROVIDER", "").strip().lower()
    explicit_model = os.environ.get("XCAGI_EMPLOYEE_VLM_MODEL", "").strip()
    if explicit_provider and explicit_model:
        return {
            "ok": True,
            "provider": explicit_provider,
            "model": explicit_model,
            "source": "env_explicit",
            "configured": _env_has_provider_key(explicit_provider),
            "message": "使用 XCAGI_EMPLOYEE_VLM_* 显式路由",
        }

    chat_provider = os.environ.get("XCAGI_LLM_PROVIDER", "").strip().lower()
    chat_model = (
        os.environ.get("XCAGI_EMPLOYEE_LLM_MODEL", "").strip()
        or (os.environ.get(f"{chat_provider.upper()}_MODEL", "").strip() if chat_provider else "")
    )
    if chat_provider and chat_model and model_looks_like_vlm(chat_model):
        return {
            "ok": True,
            "provider": chat_provider,
            "model": chat_model,
            "source": "chat_is_vlm",
            "configured": _env_has_provider_key(chat_provider),
            "message": "当前主 chat 模型具备视觉能力，复用为主 VLM",
        }

    for provider, model in _DEFAULT_VLM_BY_PROVIDER.items():
        if not _env_has_provider_key(provider):
            continue
        override = os.environ.get(f"{provider.upper()}_VLM_MODEL", "").strip()
        return {
            "ok": True,
            "provider": provider,
            "model": override or model,
            "source": "provider_default",
            "configured": True,
            "message": f"使用已配置 provider {provider} 的默认 VLM",
        }

    return {
        "ok": False,
        "provider": "",
        "model": "",
        "source": "none",
        "configured": False,
        "message": (
            "未配置可用 VLM。请设置 XCAGI_EMPLOYEE_VLM_PROVIDER + "
            "XCAGI_EMPLOYEE_VLM_MODEL，或配置具备视觉模型的 provider API key。"
        ),
        "candidates": list_configured_vlm_candidates(),
    }
