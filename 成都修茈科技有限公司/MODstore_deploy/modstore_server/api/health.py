"""Health check routes."""

from __future__ import annotations

from fastapi import APIRouter

from modstore_server.api.dto import HealthResponse
from modstore_server.deploy_context import health_payload

router = APIRouter(tags=["health"])


def _scheduler_status() -> bool | None:
    try:
        from modstore_server.workflow_scheduler import _scheduler as _sch

        if _sch is not None and getattr(_sch, "running", False):
            return True
        return False
    except Exception:
        return None


@router.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    ctx = health_payload()
    sch = _scheduler_status()
    return HealthResponse(ok=True, scheduler_running=sch, **ctx)
