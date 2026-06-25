"""模型统一 SSOT 的 MODstore 运行时只读访问层。

读取 modstore_server/config/models.generated.json —— 该文件由 FHD/config/models.yaml
派生（见 FHD/scripts/dev/ssot_plugins/models.py），是 FHD 与 MODstore 共享的同一份真相。
两包不可互 import，故 accessor 代码各实现一份，但「厂商/模态/分类/计费」数据单一源。

classify() 的算法与 FHD app/infrastructure/llm/model_registry.classify 逐字一致
（已对 64 例 model id 做过对拍），共读同一 SSOT classification 规则。
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path(__file__).resolve().parent / "config" / "models.generated.json"

_lock = threading.RLock()
_cache: dict[str, Any] | None = None


def _registry_path() -> Path:
    override = (os.environ.get("MODSTORE_MODEL_REGISTRY_PATH") or "").strip()
    return Path(override) if override else _DEFAULT_PATH


def registry() -> dict[str, Any]:
    global _cache
    if _cache is not None:
        return _cache
    with _lock:
        if _cache is not None:
            return _cache
        try:
            data = json.loads(_registry_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        _cache = data
        return _cache


def reload() -> dict[str, Any]:
    global _cache
    with _lock:
        _cache = None
    return registry()


# ---------------------------------------------------------------- providers
def providers() -> list[dict[str, Any]]:
    return list(registry().get("providers") or [])


def _alias_to_canonical() -> dict[str, str]:
    out: dict[str, str] = {}
    for p in providers():
        pid = p.get("id")
        if not pid:
            continue
        out[pid] = pid
        for alias in p.get("aliases") or []:
            out[alias] = pid
    return out


def resolve_provider_id(provider_id: str | None) -> str:
    text = str(provider_id or "").strip().lower()
    return _alias_to_canonical().get(text, text)


def get_provider(provider_id: str | None) -> dict[str, Any] | None:
    canonical = resolve_provider_id(provider_id)
    for p in providers():
        if p.get("id") == canonical:
            return p
    return None


# ---------------------------------------------------------------- 厂商分组（替代 llm_key_resolver 常量）
def known_providers() -> tuple[str, ...]:
    """平台厂商解析优先级（替代 KNOWN_PROVIDERS）。
    优先用显式 known_provider_order（顺序敏感），回落到 catalog_listed 厂商。"""
    order = registry().get("known_provider_order")
    if order:
        return tuple(order)
    return tuple(p["id"] for p in providers() if p.get("catalog_listed"))


def openai_style_providers() -> set[str]:
    """models_api == 'openai'（替代 OAI_COMPAT_OPENAI_STYLE_PROVIDERS）。"""
    return {p["id"] for p in providers() if p.get("models_api") == "openai"}


def openai_compat_default_roots() -> dict[str, str]:
    """openai 风格厂商 id → base_url（替代 OPENAI_COMPAT_DEFAULT_ROOT）。"""
    return {p["id"]: p["base_url"] for p in providers() if p.get("models_api") == "openai"}


def _first_env(names: list[str]) -> str:
    for name in names or []:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def platform_api_key(provider: str) -> str | None:
    """按 env_keys 顺序取首个非空平台密钥（替代 llm_key_resolver.platform_api_key）。"""
    p = get_provider(provider)
    if not p:
        return None
    return _first_env(p.get("env_keys") or []) or None


def platform_base_url(provider: str) -> str | None:
    """openai 风格厂商：env 覆盖优先，否则默认根（去尾斜杠）；非 openai 风格返回 None
    （替代 llm_key_resolver.platform_base_url 的语义）。"""
    p = get_provider(provider)
    if not p or p.get("models_api") != "openai":
        return None
    override = _first_env(p.get("base_url_env_keys") or [])
    base = (override or p.get("base_url") or "").strip().rstrip("/")
    return base or None


# ---------------------------------------------------------------- 模态 / 分类
def modality_labels() -> dict[str, str]:
    return dict(registry().get("modality_labels") or {})


def classify(provider: str | None, model_id: str | None) -> str:
    """模型 id → 模态分类。与 FHD model_registry.classify 同算法、共享 SSOT 规则。"""
    rules = registry().get("classification") or {}
    default = rules.get("default", "llm")
    s = (model_id or "").strip()
    if not s:
        return "other"
    low = s.lower()
    prov = (provider or "").strip().lower()

    def _hit(keys: list[str]) -> bool:
        return any(k in low for k in (keys or []))

    if _hit(rules.get("exclude_other_keywords", [])):
        return "other"
    if rules.get("openai_ada_prefix_other") and low.startswith("ada") and prov == "openai":
        return "other"
    if _hit(rules.get("video_keywords", [])):
        return "video"
    if _hit(rules.get("image_keywords", [])):
        return "image"
    if _hit(rules.get("vlm_keywords", [])):
        return "vlm"

    prov_rules = (rules.get("provider_rules") or {}).get(prov) or {}
    if prov == "google":
        if _hit(prov_rules.get("image_keywords", [])):
            return "image"
        if _hit(prov_rules.get("video_keywords", [])):
            return "video"
        if low.startswith("gemini") and "embed" not in low:
            if any(low.startswith(pfx) for pfx in prov_rules.get("vlm_prefixes", [])):
                return "vlm"
    if prov == "anthropic" and _hit(prov_rules.get("vlm_keywords", [])):
        return "vlm"

    if prov in (rules.get("aggregator_providers") or []):
        if _hit(rules.get("aggregator_image_keywords", [])):
            return "image"
        if _hit(rules.get("aggregator_video_keywords", [])):
            return "video"
        if _hit(rules.get("aggregator_other_keywords", [])):
            return "other"
        if _hit(rules.get("aggregator_vlm_keywords", [])):
            return "vlm"
        if prov == "minimax" and _hit(rules.get("minimax_media_other_keywords", [])):
            return "other"

    return default


# ---------------------------------------------------------------- 计费
def pricing() -> dict[str, Any]:
    return dict(registry().get("pricing") or {})


def pricing_defaults_by_modality(modality: str) -> dict[str, Any]:
    defaults = pricing().get("defaults_by_modality") or {}
    return dict(defaults.get(modality) or {})
