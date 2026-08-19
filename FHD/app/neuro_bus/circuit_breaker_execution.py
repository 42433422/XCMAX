"""Fallback and execution paths shared by the NeuroBus circuit breaker."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from threading import RLock
from typing import TYPE_CHECKING, Any

from app.neuro_bus.circuit_breaker_primitives import (
    CircuitBreakerConfig,
    CircuitBreakerOpen,
    RollingWindowCounter,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS


class CircuitBreakerExecutionMixin:
    _name: str
    _config: CircuitBreakerConfig
    _lock: RLock
    _window: RollingWindowCounter
    _concurrent_executions: int
    _rejected_count: int
    _fallback_success_count: int
    _fallback_failure_count: int

    if TYPE_CHECKING:
        def can_execute(self) -> bool: ...
        def record_success(self) -> None: ...
        def record_failure(self, *, is_timeout: bool = False) -> None: ...
        def record_slow_call(self) -> None: ...

    def _acquire_execution_slot(self) -> None:
        """占用一个并发执行槽位。"""
        with self._lock:
            self._concurrent_executions += 1

    def _release_execution_slot(self) -> None:
        """释放一个并发执行槽位。"""
        with self._lock:
            if self._concurrent_executions > 0:
                self._concurrent_executions -= 1

    def _call_fallback_sync(self) -> Any:
        """
        同步调用 fallback（含超时保护）。

        使用守护线程执行 fallback，主线程 join(timeout)。
        超时则抛 TimeoutError；fallback 自身异常则透传。
        """
        fallback = self._config.fallback
        if fallback is None:
            raise CircuitBreakerOpen(f"Circuit [{self._name}] is OPEN and no fallback")

        result: list[Any] = [None]
        exc: list[BaseException | None] = [None]

        def _worker() -> None:
            try:
                result[0] = fallback()
            except BaseException as e:  # noqa: BLE001 - 需捕获所有异常以透传
                exc[0] = e

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        thread.join(timeout=self._config.fallback_timeout_seconds)

        if thread.is_alive():
            # 守护线程仍在运行，无法真正终止，但主线程不再等待
            with self._lock:
                self._fallback_failure_count += 1
            raise TimeoutError(f"Fallback timed out after {self._config.fallback_timeout_seconds}s")
        if exc[0] is not None:
            with self._lock:
                self._fallback_failure_count += 1
            raise exc[0]
        with self._lock:
            self._fallback_success_count += 1
        return result[0]

    async def _call_fallback_async(self) -> Any:
        """
        异步调用 fallback（含超时保护）。

        使用 asyncio.wait_for 限制 fallback 执行时间。
        fallback 可以是协程函数或返回协程的普通函数。
        """
        fallback = self._config.fallback
        if fallback is None:
            raise CircuitBreakerOpen(f"Circuit [{self._name}] is OPEN and no fallback")

        try:
            coro = fallback()
            if asyncio.iscoroutine(coro):
                result = await asyncio.wait_for(coro, timeout=self._config.fallback_timeout_seconds)
            else:
                # fallback 返回非协程值（同步 fallback 在 async 上下文中使用）
                result = coro
            with self._lock:
                self._fallback_success_count += 1
            return result
        except BaseException:  # noqa: BLE001 - 需捕获所有异常以透传
            with self._lock:
                self._fallback_failure_count += 1
            raise

    def execute(self, fn: Callable, *args, **kwargs) -> Any:
        """
        执行函数，自动处理熔断逻辑

        Args:
            fn: 要执行的函数
            *args, **kwargs: 函数参数

        Returns:
            函数返回值（或 fallback 返回值）

        Raises:
            CircuitBreakerOpen: 熔断器打开且无 fallback 时抛出
            原始异常: 执行失败且无 fallback 时抛出

        说明：
        - 熔断 OPEN 时，若有 fallback 则调用 fallback 返回默认值
        - 执行失败时，若有 fallback 则调用 fallback
        - 记录调用耗时，慢调用计入 slow_call 统计
        """
        if not self.can_execute():
            with self._lock:
                self._rejected_count += 1
                self._window.record_rejection()
            if self._config.fallback is not None:
                return self._call_fallback_sync()
            raise CircuitBreakerOpen(f"Circuit [{self._name}] is OPEN")

        self._acquire_execution_slot()
        start_time = time.monotonic()
        try:
            result = fn(*args, **kwargs)
            duration = time.monotonic() - start_time
            if duration > self._config.slow_call_duration_threshold:
                self.record_slow_call()
            self.record_success()
            return result
        except RECOVERABLE_ERRORS:
            duration = time.monotonic() - start_time
            if duration > self._config.slow_call_duration_threshold:
                self.record_slow_call()
            self.record_failure()
            if self._config.fallback is not None:
                return self._call_fallback_sync()
            raise
        finally:
            self._release_execution_slot()

    async def execute_async(self, fn: Callable, *args, **kwargs) -> Any:
        """
        异步执行函数，自动处理熔断逻辑

        Args:
            fn: 要执行的异步函数
            *args, **kwargs: 函数参数

        Returns:
            函数返回值（或 fallback 返回值）

        Raises:
            CircuitBreakerOpen: 熔断器打开且无 fallback 时抛出
            原始异常: 执行失败且无 fallback 时抛出

        说明：
        - 熔断 OPEN 时，若有 fallback 则调用 fallback 返回默认值
        - 执行失败时，若有 fallback 则调用 fallback
        - 记录调用耗时，慢调用计入 slow_call 统计
        """
        if not self.can_execute():
            with self._lock:
                self._rejected_count += 1
                self._window.record_rejection()
            if self._config.fallback is not None:
                return await self._call_fallback_async()
            raise CircuitBreakerOpen(f"Circuit [{self._name}] is OPEN")

        self._acquire_execution_slot()
        start_time = time.monotonic()
        try:
            result = await fn(*args, **kwargs)
            duration = time.monotonic() - start_time
            if duration > self._config.slow_call_duration_threshold:
                self.record_slow_call()
            self.record_success()
            return result
        except RECOVERABLE_ERRORS:
            duration = time.monotonic() - start_time
            if duration > self._config.slow_call_duration_threshold:
                self.record_slow_call()
            self.record_failure()
            if self._config.fallback is not None:
                return await self._call_fallback_async()
            raise
        finally:
            self._release_execution_slot()

