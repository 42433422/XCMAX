"""运行时状态读取端点：一处回答「什么在跑 / 什么停了 / 各 job 上次成功何时」。"""

from __future__ import annotations

from fastapi import APIRouter

from modstore_server.scheduler_runtime import get_runtime_status

router = APIRouter(tags=["scheduler-runtime"])


@router.get("/api/scheduler/runtime")
def scheduler_runtime(stale_after_seconds: int | None = None) -> dict:
    """按 job 汇总的调度器运行时真相；``stale_after_seconds`` 可覆盖停摆阈值。"""
    return get_runtime_status(stale_after_seconds=stale_after_seconds)
