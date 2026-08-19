"""State, configuration, rolling counters, and errors for NeuroBus circuit breakers."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from threading import RLock


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

class CircuitBreakerOpen(Exception):
    """熔断器打开异常"""

    pass
