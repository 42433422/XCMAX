"""Health probe registration and execution mixin."""

from __future__ import annotations

import asyncio
import importlib
import logging
import time
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from app.neuro_bus.health_monitor_types import HealthCheckResult, HealthStatus
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger("app.neuro_bus.health_monitor")


def _get_neuro_bus():
    """Resolve through the compatibility facade so existing patches stay effective."""
    facade = importlib.import_module("app.neuro_bus.health_monitor")
    return facade.get_neuro_bus()


class HealthCheckMixin:
    if TYPE_CHECKING:
        _checks: dict[str, Callable[[], HealthCheckResult]]
        _last_results: dict[str, HealthCheckResult]
        _metrics_history: dict[str, deque]

        def _evaluate_alert(self, result: HealthCheckResult) -> None: ...

        async def run_remediation_closed_loop(self, result: HealthCheckResult) -> Any: ...

    def _register_default_checks(self):
        """注册默认健康检查"""
        self.register_check("neuro_bus", self._check_neuro_bus)
        self.register_check("event_queue", self._check_event_queue)
        self.register_check("memory", self._check_memory)

    # ========== 健康检查注册 ==========

    def register_check(self, name: str, check_fn: Callable[[], HealthCheckResult]):
        """注册健康检查"""
        self._checks[name] = check_fn
        self._metrics_history[name] = deque(maxlen=100)
        logger.info("[HealthMonitor] 注册检查: %s", name)

    def unregister_check(self, name: str):
        """注销健康检查"""
        if name in self._checks:
            del self._checks[name]
            self._last_results.pop(name, None)
            del self._metrics_history[name]

    # ========== 健康检查实现 ==========

    def _check_neuro_bus(self) -> HealthCheckResult:
        """检查 NeuroBus 状态"""
        t0 = time.perf_counter()

        try:
            bus = _get_neuro_bus()
            stats = bus.get_stats()

            latency_ms = (time.perf_counter() - t0) * 1000

            # 判断状态
            if not stats.get("running"):
                status = HealthStatus.UNHEALTHY
                message = "NeuroBus 未运行"
            elif stats.get("queue_size", 0) > 5000:
                status = HealthStatus.DEGRADED
                message = f"队列积压: {stats['queue_size']}"
            elif stats.get("errors", 0) > stats.get("processed", 1) * 0.1:
                status = HealthStatus.DEGRADED
                message = f"错误率过高: {stats['errors']}/{stats.get('processed', 0)}"
            else:
                status = HealthStatus.HEALTHY
                message = "NeuroBus 运行正常"

            return HealthCheckResult(
                component="neuro_bus",
                status=status,
                message=message,
                latency_ms=latency_ms,
                details=stats,
            )

        except RECOVERABLE_ERRORS as e:
            return HealthCheckResult(
                component="neuro_bus",
                status=HealthStatus.UNHEALTHY,
                message=f"检查失败: {str(e)}",
                latency_ms=(time.perf_counter() - t0) * 1000,
                details={"error": str(e)},
            )

    def _check_event_queue(self) -> HealthCheckResult:
        """检查事件队列状态"""
        t0 = time.perf_counter()

        try:
            bus = _get_neuro_bus()
            stats = bus.get_stats()
            queue_size = stats.get("queue_size", 0)
            dropped = stats.get("dropped", 0)

            latency_ms = (time.perf_counter() - t0) * 1000

            if queue_size > 8000:
                status = HealthStatus.UNHEALTHY
                message = f"队列严重积压: {queue_size}"
            elif queue_size > 5000:
                status = HealthStatus.DEGRADED
                message = f"队列积压: {queue_size}"
            elif dropped > 100:
                status = HealthStatus.DEGRADED
                message = f"事件丢弃过多: {dropped}"
            else:
                status = HealthStatus.HEALTHY
                message = f"队列正常: {queue_size}"

            return HealthCheckResult(
                component="event_queue",
                status=status,
                message=message,
                latency_ms=latency_ms,
                details={
                    "queue_size": queue_size,
                    "dropped": dropped,
                },
            )

        except RECOVERABLE_ERRORS as e:
            return HealthCheckResult(
                component="event_queue",
                status=HealthStatus.UNHEALTHY,
                message=f"检查失败: {str(e)}",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

    def _check_memory(self) -> HealthCheckResult:
        """检查内存使用"""
        t0 = time.perf_counter()

        try:
            import psutil

            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024

            latency_ms = (time.perf_counter() - t0) * 1000

            if memory_mb > 1024:  # 1GB
                status = HealthStatus.DEGRADED
                message = f"内存使用较高: {memory_mb:.1f}MB"
            else:
                status = HealthStatus.HEALTHY
                message = f"内存使用正常: {memory_mb:.1f}MB"

            return HealthCheckResult(
                component="memory",
                status=status,
                message=message,
                latency_ms=latency_ms,
                details={"memory_mb": memory_mb},
            )

        except ImportError:
            return HealthCheckResult(
                component="memory",
                status=HealthStatus.UNKNOWN,
                message="无法检查（psutil 未安装）",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
        except RECOVERABLE_ERRORS as e:
            return HealthCheckResult(
                component="memory",
                status=HealthStatus.UNHEALTHY,
                message=f"检查失败: {str(e)}",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

    # ========== 检查执行 ==========

    async def run_check(self, name: str) -> HealthCheckResult | None:
        """运行单个检查"""
        check_fn = self._checks.get(name)
        if not check_fn:
            return None

        try:
            # 支持异步和同步检查
            if asyncio.iscoroutinefunction(check_fn):
                result = await check_fn()
            else:
                result = check_fn()

            self._last_results[name] = result
            self._metrics_history[name].append(result)

            # 检查是否需要告警
            self._evaluate_alert(result)

            # 自动驱动闭环：对所有结果调用闭环方法，使其自动处理非健康结果
            # （执行已注册的修复处理器、强制后置条件复查、写接收单），并在健康时解除未决 incident。
            # 后置条件复查复用 `_run_postcondition_check`，绝不在此递归调用 run_check。
            await self.run_remediation_closed_loop(result)

            return cast("HealthCheckResult | None", result)

        except RECOVERABLE_ERRORS as e:
            logger.error("[HealthMonitor] 检查失败 %s: %s", name, e)
            return None

    async def run_all_checks(self) -> dict[str, HealthCheckResult]:
        """运行所有检查"""
        results = {}

        for name in self._checks:
            result = await self.run_check(name)
            if result:
                results[name] = result

        return results
