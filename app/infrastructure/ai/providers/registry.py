"""Provider 注册表（阶段 8）。

负责发现、实例化与查询所有 AI Provider，提供：
- 按名称获取 Provider
- 按能力 + 档位筛选可用 Provider（供路由层使用）
- 缺依赖 Provider 的优雅降级（实例化失败仅记日志，不影响整体）

注册采用懒加载：首次访问时导入并实例化内置 Provider，避免 import 期触发
torch/transformers 等重依赖。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable

from app.infrastructure.ai.providers.base import BaseProvider, Capability, Tier

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_providers: dict[str, BaseProvider] = {}
_loaded = False

# 内置 Provider：模块路径 + 类名（懒加载）
_BUILTIN = [
    ("app.infrastructure.ai.providers.deepseek_provider", "DeepSeekProvider"),
    ("app.infrastructure.ai.providers.bert_provider", "BertProvider"),
    ("app.infrastructure.ai.providers.rasa_provider", "RasaProvider"),
    ("app.infrastructure.ai.providers.tts_provider", "TTSProvider"),
]


def register(provider: BaseProvider) -> None:
    with _lock:
        _providers[provider.name] = provider
        logger.info("AI provider registered: %s (tier=%s)", provider.name, provider.tier.value)


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    with _lock:
        if _loaded:
            return
        for module_path, cls_name in _BUILTIN:
            try:
                module = __import__(module_path, fromlist=[cls_name])
                cls = getattr(module, cls_name)
                instance = cls()
                _providers[instance.name] = instance
                logger.info("AI provider loaded: %s", instance.name)
            except Exception as exc:  # 缺依赖/导入错误 → 跳过，优雅降级
                logger.warning("AI provider %s 不可用（已跳过）：%s", cls_name, exc)
        _loaded = True


def get(name: str) -> BaseProvider | None:
    _ensure_loaded()
    return _providers.get(name)


def all_providers() -> list[BaseProvider]:
    _ensure_loaded()
    return list(_providers.values())


def find(
    capability: Capability,
    tier: Tier | None = None,
    available_only: bool = True,
) -> list[BaseProvider]:
    """按能力（必选）+ 档位（可选）筛选 Provider。"""
    _ensure_loaded()
    result: list[BaseProvider] = []
    for provider in _providers.values():
        if not provider.supports(capability):
            continue
        if tier is not None and provider.tier != tier:
            continue
        if available_only and not _safe_available(provider):
            continue
        result.append(provider)
    return result


def _safe_available(provider: BaseProvider) -> bool:
    try:
        return provider.is_available()
    except Exception as exc:
        logger.debug("provider %s availability probe failed: %s", provider.name, exc)
        return False


def matrix() -> list[dict]:
    """返回 Provider 能力矩阵（供 /api/ai/providers 与文档生成使用）。"""
    _ensure_loaded()
    return [p.describe() for p in _providers.values()]


def reset() -> None:
    """测试辅助：清空注册表。"""
    global _loaded
    with _lock:
        _providers.clear()
        _loaded = False


__all__ = [
    "register",
    "get",
    "all_providers",
    "find",
    "matrix",
    "reset",
    "Capability",
    "Tier",
]


def _iter_names(providers: Iterable[BaseProvider]) -> list[str]:
    return [p.name for p in providers]
