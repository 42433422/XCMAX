"""AI Provider 抽象与注册表（阶段 8）。"""

from __future__ import annotations

from app.infrastructure.ai.providers.base import (
    BaseProvider,
    Capability,
    ProviderResult,
    Tier,
)
from app.infrastructure.ai.providers.registry import (
    all_providers,
    find,
    get,
    matrix,
    register,
)

__all__ = [
    "BaseProvider",
    "Capability",
    "ProviderResult",
    "Tier",
    "all_providers",
    "find",
    "get",
    "matrix",
    "register",
]
