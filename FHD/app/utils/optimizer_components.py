"""Lazy optimizer discovery and the service optimization mixin."""

from __future__ import annotations

import logging
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def get_optimizer_components() -> dict[str, Any]:
    """Load optional performance components without imposing startup dependencies."""
    components: dict[str, Any] = {
        "cache": None,
        "monitor": None,
        "deduplicator": None,
        "async_manager": None,
    }
    try:
        from app.utils.performance.performance_initializer import get_performance_optimizer

        optimizer = get_performance_optimizer()
        if optimizer.redis_cache:
            components["cache"] = optimizer.redis_cache
        if optimizer.performance_monitor:
            components["monitor"] = optimizer.performance_monitor
        if optimizer.request_deduplicator:
            components["deduplicator"] = optimizer.request_deduplicator
        if optimizer.async_task_manager:
            components["async_manager"] = optimizer.async_task_manager
    except RECOVERABLE_ERRORS as exc:
        logger.debug("优化组件加载失败: %s", exc)
    return components


class OptimizedServiceMixin:
    """Populate optional optimizer fields for a service instance."""

    def _init_optimizers(self) -> None:
        # Resolve through the compatibility module so existing monkeypatch and
        # extension points continue to control component discovery.
        from app.utils import decorators

        components = decorators.get_optimizer_components()
        self._cache = components["cache"]
        self._monitor = components["monitor"]
        self._deduplicator = components["deduplicator"]
        self._async_manager = components["async_manager"]
        logger.debug("服务 %s 优化组件已初始化", self.__class__.__name__)
