"""三档模型路由（阶段 8）：本地 / 边缘 / 云端。

路由策略：
- 由 ``XCAGI_AI_TIER`` 环境变量决定首选档位（local / edge / cloud / auto）。
- 与既有 ``infrastructure.llm.client`` 的 online/offline 模式对齐：
  offline → 首选 local；online → 首选 cloud。
- 选定首选档后，按 ``偏好档 → 其余档`` 的顺序在可用 Provider 间 failover，
  任一成功即返回；全部失败返回最后一次错误。

对外暴露 ``recognize_intent`` / ``chat`` / ``synthesize`` 三个高层入口，
业务层只需调用 router，不感知具体 Provider。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.infrastructure.ai.providers import Capability, ProviderResult, Tier, find

logger = logging.getLogger(__name__)

_DEFAULT_ORDER = [Tier.LOCAL, Tier.EDGE, Tier.CLOUD]


def _preferred_tier() -> Tier | None:
    raw = (os.environ.get("XCAGI_AI_TIER") or "").strip().lower()
    if raw in {"local", "offline"}:
        return Tier.LOCAL
    if raw in {"edge"}:
        return Tier.EDGE
    if raw in {"cloud", "online", "api"}:
        return Tier.CLOUD
    # 回落到 llm.client 的 online/offline 模式
    try:
        from app.infrastructure.llm.client import resolve_mode

        return Tier.LOCAL if resolve_mode() == "offline" else Tier.CLOUD
    except Exception:
        return None


def tier_order() -> list[Tier]:
    """返回本次路由的档位优先顺序（首选档置顶）。"""
    preferred = _preferred_tier()
    if preferred is None:
        return list(_DEFAULT_ORDER)
    rest = [t for t in _DEFAULT_ORDER if t != preferred]
    return [preferred, *rest]


def _ordered_providers(capability: Capability) -> list:
    """按档位优先顺序返回所有可用 Provider（跨档 failover 用）。"""
    providers: list = []
    for tier in tier_order():
        providers.extend(find(capability, tier=tier, available_only=True))
    # 去重保序
    seen: set[str] = set()
    unique = []
    for p in providers:
        if p.name not in seen:
            seen.add(p.name)
            unique.append(p)
    return unique


async def _dispatch(capability: Capability, method: str, *args: Any, **kwargs: Any) -> ProviderResult:
    providers = _ordered_providers(capability)
    if not providers:
        return ProviderResult(
            False, capability, "none", error=f"无可用 {capability.value} Provider"
        )
    last: ProviderResult | None = None
    for provider in providers:
        try:
            result: ProviderResult = await getattr(provider, method)(*args, **kwargs)
        except Exception as exc:  # Provider 内部已大多兜底，这里是双保险
            logger.warning("provider %s raised: %s", provider.name, exc)
            last = ProviderResult(False, capability, provider.name, error=str(exc))
            continue
        if result.success:
            return result
        last = result
    return last or ProviderResult(False, capability, "none", error="全部 Provider 失败")


async def recognize_intent(
    message: str, context: list[dict[str, str]] | None = None, **kwargs: Any
) -> ProviderResult:
    return await _dispatch(Capability.INTENT, "recognize_intent", message, context, **kwargs)


async def chat(messages: list[dict[str, str]], **kwargs: Any) -> ProviderResult:
    return await _dispatch(Capability.CHAT, "chat", messages, **kwargs)


async def synthesize(text: str, voice: str | None = None, **kwargs: Any) -> ProviderResult:
    return await _dispatch(Capability.TTS, "synthesize", text, voice, **kwargs)


__all__ = ["tier_order", "recognize_intent", "chat", "synthesize"]
