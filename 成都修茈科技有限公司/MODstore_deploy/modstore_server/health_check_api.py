"""健康检查 API。"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/", summary="健康检查")
async def health_check() -> dict:
    """返回服务状态，用于负载均衡或监控探活。"""
    return {"status": "ok"}
