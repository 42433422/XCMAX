"""Optional application mounts and NeuroBus diagnostic routes."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI

from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def maybe_mount_vibe_subapp(app: FastAPI) -> None:
    if (os.environ.get("MODSTORE_ENABLE_VIBE_WEB") or "").strip() not in (
        "1",
        "true",
        "yes",
    ):
        return
    try:
        from modstore_server.integrations.vibe_adapter import vibe_available
    except RECOVERABLE_ERRORS:
        return
    if not vibe_available():
        logger.info("MODSTORE_ENABLE_VIBE_WEB=1 但 vibe-coding 未安装,跳过挂载")
        return
    try:
        from vibe_coding.agent.web import create_app as create_vibe_app
    except RECOVERABLE_ERRORS:
        logger.exception("vibe_coding.agent.web 加载失败,跳过 /api/vibe 挂载")
        return
    try:
        app.mount("/api/vibe", create_vibe_app())
        logger.info("已挂载 vibe-coding sub-app 到 /api/vibe")
    except RECOVERABLE_ERRORS:
        logger.exception("挂载 /api/vibe 失败")


def register_neurobus_diagnostics(app: FastAPI) -> None:
    try:
        from modstore_server.eventing.global_bus import neuro_bus

        @app.get("/api/neurobus/stats", tags=["ops"])
        async def neurobus_stats():
            if hasattr(neuro_bus, "get_stats"):
                return neuro_bus.get_stats()
            return {"status": "basic", "type": type(neuro_bus).__name__}

        @app.get("/api/neurobus/health", tags=["ops"])
        async def neurobus_health():
            return {
                "status": "ok",
                "bus_type": type(neuro_bus).__name__,
                "has_stats": hasattr(neuro_bus, "get_stats"),
            }

        logger.info("Registered NeuroBus diagnostics (/api/neurobus/stats, /api/neurobus/health)")
    except RECOVERABLE_ERRORS:
        logger.debug("NeuroBus diagnostics skipped", exc_info=True)
