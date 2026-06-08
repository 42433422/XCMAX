"""健康检查与 K8s 探针。"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import text

from modstore_server.models import get_session_factory

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/")
async def health_check():
    checks: dict = {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": os.environ.get("MODSTORE_VERSION", "unknown"),
    }
    try:
        sf = get_session_factory()
        with sf() as session:
            session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
        checks["status"] = "degraded"
    return checks


@router.get("/ready")
async def readiness_check():
    return {"ready": True}


@router.get("/live")
async def liveness_check():
    return {"alive": True}
