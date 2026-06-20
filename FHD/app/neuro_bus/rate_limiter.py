"""
动态限流器（Rate Limiter）

支持动态调整的限流器，可基于领域、事件类型等维度进行限流。

核心算法：令牌桶（TokenBucket）——惰性刷新、短临界区、对标 resilience4j AtomicRateLimiter。
保留 SlidingWindowCounter 仅为向后兼容，已标记废弃。
"""

import logging
import time
import warnings
from dataclasses import dataclass
from threading import Lock, RLock

from app.neuro_bus.events.base import EventPriority, NeuroEvent

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """限流配置"""

    requests_per_second: float = 10.0
    burst_size: int = 20
    window_size: float = 1.0  # 秒
    dynamic_adjust: bool = True

    def to_snapshot(self) -> dict:
        """生成不可变快照，用于 metrics 上报配置变更。"""
        return {
            "requests_per_second": self.requests_per_second,
            "burst_size": self.burst_size,
            "window_size": self.window_size,
            "dynamic_adjust": self.dynamic_adjust,
        }


@dataclass
class BucketState:
    """令牌桶状态（不可变，整体替换）"""

    current_tokens: float
    last_refill_time: float  # monotonic


@dataclass
class _BucketMetrics:
    """令牌桶运行时指标（线程内聚合，读取时加锁）"""

    allowed_count: int = 0
    rejected_count: int = 0
    wait_time_total: float = 0.0
    wait_time_count: int = 0


class TokenBucket:
    """
    令牌桶限流器（对标 resilience4j AtomicRateLimiter）

    特性：
    - 惰性刷新：不维护后台线程，每次 acquire 时根据时间差计算可用令牌
    - 短临界区：Lock 仅保护状态读改写，不做 IO/日志
    - 令牌积累上限：跨周期补满至 capacity，不无限积累
    - 状态封装：BucketState 整体替换，便于未来切换到 CAS
    - 使用 time.monotonic()：不受 NTP 影响
    """

    def __init__(
        self,
        capacity: float,
        refill_rate: float,
        *,
        initial_tokens: float | None = None,
    ):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if refill_rate <= 0:
            raise ValueError("refill_rate must be positive")

        self._capacity = float(capacity)
        self._refill_rate = float(refill_rate)
        now = time.monotonic()
        self._state = BucketState(
            current_tokens=float(initial_tokens) if initial_tokens is not None else self._capacity,
            last_refill_time=now,
        )
        self._lock = Lock()
        self._metrics = _BucketMetrics()

        logger.debug(
            "TokenBucket initialized: capacity=%s refill_rate=%s", self._capacity, self._refill_rate
        )

    @property
    def capacity(self) -> float:
        """桶容量（突发上限）"""
        return self._capacity

    @property
    def refill_rate(self) -> float:
        """令牌补充速率（令牌/秒）"""
        return self._refill_rate

    def _refill(self, state: BucketState, now: float) -> BucketState:
        """根据时间差计算补充后的状态。不积累超过 capacity。"""
        elapsed = now - state.last_refill_time
        if elapsed <= 0:
            return state
        new_tokens = min(self._capacity, state.current_tokens + elapsed * self._refill_rate)
        return BucketState(current_tokens=new_tokens, last_refill_time=now)

    def acquire(self, tokens: int = 1) -> bool:
        """
        尝试获取令牌（阻塞语义：成功即返回，不 park）。

        Returns:
            True: 获取成功
            False: 令牌不足
        """
        wait = self.try_acquire(tokens)
        return wait <= 0.0

    def try_acquire(self, tokens: int = 1) -> float:
        """
        非阻塞尝试获取令牌。

        Returns:
            0.0: 获取成功
            >0.0: 需等待的秒数（调用方可 park 或放弃）
        """
        if tokens <= 0:
            return 0.0
        now = time.monotonic()
        with self._lock:
            refilled = self._refill(self._state, now)
            needed = float(tokens)
            if refilled.current_tokens >= needed:
                new_state = BucketState(
                    current_tokens=refilled.current_tokens - needed,
                    last_refill_time=refilled.last_refill_time,
                )
                self._state = new_state
                self._metrics.allowed_count += 1
                return 0.0
            # 计算需等待时间
            deficit = needed - refilled.current_tokens
            wait_seconds = deficit / self._refill_rate
            self._metrics.rejected_count += 1
            self._metrics.wait_time_total += wait_seconds
            self._metrics.wait_time_count += 1
            return wait_seconds

    def drain(self) -> None:
        """紧急排空令牌（运维用，立即拒绝所有后续请求直到补充）。"""
        with self._lock:
            self._state = BucketState(
                current_tokens=0.0,
                last_refill_time=time.monotonic(),
            )
        logger.warning("TokenBucket drained")

    def get_available_tokens(self) -> float:
        """当前可用令牌数（含惰性补充）。"""
        now = time.monotonic()
        with self._lock:
            refilled = self._refill(self._state, now)
            # 不修改内部状态，仅返回观察值
            return refilled.current_tokens

    def change_capacity(self, new_capacity: float) -> None:
        """
        运行时修改桶容量。不重置当前令牌（避免调大瞬间突发翻倍），
        但若当前令牌超过新容量则截断。
        """
        if new_capacity <= 0:
            raise ValueError("new_capacity must be positive")
        with self._lock:
            now = time.monotonic()
            refilled = self._refill(self._state, now)
            clamped_tokens = min(refilled.current_tokens, new_capacity)
            self._state = BucketState(
                current_tokens=clamped_tokens,
                last_refill_time=now,
            )
            self._capacity = float(new_capacity)
        logger.info("TokenBucket capacity changed to %s", new_capacity)

    def change_refill_rate(self, new_rate: float) -> None:
        """运行时修改补充速率。不重置当前令牌。"""
        if new_rate <= 0:
            raise ValueError("new_rate must be positive")
        with self._lock:
            now = time.monotonic()
            # 先按旧速率补充到当前时刻，再切换
            refilled = self._refill(self._state, now)
            self._state = refilled
            self._refill_rate = float(new_rate)
        logger.info("TokenBucket refill_rate changed to %s", new_rate)

    def get_stats(self) -> dict:
        """获取令牌桶统计。"""
        with self._lock:
            metrics = self._metrics
            wait_avg = (
                metrics.wait_time_total / metrics.wait_time_count
                if metrics.wait_time_count > 0
                else 0.0
            )
            return {
                "capacity": self._capacity,
                "refill_rate": self._refill_rate,
                "available_tokens": self.get_available_tokens_unlocked(),
                "allowed": metrics.allowed_count,
                "rejected": metrics.rejected_count,
                "wait_time_avg": wait_avg,
            }

    def get_available_tokens_unlocked(self) -> float:
        """获取可用令牌（调用方需持锁）。"""
        now = time.monotonic()
        refilled = self._refill(self._state, now)
        return refilled.current_tokens


class SlidingWindowCounter:
    """滑动窗口计数器（已废弃，仅保留向后兼容）。

    .. deprecated::
        该实现用 list 存储所有请求时间戳，高 QPS 下内存爆炸。
        请改用 :class:`TokenBucket`。DynamicRateLimiter 内部已切换到令牌桶。
    """

    def __init__(self, window_size: float = 1.0):
        warnings.warn(
            "SlidingWindowCounter is deprecated and memory-inefficient; use TokenBucket instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._window_size = window_size
        self._timestamps: list = []
        self._lock = RLock()

    def add(self) -> int:
        """添加一个请求，返回当前窗口内计数"""
        now = time.time()

        with self._lock:
            # 清理过期
            cutoff = now - self._window_size
            self._timestamps = [t for t in self._timestamps if t > cutoff]

            # 添加新请求
            self._timestamps.append(now)

            return len(self._timestamps)

    def count(self) -> int:
        """获取当前窗口计数"""
        now = time.time()

        with self._lock:
            cutoff = now - self._window_size
            self._timestamps = [t for t in self._timestamps if t > cutoff]
            return len(self._timestamps)

    def reset(self):
        """重置计数器"""
        with self._lock:
            self._timestamps.clear()


class DynamicRateLimiter:
    """
    动态限流器

    支持：
    - 多维度限流（全局、领域、事件类型）
    - 动态调整限流策略
    - 优先级白名单

    内部使用 TokenBucket（令牌桶）实现，惰性刷新、短临界区。
    """

    def __init__(
        self,
        default_config: RateLimitConfig | None = None,
        priority_whitelist: list | None = None,
    ):
        self._default_config = default_config or RateLimitConfig()
        self._priority_whitelist = priority_whitelist or [
            EventPriority.CRITICAL,
            EventPriority.HIGH,
        ]

        # 各维度令牌桶
        self._global_bucket = self._make_bucket(self._default_config)
        self._domain_buckets: dict[str, TokenBucket] = {}
        self._event_buckets: dict[str, TokenBucket] = {}

        # 各维度配置
        self._domain_configs: dict[str, RateLimitConfig] = {}
        self._event_configs: dict[str, RateLimitConfig] = {}

        self._lock = RLock()

        # 统计
        self._allowed_count = 0
        self._rejected_count = 0

        logger.info("DynamicRateLimiter initialized")

    @staticmethod
    def _make_bucket(config: RateLimitConfig) -> TokenBucket:
        """根据 RateLimitConfig 构造令牌桶。"""
        return TokenBucket(
            capacity=float(config.burst_size),
            refill_rate=float(config.requests_per_second),
        )

    def _get_domain_bucket(self, domain: str) -> TokenBucket:
        """获取或创建领域令牌桶（短临界区，仅保护字典）。"""
        with self._lock:
            bucket = self._domain_buckets.get(domain)
            if bucket is None:
                config = self._domain_configs.get(domain, self._default_config)
                bucket = self._make_bucket(config)
                self._domain_buckets[domain] = bucket
            return bucket

    def _get_event_bucket(self, event_type: str) -> TokenBucket:
        """获取或创建事件类型令牌桶（短临界区，仅保护字典）。"""
        with self._lock:
            bucket = self._event_buckets.get(event_type)
            if bucket is None:
                config = self._event_configs.get(event_type, self._default_config)
                bucket = self._make_bucket(config)
                self._event_buckets[event_type] = bucket
            return bucket

    def _incr_allowed(self) -> None:
        with self._lock:
            self._allowed_count += 1

    def _incr_rejected(self) -> None:
        with self._lock:
            self._rejected_count += 1

    def set_domain_limit(self, domain: str, config: RateLimitConfig):
        """设置领域限流配置。若该领域已有令牌桶，则热更新容量与速率，不重置令牌。"""
        with self._lock:
            self._domain_configs[domain] = config
            bucket = self._domain_buckets.get(domain)
            if bucket is not None:
                bucket.change_capacity(float(config.burst_size))
                bucket.change_refill_rate(float(config.requests_per_second))
        logger.info(
            "Domain [%s] limit updated: rps=%s burst=%s",
            domain,
            config.requests_per_second,
            config.burst_size,
        )

    def set_event_limit(self, event_type: str, config: RateLimitConfig):
        """设置事件类型限流配置。若已有令牌桶，则热更新。"""
        with self._lock:
            self._event_configs[event_type] = config
            bucket = self._event_buckets.get(event_type)
            if bucket is not None:
                bucket.change_capacity(float(config.burst_size))
                bucket.change_refill_rate(float(config.requests_per_second))
        logger.info(
            "Event [%s] limit updated: rps=%s burst=%s",
            event_type,
            config.requests_per_second,
            config.burst_size,
        )

    def change_limit_for_period(self, new_rps: float) -> None:
        """运行时动态修改默认限流速率（RPS）。不重置当前令牌。"""
        if new_rps <= 0:
            raise ValueError("new_rps must be positive")
        with self._lock:
            self._default_config = RateLimitConfig(
                requests_per_second=new_rps,
                burst_size=self._default_config.burst_size,
                window_size=self._default_config.window_size,
                dynamic_adjust=self._default_config.dynamic_adjust,
            )
            self._global_bucket.change_refill_rate(new_rps)
        logger.info("Default rate limit changed: rps=%s", new_rps)

    def change_burst_size(self, new_burst: int) -> None:
        """运行时动态修改默认突发大小。不重置当前令牌。"""
        if new_burst <= 0:
            raise ValueError("new_burst must be positive")
        with self._lock:
            self._default_config = RateLimitConfig(
                requests_per_second=self._default_config.requests_per_second,
                burst_size=new_burst,
                window_size=self._default_config.window_size,
                dynamic_adjust=self._default_config.dynamic_adjust,
            )
            self._global_bucket.change_capacity(float(new_burst))
        logger.info("Default burst size changed: burst=%s", new_burst)

    def allow(self, event: NeuroEvent) -> bool:
        """
        检查是否允许处理该事件

        Returns:
            True: 允许通过
            False: 被限流
        """
        allowed, _ = self.try_allow(event)
        return allowed

    def try_allow(self, event: NeuroEvent) -> tuple[bool, float]:
        """
        非阻塞检查是否允许处理该事件。

        Returns:
            (是否允许, 需等待秒数)。允许时等待为 0.0。
        """
        # 高优先级白名单
        if event.priority in self._priority_whitelist:
            return True, 0.0

        max_wait = 0.0

        # 1. 检查全局限流
        wait = self._global_bucket.try_acquire(1)
        if wait > 0.0:
            self._incr_rejected()
            logger.warning(
                "Global rate limit exceeded: wait=%.4fs available=%.2f",
                wait,
                self._global_bucket.get_available_tokens(),
            )
            return False, wait
        max_wait = max(max_wait, wait)

        # 2. 检查领域限流
        domain = event.metadata.domain
        if domain:
            domain_bucket = self._get_domain_bucket(domain)
            wait = domain_bucket.try_acquire(1)
            if wait > 0.0:
                self._incr_rejected()
                logger.warning("Domain rate limit exceeded [%s]: wait=%.4fs", domain, wait)
                return False, wait
            max_wait = max(max_wait, wait)

        # 3. 检查事件类型限流
        event_type = event.event_type
        event_bucket = self._get_event_bucket(event_type)
        wait = event_bucket.try_acquire(1)
        if wait > 0.0:
            self._incr_rejected()
            logger.warning("Event type rate limit exceeded [%s]: wait=%.4fs", event_type, wait)
            return False, wait
        max_wait = max(max_wait, wait)

        self._incr_allowed()
        return True, max_wait

    def drain_domain(self, domain: str) -> None:
        """紧急排空某领域的令牌桶。"""
        with self._lock:
            bucket = self._domain_buckets.get(domain)
        if bucket is not None:
            bucket.drain()
            logger.warning("Domain [%s] bucket drained", domain)

    def drain_event(self, event_type: str) -> None:
        """紧急排空某事件类型的令牌桶。"""
        with self._lock:
            bucket = self._event_buckets.get(event_type)
        if bucket is not None:
            bucket.drain()
            logger.warning("Event [%s] bucket drained", event_type)

    def get_stats(self) -> dict:
        """获取统计（含令牌桶指标与配置快照）。"""
        with self._lock:
            global_stats = self._global_bucket.get_stats()
            domain_stats = {
                name: bucket.get_stats() for name, bucket in self._domain_buckets.items()
            }
            event_stats = {name: bucket.get_stats() for name, bucket in self._event_buckets.items()}
            return {
                "allowed": self._allowed_count,
                "rejected": self._rejected_count,
                "global_count": int(global_stats["allowed"] + global_stats["rejected"]),
                "available_tokens": global_stats["available_tokens"],
                "wait_time_avg": global_stats["wait_time_avg"],
                "config_snapshot": self._default_config.to_snapshot(),
                "domains": list(self._domain_buckets.keys()),
                "event_types": list(self._event_buckets.keys()),
                "domain_stats": domain_stats,
                "event_stats": event_stats,
            }


class NeuroRateLimiter:
    """
    NeuroBus 专用限流器

    提供领域感知的限流策略，支持运行时动态调整各领域配置。
    """

    # 各领域的默认限流配置
    DOMAIN_LIMITS = {
        "intent": RateLimitConfig(
            requests_per_second=50.0,  # 意图识别高频
            burst_size=100,
        ),
        "payment": RateLimitConfig(
            requests_per_second=5.0,  # 支付保守
            burst_size=10,
        ),
        "wechat": RateLimitConfig(
            requests_per_second=30.0,  # 微信中等
            burst_size=50,
        ),
        "default": RateLimitConfig(
            requests_per_second=20.0,
            burst_size=40,
        ),
    }

    def __init__(self):
        self._limiter = DynamicRateLimiter(default_config=self.DOMAIN_LIMITS["default"])

        # 设置各领域限流
        for domain, config in self.DOMAIN_LIMITS.items():
            if domain != "default":
                self._limiter.set_domain_limit(domain, config)

    def check_rate(self, event: NeuroEvent) -> bool:
        """检查事件是否通过限流"""
        return self._limiter.allow(event)

    def try_check_rate(self, event: NeuroEvent) -> tuple[bool, float]:
        """非阻塞检查事件是否通过限流，返回 (是否允许, 需等待秒数)。"""
        return self._limiter.try_allow(event)

    def set_domain_limit(self, domain: str, config: RateLimitConfig) -> None:
        """运行时动态调整某领域的限流配置。"""
        self._limiter.set_domain_limit(domain, config)
        logger.info("NeuroRateLimiter domain [%s] config updated", domain)

    def set_event_limit(self, event_type: str, config: RateLimitConfig) -> None:
        """运行时动态调整某事件类型的限流配置。"""
        self._limiter.set_event_limit(event_type, config)
        logger.info("NeuroRateLimiter event [%s] config updated", event_type)

    def change_default_limit(self, new_rps: float) -> None:
        """运行时动态修改默认 RPS。"""
        self._limiter.change_limit_for_period(new_rps)

    def change_default_burst(self, new_burst: int) -> None:
        """运行时动态修改默认突发大小。"""
        self._limiter.change_burst_size(new_burst)

    def drain_domain(self, domain: str) -> None:
        """紧急排空某领域的令牌桶（运维用）。"""
        self._limiter.drain_domain(domain)

    def drain_event(self, event_type: str) -> None:
        """紧急排空某事件类型的令牌桶（运维用）。"""
        self._limiter.drain_event(event_type)

    def get_stats(self) -> dict:
        """获取统计"""
        return self._limiter.get_stats()

    def get_all_metrics(self) -> dict:
        """
        获取所有维度的 metrics（全局 + 各领域 + 各事件类型）。

        用于监控面板与配置变更追踪。
        """
        base = self._limiter.get_stats()
        return {
            "allowed": base["allowed"],
            "rejected": base["rejected"],
            "available_tokens": base["available_tokens"],
            "wait_time_avg": base["wait_time_avg"],
            "config_snapshot": base["config_snapshot"],
            "global": base,
            "domains": base["domain_stats"],
            "event_types": base["event_stats"],
        }
