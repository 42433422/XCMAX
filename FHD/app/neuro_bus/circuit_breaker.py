"""
熔断保护器（Circuit Breaker）

工业级实现，对标 Netflix Hystrix 和 resilience4j。

支持特性：
- 滑动窗口失败率统计（桶计数 + 环形缓冲，O(1) 更新）
- 慢调用熔断（slow_call_rate_threshold）
- Fallback 降级（含超时保护）
- Metrics 暴露（Prometheus 兼容）
- 自动转半开（惰性检查）
- 状态转换事件回调
- 向后兼容：旧的 failure_threshold 快速熔断仍有效
"""

import asyncio
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from threading import RLock
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """熔断器状态"""

    CLOSED = "closed"  # 正常，请求通过
    OPEN = "open"  # 熔断，拒绝请求
    HALF_OPEN = "half_open"  # 半开，试探性允许


@dataclass
class CircuitBreakerConfig:
    """熔断器配置（对标 Netflix Hystrix / resilience4j）"""

    # ── 基础配置（向后兼容） ──
    failure_threshold: int = 5  # 触发熔断的连续失败次数（快速熔断后备）
    success_threshold: int = 3  # 半开状态恢复所需成功次数
    timeout_seconds: float = 60.0  # 熔断后尝试恢复的时间
    half_open_max_calls: int = 3  # 半开状态最大试探请求数（向后兼容）

    # ── 滑动窗口失败率统计 ──
    failure_rate_threshold: float = 0.5  # 失败率阈值（50%）
    minimum_number_of_calls: int = 20  # 最小样本量，未达不熔断
    window_size_seconds: float = 10.0  # 滑动窗口大小（秒）
    bucket_size_seconds: float = 1.0  # 桶大小（秒）

    # ── 慢调用熔断 ──
    slow_call_duration_threshold: float = 5.0  # 慢调用阈值（秒）
    slow_call_rate_threshold: float = 0.8  # 慢调用率阈值（80%）

    # ── Fallback 降级 ──
    fallback: Callable | None = None  # 降级函数
    fallback_timeout_seconds: float = 5.0  # fallback 超时（秒）

    # ── 自动转半开 ──
    automatic_transition_from_open_to_half_open: bool = True

    # ── 半开状态改进 ──
    permitted_number_of_calls_in_half_open_state: int = 10  # 半开允许调用数
    minimum_number_of_calls_in_half_open: int = 3  # 半开最小决策样本量


class RollingWindowCounter:
    """
    滑动窗口计数器（桶计数 + 环形缓冲）

    使用 collections.deque 实现环形缓冲，O(1) 更新。
    每桶维护 success/failure/timeout/rejection/slow_call 计数。
    """

    def __init__(
        self,
        window_size_seconds: float = 10.0,
        bucket_size_seconds: float = 1.0,
    ):
        self._window_size = window_size_seconds
        self._bucket_size = max(0.001, bucket_size_seconds)
        self._num_buckets = max(1, int(window_size_seconds / self._bucket_size))
        # deque(maxlen=...) 自动丢弃最旧的桶，实现环形缓冲
        self._buckets: deque[dict] = deque(maxlen=self._num_buckets)
        self._lock = RLock()

    def _current_bucket(self) -> dict:
        """获取当前时间对应的桶，必要时创建新桶并淘汰过期桶。"""
        now = time.monotonic()
        bucket_start = (int(now / self._bucket_size)) * self._bucket_size
        # 淘汰过期桶（start 早于窗口外）
        cutoff = now - self._window_size
        while self._buckets and self._buckets[0]["start"] < cutoff:
            self._buckets.popleft()
        # 复用当前桶或创建新桶
        if self._buckets and self._buckets[-1]["start"] == bucket_start:
            return self._buckets[-1]
        new_bucket = {
            "start": bucket_start,
            "success": 0,
            "failure": 0,
            "timeout": 0,
            "rejection": 0,
            "slow_call": 0,
        }
        self._buckets.append(new_bucket)
        return new_bucket

    def record_success(self) -> None:
        """记录一次成功调用。"""
        with self._lock:
            self._current_bucket()["success"] += 1

    def record_failure(self) -> None:
        """记录一次失败调用。"""
        with self._lock:
            self._current_bucket()["failure"] += 1

    def record_timeout(self) -> None:
        """记录一次超时调用。"""
        with self._lock:
            self._current_bucket()["timeout"] += 1

    def record_rejection(self) -> None:
        """记录一次拒绝调用（熔断器 OPEN 时）。"""
        with self._lock:
            self._current_bucket()["rejection"] += 1

    def record_slow_call(self) -> None:
        """记录一次慢调用。"""
        with self._lock:
            self._current_bucket()["slow_call"] += 1

    def get_stats(self) -> dict:
        """
        获取窗口内累计统计。

        Returns:
            包含 total/success/failure/timeout/rejection/slow_call
            及 failure_rate/slow_call_rate 的字典。
            注意：failure_rate 不含 rejection（rejection 不是真实调用）。
        """
        with self._lock:
            now = time.monotonic()
            cutoff = now - self._window_size
            while self._buckets and self._buckets[0]["start"] < cutoff:
                self._buckets.popleft()
            success = sum(b["success"] for b in self._buckets)
            failure = sum(b["failure"] for b in self._buckets)
            timeout = sum(b["timeout"] for b in self._buckets)
            rejection = sum(b["rejection"] for b in self._buckets)
            slow_call = sum(b["slow_call"] for b in self._buckets)
            # failure_rate 的分母不含 rejection（rejection 不是真实调用）
            total = success + failure + timeout
            failure_rate = (failure + timeout) / total if total > 0 else 0.0
            slow_call_rate = slow_call / total if total > 0 else 0.0
            return {
                "total": total,
                "success": success,
                "failure": failure,
                "timeout": timeout,
                "rejection": rejection,
                "slow_call": slow_call,
                "failure_rate": failure_rate,
                "slow_call_rate": slow_call_rate,
            }

    def reset(self) -> None:
        """清空所有桶。"""
        with self._lock:
            self._buckets.clear()


class CircuitBreaker:
    """
    熔断器（工业级实现）

    基于 Hystrix/resilience4j 设计：
    - 滑动窗口失败率统计（RollingWindowCounter）
    - 慢调用熔断（slow_call_rate_threshold）
    - Fallback 降级（含超时保护）
    - 自动转半开（惰性检查）
    - 状态转换事件回调
    - 向后兼容：failure_threshold 快速熔断仍有效
    """

    def __init__(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
    ):
        self._name = name
        self._config = config or CircuitBreakerConfig()

        self._state = CircuitState.CLOSED
        self._failure_count = 0  # 连续失败计数（快速熔断后备）
        self._success_count = 0  # 半开状态连续成功计数
        self._last_failure_time: float | None = None  # monotonic 时间戳
        self._half_open_calls = 0  # 半开状态已放行的试探请求数

        # ── 滑动窗口统计 ──
        self._window = RollingWindowCounter(
            window_size_seconds=self._config.window_size_seconds,
            bucket_size_seconds=self._config.bucket_size_seconds,
        )
        # 半开状态独立的窗口（避免与 CLOSED 窗口污染）
        self._half_open_window = RollingWindowCounter(
            window_size_seconds=self._config.timeout_seconds,
            bucket_size_seconds=max(0.1, self._config.timeout_seconds / 10.0),
        )

        # ── 并发执行计数 ──
        self._concurrent_executions = 0

        # ── 拒绝/fallback 计数 ──
        self._rejected_count = 0
        self._fallback_success_count = 0
        self._fallback_failure_count = 0

        # ── 状态转换回调 ──
        self._state_change_callbacks: list[Callable[[CircuitState, CircuitState, dict], None]] = []

        self._lock = RLock()

        logger.info("CircuitBreaker [%s] initialized", name)

    @property
    def state(self) -> CircuitState:
        """当前状态"""
        with self._lock:
            return self._state

    def on_state_change(self, callback: Callable[[CircuitState, CircuitState, dict], None]) -> None:
        """
        注册状态转换回调。

        回调签名：callback(old_state, new_state, context_dict)
        回调异常不影响熔断逻辑（try/except 吞掉）。
        """
        with self._lock:
            self._state_change_callbacks.append(callback)

    def _transition_to(
        self,
        new_state: CircuitState,
        context: dict | None = None,
    ) -> None:
        """
        状态转换（线程安全，调用方需持有 _lock 或确保单线程上下文）。

        Args:
            new_state: 目标状态
            context: 转换上下文（传给回调）
        """
        old_state = self._state
        if old_state == new_state:
            return
        self._state = new_state
        ctx = context or {}
        # 进入 OPEN 时记录时间戳（用于自动转半开的惰性检查）
        if new_state == CircuitState.OPEN:
            self._last_failure_time = time.monotonic()
        # 进入 HALF_OPEN 时重置计数器
        if new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
            self._success_count = 0
            self._half_open_window.reset()
        # 进入 CLOSED 时重置所有计数器
        if new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0
        logger.info(
            "Circuit [%s] transition: %s -> %s (ctx=%s)",
            self._name,
            old_state.value,
            new_state.value,
            ctx,
        )
        # 触发回调（异常不影响熔断逻辑）
        for callback in self._state_change_callbacks:
            try:
                callback(old_state, new_state, ctx)
            except Exception as e:  # noqa: BLE001 - 回调异常不应影响熔断
                logger.warning("Circuit [%s] state change callback failed: %s", self._name, e)

    def can_execute(self) -> bool:
        """
        检查是否可以执行

        Returns:
            True: 允许执行
            False: 熔断中，拒绝执行

        说明：
        - OPEN 状态下，若 automatic_transition_from_open_to_half_open=True
          且 timeout_seconds 已过，自动转 HALF_OPEN（惰性检查）
        - HALF_OPEN 状态限制试探请求数（half_open_max_calls）
        """
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True

            if self._state == CircuitState.OPEN:
                # 检查是否到达恢复时间（惰性检查实现自动转半开）
                if self._config.automatic_transition_from_open_to_half_open:
                    if self._last_failure_time is not None:
                        elapsed = time.monotonic() - self._last_failure_time
                        if elapsed > self._config.timeout_seconds:
                            logger.info("Circuit [%s] auto-transitioning to HALF_OPEN", self._name)
                            self._transition_to(
                                CircuitState.HALF_OPEN,
                                context={"reason": "timeout_elapsed", "elapsed": elapsed},
                            )
                            # 转入 HALF_OPEN 后放行第一个试探请求
                            # 注意：不在此处累加 half_open_calls，保持与原实现一致
                            # （transition 调用本身不占用 half_open 配额）
                            return True
                return False

            if self._state == CircuitState.HALF_OPEN:
                # 半开状态限制试探请求数（向后兼容 half_open_max_calls）
                if self._half_open_calls < self._config.half_open_max_calls:
                    self._half_open_calls += 1
                    return True
                return False

            return True

    def record_success(self):
        """
        记录成功

        - CLOSED：重置连续失败计数，记录到滑动窗口
        - HALF_OPEN：累计成功，达 success_threshold 转 CLOSED
        """
        with self._lock:
            # 滑动窗口记录（CLOSED 和 HALF_OPEN 都记录）
            self._window.record_success()
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_window.record_success()

            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1

                # 向后兼容：达 success_threshold 转 CLOSED
                if self._success_count >= self._config.success_threshold:
                    logger.info("Circuit [%s] transitioning to CLOSED", self._name)
                    self._transition_to(
                        CircuitState.CLOSED,
                        context={"reason": "half_open_success_threshold"},
                    )

            elif self._state == CircuitState.CLOSED:
                # 重置连续失败计数（向后兼容）
                if self._failure_count > 0:
                    self._failure_count = 0

    def record_failure(self):
        """
        记录失败

        - CLOSED：累计连续失败，达 failure_threshold 快速熔断；
          或滑动窗口失败率/慢调用率达阈值且样本量足够 → OPEN
        - HALF_OPEN：立即转 OPEN（向后兼容快速失败语义）
        """
        with self._lock:
            self._failure_count += 1
            # 滑动窗口记录（CLOSED 和 HALF_OPEN 都记录）
            self._window.record_failure()
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_window.record_failure()
            # _last_failure_time 由 _transition_to(OPEN) 设置

            if self._state == CircuitState.HALF_OPEN:
                # 半开状态再次失败，重新熔断（向后兼容）
                logger.warning("Circuit [%s] failed in HALF_OPEN, returning to OPEN", self._name)
                self._transition_to(
                    CircuitState.OPEN,
                    context={"reason": "half_open_failure"},
                )

            elif self._state == CircuitState.CLOSED:
                # 快速熔断后备：连续失败达 failure_threshold 立即熔断
                if self._failure_count >= self._config.failure_threshold:
                    logger.warning(
                        "Circuit [%s] OPEN due to %s consecutive failures (fast-fail)",
                        self._name,
                        self._failure_count,
                    )
                    self._transition_to(
                        CircuitState.OPEN,
                        context={
                            "reason": "consecutive_failure_threshold",
                            "failure_count": self._failure_count,
                        },
                    )
                    return

                # 滑动窗口失败率熔断（需达最小样本量）
                window_stats = self._window.get_stats()
                if window_stats["total"] >= self._config.minimum_number_of_calls:
                    if window_stats["failure_rate"] >= self._config.failure_rate_threshold:
                        logger.warning(
                            "Circuit [%s] OPEN due to failure_rate=%.2f (>= %.2f, total=%d)",
                            self._name,
                            window_stats["failure_rate"],
                            self._config.failure_rate_threshold,
                            window_stats["total"],
                        )
                        self._transition_to(
                            CircuitState.OPEN,
                            context={
                                "reason": "failure_rate_threshold",
                                "failure_rate": window_stats["failure_rate"],
                                "total": window_stats["total"],
                            },
                        )
                        return

                    # 慢调用率熔断
                    if window_stats["slow_call_rate"] >= self._config.slow_call_rate_threshold:
                        logger.warning(
                            "Circuit [%s] OPEN due to slow_call_rate=%.2f (>= %.2f, total=%d)",
                            self._name,
                            window_stats["slow_call_rate"],
                            self._config.slow_call_rate_threshold,
                            window_stats["total"],
                        )
                        self._transition_to(
                            CircuitState.OPEN,
                            context={
                                "reason": "slow_call_rate_threshold",
                                "slow_call_rate": window_stats["slow_call_rate"],
                                "total": window_stats["total"],
                            },
                        )

    def record_slow_call(self) -> None:
        """
        记录一次慢调用（耗时超过 slow_call_duration_threshold）。

        慢调用会同时计入滑动窗口的 slow_call 计数，
        用于慢调用率熔断判定。
        """
        with self._lock:
            self._window.record_slow_call()
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_window.record_slow_call()

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

    def get_metrics(self) -> dict:
        """
        获取 Prometheus 兼容的指标快照。

        Returns:
            包含 state/failure_rate/slow_call_rate/各类调用计数
            及 concurrent_executions 的字典。
        """
        with self._lock:
            window_stats = self._window.get_stats()
            return {
                "name": self._name,
                "state": self._state.value,
                "failure_rate": window_stats["failure_rate"],
                "slow_call_rate": window_stats["slow_call_rate"],
                "total_calls": window_stats["total"],
                "successful_calls": window_stats["success"],
                "failed_calls": window_stats["failure"] + window_stats["timeout"],
                "slow_calls": window_stats["slow_call"],
                "rejected_calls": self._rejected_count,
                "fallback_calls": self._fallback_success_count + self._fallback_failure_count,
                "fallback_success": self._fallback_success_count,
                "fallback_failure": self._fallback_failure_count,
                "concurrent_executions": self._concurrent_executions,
            }

    def get_stats(self) -> dict:
        """
        获取统计（向后兼容，含旧字段 + 新指标）

        Returns:
            包含 name/state/failure_count/success_count/half_open_calls
            /last_failure 及滑动窗口指标的字典。
        """
        with self._lock:
            window_stats = self._window.get_stats()
            return {
                # 旧字段（向后兼容）
                "name": self._name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "half_open_calls": self._half_open_calls,
                "last_failure": self._last_failure_time,
                # 新字段（滑动窗口指标）
                "failure_rate": window_stats["failure_rate"],
                "slow_call_rate": window_stats["slow_call_rate"],
                "total_calls": window_stats["total"],
                "successful_calls": window_stats["success"],
                "failed_calls": window_stats["failure"] + window_stats["timeout"],
                "slow_calls": window_stats["slow_call"],
                "rejected_calls": self._rejected_count,
                "fallback_calls": self._fallback_success_count + self._fallback_failure_count,
                "concurrent_executions": self._concurrent_executions,
            }


class CircuitBreakerOpen(Exception):
    """熔断器打开异常"""

    pass


class NeuroCircuitBreakerManager:
    """
    NeuroBus 熔断管理器

    管理多个熔断器，按领域和事件类型划分。
    提供 get_all_metrics / get_prometheus_metrics 用于监控集成。
    """

    # 各领域的熔断配置
    DOMAIN_CONFIGS = {
        "payment": CircuitBreakerConfig(
            failure_threshold=3,  # 支付敏感，低阈值
            timeout_seconds=30.0,  # 快速恢复尝试
        ),
        "wechat": CircuitBreakerConfig(
            failure_threshold=5,
            timeout_seconds=60.0,
        ),
        "intent": CircuitBreakerConfig(
            failure_threshold=10,  # 意图识别容忍度高
            timeout_seconds=30.0,
        ),
        "default": CircuitBreakerConfig(),
    }

    # 状态到数值的映射（用于 Prometheus gauge）
    _STATE_TO_INT = {
        CircuitState.CLOSED: 0,
        CircuitState.HALF_OPEN: 1,
        CircuitState.OPEN: 2,
    }

    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = RLock()

    def get_breaker(self, domain: str, event_type: str | None = None) -> CircuitBreaker:
        """获取或创建熔断器"""
        key = f"{domain}:{event_type}" if event_type else domain

        with self._lock:
            if key not in self._breakers:
                config = self.DOMAIN_CONFIGS.get(domain, self.DOMAIN_CONFIGS["default"])
                self._breakers[key] = CircuitBreaker(key, config)

            return self._breakers[key]

    def check(self, domain: str, event_type: str | None = None) -> bool:
        """检查是否可以通过"""
        breaker = self.get_breaker(domain, event_type)
        return breaker.can_execute()

    def record_success(self, domain: str, event_type: str | None = None):
        """记录成功"""
        breaker = self.get_breaker(domain, event_type)
        breaker.record_success()

    def record_failure(self, domain: str, event_type: str | None = None):
        """记录失败"""
        breaker = self.get_breaker(domain, event_type)
        breaker.record_failure()

    def get_all_stats(self) -> dict:
        """获取所有熔断器统计（向后兼容）"""
        with self._lock:
            return {key: breaker.get_stats() for key, breaker in self._breakers.items()}

    def get_all_metrics(self) -> dict:
        """
        获取所有熔断器的 Prometheus 兼容指标。

        Returns:
            {breaker_name: metrics_dict} 的字典。
        """
        with self._lock:
            return {key: breaker.get_metrics() for key, breaker in self._breakers.items()}

    def get_prometheus_metrics(self) -> str:
        """
        生成 Prometheus 文本格式指标。

        输出格式符合 Prometheus exposition format，
        可直接由 /metrics 端点返回。

        指标列表：
        - circuit_breaker_state{gauge}
        - circuit_breaker_failure_rate
        - circuit_breaker_slow_call_rate
        - circuit_breaker_total_calls
        - circuit_breaker_successful_calls
        - circuit_breaker_failed_calls
        - circuit_breaker_slow_calls
        - circuit_breaker_rejected_calls
        - circuit_breaker_fallback_calls
        - circuit_breaker_concurrent_executions
        """
        with self._lock:
            lines: list[str] = []
            # 帮助文本
            lines.append(
                "# HELP circuit_breaker_state Circuit breaker state (0=closed,1=half_open,2=open)"
            )
            lines.append("# TYPE circuit_breaker_state gauge")
            lines.append("# HELP circuit_breaker_failure_rate Failure rate in sliding window")
            lines.append("# TYPE circuit_breaker_failure_rate gauge")
            lines.append("# HELP circuit_breaker_total_calls Total calls in sliding window")
            lines.append("# TYPE circuit_breaker_total_calls gauge")
            lines.append(
                "# HELP circuit_breaker_concurrent_executions Current concurrent executions"
            )
            lines.append("# TYPE circuit_breaker_concurrent_executions gauge")

            for name, breaker in self._breakers.items():
                m = breaker.get_metrics()
                # 转义 name 中的特殊字符
                safe_name = name.replace("\\", "\\\\").replace('"', '\\"')
                label = f'name="{safe_name}"'
                state_int = self._STATE_TO_INT.get(CircuitState(m["state"]), 0)
                lines.append(f"circuit_breaker_state{{{label}}} {state_int}")
                lines.append(f"circuit_breaker_failure_rate{{{label}}} {m['failure_rate']}")
                lines.append(f"circuit_breaker_slow_call_rate{{{label}}} {m['slow_call_rate']}")
                lines.append(f"circuit_breaker_total_calls{{{label}}} {m['total_calls']}")
                lines.append(f"circuit_breaker_successful_calls{{{label}}} {m['successful_calls']}")
                lines.append(f"circuit_breaker_failed_calls{{{label}}} {m['failed_calls']}")
                lines.append(f"circuit_breaker_slow_calls{{{label}}} {m['slow_calls']}")
                lines.append(f"circuit_breaker_rejected_calls{{{label}}} {m['rejected_calls']}")
                lines.append(f"circuit_breaker_fallback_calls{{{label}}} {m['fallback_calls']}")
                lines.append(
                    f"circuit_breaker_concurrent_executions{{{label}}} {m['concurrent_executions']}"
                )
            return "\n".join(lines) + "\n" if lines else ""


_neuro_circuit_manager: NeuroCircuitBreakerManager | None = None


def get_circuit_breaker() -> NeuroCircuitBreakerManager:
    """NeuroBus 初始化器使用的单例。"""
    global _neuro_circuit_manager
    if _neuro_circuit_manager is None:
        _neuro_circuit_manager = NeuroCircuitBreakerManager()
    return _neuro_circuit_manager
