"""路由注册：生产 fail-fast、可观测跳过列表。"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

logger = logging.getLogger(__name__)

_skipped_routes: list[str] = []


def routes_degraded() -> bool:
    return len(_skipped_routes) > 0


def skipped_route_names() -> list[str]:
    return list(_skipped_routes)


def reset_skipped_routes() -> None:
    _skipped_routes.clear()


def _fail_fast_enabled() -> bool:
    from app.utils.deployment import deployment_is_production, deployment_is_staging, env_flag

    if env_flag("XCAGI_ALLOW_DEGRADED_ROUTES"):
        return False
    return deployment_is_production() or deployment_is_staging()


def include_router(
    app: FastAPI,
    router: Any,
    *,
    name: str,
    required: bool = False,
    **kwargs: Any,
) -> None:
    try:
        app.include_router(router, **kwargs)
        logger.info("Registered %s", name)
    except Exception as exc:
        if required or _fail_fast_enabled():
            raise RuntimeError(f"Required route registration failed: {name}") from exc
        logger.warning("%s skipped: %s", name, exc)
        _skipped_routes.append(name)


def register_callable(
    app: FastAPI,
    fn: Callable[[FastAPI], None],
    *,
    name: str,
    required: bool = False,
) -> None:
    try:
        fn(app)
        logger.info("Registered %s", name)
    except Exception as exc:
        if required or _fail_fast_enabled():
            raise RuntimeError(f"Required route registration failed: {name}") from exc
        logger.warning("%s skipped: %s", name, exc)
        _skipped_routes.append(name)
