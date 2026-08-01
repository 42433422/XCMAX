"""Persy 记忆图谱定时任务：权重衰减 + 缓存刷新。

由 FastAPI lifespan 在启动时通过 ``asyncio.create_task`` 挂起，shutdown 时 cancel。
两个任务都是 ``while True`` 循环，靠 ``asyncio.sleep`` 控制频率。

- ``run_memory_decay_task`` — 每 24 小时执行一次 ``MemoryDecayService.run_maintenance``，
  对 scope 内 active 节点重新计算权重并归档冷数据。
- ``run_memory_cache_refresh_task`` — 每 30 分钟刷新本地兜底缓存
  （``~/.trae-cn/memory-cache/persy-cache.json``），Persy 不可用时供 Trae IDE 降级读取。

设计要点：
- 任意一轮失败不退出循环，记录日志后短退避（60s）重试，避免任务永久死亡。
- ``MemoryDecayService`` / ``MemoryCacheService`` 在循环内延迟导入，避免模块加载阶段
  触发 DB 引擎构造（与 lifespan 其他 init 函数保持一致）。
- 接收 ``app_service`` 入参，由 lifespan 注入；解耦具体 DB 来源
  （应用 SessionLocal 或 PERSY_DB_URL 独立 engine）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.application.memory_graph_app_service import MemoryGraphAppService

logger = logging.getLogger(__name__)

# 默认调度间隔（生产值）。测试时可传入极小值加速。
DEFAULT_DECAY_INTERVAL_HOURS = 24
DEFAULT_CACHE_REFRESH_INTERVAL_MINUTES = 30
# 出错后退避秒数
ERROR_BACKOFF_SECONDS = 60


async def run_memory_decay_task(
    app_service: MemoryGraphAppService,
    interval_hours: int = DEFAULT_DECAY_INTERVAL_HOURS,
    scope: str = "project",
    scope_id: str = "XCMAX",
    stop_event: asyncio.Event | None = None,
) -> None:
    """定时执行权重衰减 + 自动归档。

    Args:
        app_service: 记忆图谱应用服务。
        interval_hours: 调度间隔（小时），默认 24。
        scope: 作用域类型。
        scope_id: 作用域内的标识。
        stop_event: 优雅停机信号；set 后循环退出（lifespan shutdown 时触发，
            task.cancel() 仍作为兜底）。
    """
    stop = stop_event or asyncio.Event()
    interval_seconds = max(1, interval_hours * 3600)
    while not stop.is_set():
        try:
            await asyncio.sleep(interval_seconds)
            # 延迟导入，避免模块加载阶段触发 DB 引擎构造
            from app.application.memory_decay_service import MemoryDecayService

            # MemoryDecayService 直接操作 store._session（同步调用），
            # 用 to_thread 避免阻塞事件循环
            decay_svc = MemoryDecayService(app_service._store)  # noqa: SLF001
            result = await asyncio.to_thread(
                decay_svc.run_maintenance, scope=scope, scope_id=scope_id
            )
            logger.info(
                "[MemoryGraph] 衰减维护完成 scope=%s/%s processed=%s decayed=%s archived=%s",
                scope,
                scope_id,
                result.get("processed"),
                result.get("decayed"),
                result.get("archived"),
            )
        except asyncio.CancelledError:
            logger.info("[MemoryGraph] 衰减任务被取消，退出循环")
            raise
        except Exception as e:  # noqa: BLE001 - 定时任务必须吞掉所有异常避免死亡
            logger.error("[MemoryGraph] 衰减任务失败，%ss 后重试: %s", ERROR_BACKOFF_SECONDS, e)
            await asyncio.sleep(ERROR_BACKOFF_SECONDS)


async def run_memory_cache_refresh_task(
    app_service: MemoryGraphAppService,
    interval_minutes: int = DEFAULT_CACHE_REFRESH_INTERVAL_MINUTES,
    scope: str = "project",
    scope_id: str = "XCMAX",
) -> None:
    """定时刷新本地兜底缓存。

    Args:
        app_service: 记忆图谱应用服务。
        interval_minutes: 调度间隔（分钟），默认 30。
        scope: 作用域类型。
        scope_id: 作用域内的标识。
    """
    interval_seconds = max(1, interval_minutes * 60)
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            from app.infrastructure.memory_cache import MemoryCacheService

            cache_svc = MemoryCacheService()
            # refresh 是同步 IO（写 JSON），用 to_thread 避免阻塞事件循环
            count = await asyncio.to_thread(
                cache_svc.refresh, app_service, scope=scope, scope_id=scope_id
            )
            logger.info(
                "[MemoryGraph] 缓存刷新完成 scope=%s/%s cached=%s",
                scope,
                scope_id,
                count,
            )
        except asyncio.CancelledError:
            logger.info("[MemoryGraph] 缓存刷新任务被取消，退出循环")
            raise
        except Exception as e:  # noqa: BLE001 - 定时任务必须吞掉所有异常避免死亡
            logger.error(
                "[MemoryGraph] 缓存刷新任务失败，%ss 后重试: %s",
                ERROR_BACKOFF_SECONDS,
                e,
            )
            await asyncio.sleep(ERROR_BACKOFF_SECONDS)


__all__ = [
    "DEFAULT_CACHE_REFRESH_INTERVAL_MINUTES",
    "DEFAULT_DECAY_INTERVAL_HOURS",
    "ERROR_BACKOFF_SECONDS",
    "run_memory_cache_refresh_task",
    "run_memory_decay_task",
]
