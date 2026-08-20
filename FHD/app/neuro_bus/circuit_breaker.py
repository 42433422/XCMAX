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

import importlib
import logging
import time
from collections.abc import Callable
from threading import RLock
from typing import TYPE_CHECKING

from app.neuro_bus.circuit_breaker_execution import CircuitBreakerExecutionMixin
from app.neuro_bus.circuit_breaker_primitives import (
    CircuitBreakerConfig,
    CircuitState,
    RollingWindowCounter,
)
from app.neuro_bus.circuit_breaker_primitives import (
    CircuitBreakerOpen as CircuitBreakerOpen,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class CircuitBreaker(CircuitBreakerExecutionMixin):
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
            except RECOVERABLE_ERRORS as e:  # noqa: BLE001 - 回调异常不应影响熔断
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


_manager_module = importlib.import_module("app.neuro_bus.circuit_breaker_manager")
if TYPE_CHECKING:
    from app.neuro_bus.circuit_breaker_manager import NeuroCircuitBreakerManager
else:
    NeuroCircuitBreakerManager = _manager_module.NeuroCircuitBreakerManager


_neuro_circuit_manager: NeuroCircuitBreakerManager | None = None


def get_circuit_breaker() -> NeuroCircuitBreakerManager:
    """NeuroBus 初始化器使用的单例。"""
    global _neuro_circuit_manager
    if _neuro_circuit_manager is None:
        _neuro_circuit_manager = NeuroCircuitBreakerManager()
    return _neuro_circuit_manager
