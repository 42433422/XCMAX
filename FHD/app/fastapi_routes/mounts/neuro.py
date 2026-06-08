"""Route mount: neuro."""

from __future__ import annotations

from app.utils.operational_errors import OPERATIONAL_ERRORS
import logging
import os

from fastapi import FastAPI

from app.fastapi_routes._route_helpers import is_ci_strict

logger = logging.getLogger(__name__)


def register_neuro_routes(app: FastAPI) -> None:
    """注册 NeuroBus HTTP 诊断路由（与 lifespan 中的总线启动配合）。"""
    try:
        from app.neuro_bus.integrations.fastapi_integration import add_neurobus_routes

        add_neurobus_routes(app)
        logger.info("Registered NeuroBus routes (/api/neurobus/*)")
    except OPERATIONAL_ERRORS as exc:
        if is_ci_strict():
            raise RuntimeError("NeuroBus routes required in CI") from exc
        logger.warning("NeuroBus routes skipped: %s", exc)


