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


def initialize_service_optimizers(service: Any, components: dict[str, Any]) -> None:
    """Bind explicitly supplied optional components to a service instance."""
    service._cache = components["cache"]
    service._monitor = components["monitor"]
    service._deduplicator = components["deduplicator"]
    service._async_manager = components["async_manager"]
    logger.debug("服务 %s 优化组件已初始化", service.__class__.__name__)
