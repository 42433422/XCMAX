"""模型统一 SSOT 的 FHD 运行时只读访问层。

读取 FHD/config/models.generated.json（由 FHD/config/models.yaml 派生，见
scripts/dev/ssot_plugins/models.py）。FHD 内所有对「厂商连接信息 / 默认模型 /
模态分类 / 计费默认价」的查询都应经此模块，禁止再写硬编码副本。

设计：
  - 只读 stdlib json，无 PyYAML 运行时依赖。
  - 进程内缓存（首次加载后缓存；测试可调 reload()）。
  - 派生件缺失时优雅降级（返回空集），不让 import 期崩溃。
  - 别名（aliases）在各映射里展开，兼容旧 PROVIDER_DEFAULT_URLS 等以 id 为键的用法。
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

_FHD_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PATH = _FHD_ROOT / "config" / "models.generated.json"

_lock = threading.RLock()
_cache: dict[str, Any] | None = None


def _registry_path() -> Path:
    override = (os.environ.get("XCAGI_MODEL_REGISTRY_PATH") or "").strip()
    return Path(override) if override else _DEFAULT_PATH


def registry() -> dict[str, Any]:
    """返回完整 SSOT 派生数据（缓存）。派生件缺失/损坏时返回空骨架。"""
    global _cache
    if _cache is not None:
        return _cache
    with _lock:
        if _cache is not None:
            return _cache
        path = _registry_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        _cache = data
        return _cache


def reload() -> dict[str, Any]:
    """清缓存并重载（测试或热更新用）。"""
    global _cache
    with _lock:
        _cache = None
    return registry()


# ---------------------------------------------------------------- providers
def providers() -> list[dict[str, Any]]:
    return list(registry().get("providers") or [])


def provider_ids() -> list[str]:
    """所有真实 provider id（不含别名）。"""
    return [p["id"] for p in providers() if p.get("id")]


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
    """别名 → 规范 id；未知原样返回（小写去空白）。"""
    text = str(provider_id or "").strip().lower()
    return _alias_to_canonical().get(text, text)


def get_provider(provider_id: str | None) -> dict[str, Any] | None:
    """按 id 或别名取厂商条目。"""
    canonical = resolve_provider_id(provider_id)
    for p in providers():
        if p.get("id") == canonical:
            return p
    return None


# ---------------------------------------------------------------- back-compat 映射（含别名展开）
def _expand_with_aliases(value_key: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for p in providers():
        pid = p.get("id")
        if not pid or value_key not in p:
            continue
        out[pid] = p[value_key]
        for alias in p.get("aliases") or []:
            out[alias] = p[value_key]
    return out


def provider_default_urls() -> dict[str, str]:
    """替代 llm_adapter.PROVIDER_DEFAULT_URLS（id/别名 → base_url）。"""
    return _expand_with_aliases("base_url")


def default_models() -> dict[str, str]:
    """替代 llm_adapter.DEFAULT_MODELS（id/别名 → default_model）。"""
    return _expand_with_aliases("default_model")


def env_key_mapping() -> dict[str, list[str]]:
    """替代 llm_adapter.ENV_KEY_MAPPING（id/别名 → env_keys）。"""
    return _expand_with_aliases("env_keys")


def base_url_env_mapping() -> dict[str, list[str]]:
    return _expand_with_aliases("base_url_env_keys")


def default_model(provider_id: str | None) -> str | None:
    p = get_provider(provider_id)
    return p.get("default_model") if p else None


def provider_base_url(provider_id: str | None) -> str | None:
    p = get_provider(provider_id)
    return p.get("base_url") if p else None


# ---------------------------------------------------------------- 凭证 / base_url 解析
def _first_env(names: list[str]) -> str:
    for name in names or []:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def provider_api_key(provider_id: str | None) -> str | None:
    """按 env_keys 顺序取首个非空平台密钥。"""
    p = get_provider(provider_id)
    if not p:
        return None
    key = _first_env(p.get("env_keys") or [])
    return key or None


def provider_base_url_resolved(provider_id: str | None) -> str | None:
    """base_url_env_keys 覆盖优先，否则厂商默认 base_url（去尾斜杠）。"""
    p = get_provider(provider_id)
    if not p:
        return None
    override = _first_env(p.get("base_url_env_keys") or [])
    base = (override or p.get("base_url") or "").strip().rstrip("/")
    return base or None


# ---------------------------------------------------------------- 厂商分组（替代散落常量）
def openai_style_providers() -> set[str]:
    """models_api == 'openai' 的厂商（替代 OAI_COMPAT_OPENAI_STYLE_PROVIDERS）。"""
    return {p["id"] for p in providers() if p.get("models_api") == "openai"}


def known_providers() -> tuple[str, ...]:
    """平台厂商解析优先级（替代 MODstore KNOWN_PROVIDERS）。
    优先用显式 known_provider_order（顺序敏感），回落到 catalog_listed 厂商。"""
    order = registry().get("known_provider_order")
    if order:
        return tuple(order)
    return tuple(p["id"] for p in providers() if p.get("catalog_listed"))


def byok_base_url_providers() -> list[str]:
    """byok_custom_base_url=true（替代前端 LLM_OAI_COMPAT_BASE_URL_PROVIDERS）。"""
    return [p["id"] for p in providers() if p.get("byok_custom_base_url")]


def registry_aliases() -> dict[str, str]:
    """FHD registry 的 provider id 归一别名（替代 registry._PROVIDER_ID_ALIASES）。"""
    return dict((registry().get("gateway") or {}).get("registry_aliases") or {})


def gateway_order() -> tuple[str, ...]:
    order = (registry().get("gateway") or {}).get("default_order") or []
    return tuple(order)


# ---------------------------------------------------------------- 模态 / 分类
def modalities() -> list[str]:
    return list(registry().get("modalities") or [])


def modality_labels() -> dict[str, str]:
    return dict(registry().get("modality_labels") or {})


def chat_capable_modalities() -> set[str]:
    return set(registry().get("chat_capable_modalities") or [])


def classify(provider: str | None, model_id: str | None) -> str:
    """模型 id → 模态分类。读取 SSOT classification 规则，算法与
    MODstore llm_model_taxonomy.classify_model 保持逐字一致（两包不可互 import，
    故同算法各实现一份，规则数据共享自同一 SSOT）。"""
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
    defaults = (pricing().get("defaults_by_modality") or {})
    return dict(defaults.get(modality) or {})


def service_fee_multiplier() -> str:
    return str(pricing().get("service_fee_multiplier") or "1.0")
