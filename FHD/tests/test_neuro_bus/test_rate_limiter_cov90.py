"""rate_limiter.py 真实行为测试（覆盖未测分支）。

聚焦 TokenBucket 的参数校验/属性/惰性刷新/drain/热更新，
DynamicRateLimiter 的热更新与 drain，以及 NeuroRateLimiter 的薄包装委托。

所有时间相关测试通过 patch `app.neuro_bus.rate_limiter.time.monotonic` 保持确定性。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import app.neuro_bus.rate_limiter as rl_mod
from app.neuro_bus.events.base import EventMetadata, EventPriority, NeuroEvent
from app.neuro_bus.rate_limiter import (
    BucketState,
    DynamicRateLimiter,
    NeuroRateLimiter,
    RateLimitConfig,
    TokenBucket,
)


def _make_event(
    event_type: str = "test.event",
    priority: EventPriority = EventPriority.NORMAL,
    domain: str = "global",
) -> NeuroEvent:
    return NeuroEvent(
        event_type=event_type,
        payload={"k": "v"},
        priority=priority,
        metadata=EventMetadata(domain=domain),
    )


# ════════════════════════════════════════════════════════════════════════════
# TokenBucket: 构造校验 & 属性
# ════════════════════════════════════════════════════════════════════════════


class TestTokenBucketInit:
    def test_capacity_non_positive_raises(self):
        with pytest.raises(ValueError, match="capacity must be positive"):
            TokenBucket(capacity=0, refill_rate=1.0)

    def test_refill_rate_non_positive_raises(self):
        with pytest.raises(ValueError, match="refill_rate must be positive"):
            TokenBucket(capacity=5.0, refill_rate=0)

    def test_capacity_property(self):
        bucket = TokenBucket(capacity=7.0, refill_rate=2.0)
        assert bucket.capacity == 7.0

    def test_refill_rate_property(self):
        bucket = TokenBucket(capacity=7.0, refill_rate=2.5)
        assert bucket.refill_rate == 2.5

    def test_initial_tokens_respected(self):
        with patch.object(rl_mod.time, "monotonic", return_value=100.0):
            bucket = TokenBucket(capacity=10.0, refill_rate=1.0, initial_tokens=3.0)
            # 同一时刻读取（elapsed==0），不补充，应等于 initial_tokens
            assert bucket.get_available_tokens() == 3.0

    def test_initial_tokens_default_full(self):
        with patch.object(rl_mod.time, "monotonic", return_value=100.0):
            bucket = TokenBucket(capacity=10.0, refill_rate=1.0)
            assert bucket.get_available_tokens() == 10.0


# ════════════════════════════════════════════════════════════════════════════
# TokenBucket: 惰性刷新 / acquire / try_acquire 边界
# ════════════════════════════════════════════════════════════════════════════


class TestTokenBucketRefill:
    def test_refill_elapsed_non_positive_returns_same_state(self):
        bucket = TokenBucket(capacity=10.0, refill_rate=1.0)
        state = BucketState(current_tokens=5.0, last_refill_time=100.0)
        # now 早于 last_refill_time -> elapsed < 0 -> 返回原状态对象
        result = bucket._refill(state, now=99.0)
        assert result is state

    def test_refill_accumulates_but_caps_at_capacity(self):
        # 起步 0 token，经过 100 秒、速率 2/s -> 200 但被 capacity=10 截断
        clock = [0.0]
        with patch.object(rl_mod.time, "monotonic", side_effect=lambda: clock[0]):
            bucket = TokenBucket(capacity=10.0, refill_rate=2.0, initial_tokens=0.0)
            clock[0] = 100.0
            assert bucket.get_available_tokens() == 10.0

    def test_acquire_success_returns_true(self):
        bucket = TokenBucket(capacity=5.0, refill_rate=1.0)
        assert bucket.acquire(1) is True

    def test_acquire_insufficient_returns_false(self):
        clock = [0.0]
        with patch.object(rl_mod.time, "monotonic", side_effect=lambda: clock[0]):
            bucket = TokenBucket(capacity=1.0, refill_rate=0.001, initial_tokens=0.5)
            # 需要 1 token 但仅 0.5，且补充极慢 -> acquire False
            assert bucket.acquire(1) is False

    def test_try_acquire_non_positive_tokens_returns_zero(self):
        bucket = TokenBucket(capacity=5.0, refill_rate=1.0)
        assert bucket.try_acquire(0) == 0.0
        assert bucket.try_acquire(-3) == 0.0

    def test_try_acquire_deficit_returns_wait_seconds(self):
        clock = [0.0]
        with patch.object(rl_mod.time, "monotonic", side_effect=lambda: clock[0]):
            bucket = TokenBucket(capacity=10.0, refill_rate=2.0, initial_tokens=1.0)
            # 需要 5 tokens，有 1，缺 4，速率 2/s -> 等待 2.0s
            wait = bucket.try_acquire(5)
            assert wait == pytest.approx(2.0)
            stats = bucket.get_stats()
            assert stats["rejected"] == 1
            assert stats["allowed"] == 0


# ════════════════════════════════════════════════════════════════════════════
# TokenBucket: drain / 热更新
# ════════════════════════════════════════════════════════════════════════════


class TestTokenBucketDrainAndChange:
    def test_drain_empties_tokens(self):
        with patch.object(rl_mod.time, "monotonic", return_value=50.0):
            bucket = TokenBucket(capacity=10.0, refill_rate=1.0)
            bucket.drain()
            # 同一时刻读取，elapsed==0，应仍为 0
            assert bucket.get_available_tokens() == 0.0
            # drain 后立即获取应失败
            assert bucket.acquire(1) is False

    def test_change_capacity_non_positive_raises(self):
        bucket = TokenBucket(capacity=10.0, refill_rate=1.0)
        with pytest.raises(ValueError, match="new_capacity must be positive"):
            bucket.change_capacity(0)

    def test_change_capacity_clamps_tokens_down(self):
        with patch.object(rl_mod.time, "monotonic", return_value=10.0):
            bucket = TokenBucket(capacity=10.0, refill_rate=1.0)  # 满 10
            bucket.change_capacity(4.0)
            assert bucket.capacity == 4.0
            # 当前 token 被截断到新容量
            assert bucket.get_available_tokens() == 4.0

    def test_change_capacity_does_not_inflate_existing_tokens(self):
        with patch.object(rl_mod.time, "monotonic", return_value=10.0):
            bucket = TokenBucket(capacity=10.0, refill_rate=1.0, initial_tokens=3.0)
            bucket.change_capacity(20.0)
            assert bucket.capacity == 20.0
            # 调大容量不应凭空增加当前令牌
            assert bucket.get_available_tokens() == 3.0

    def test_change_refill_rate_non_positive_raises(self):
        bucket = TokenBucket(capacity=10.0, refill_rate=1.0)
        with pytest.raises(ValueError, match="new_rate must be positive"):
            bucket.change_refill_rate(-1.0)

    def test_change_refill_rate_updates_property_and_keeps_tokens(self):
        clock = [0.0]
        with patch.object(rl_mod.time, "monotonic", side_effect=lambda: clock[0]):
            bucket = TokenBucket(capacity=10.0, refill_rate=1.0, initial_tokens=2.0)
            clock[0] = 3.0  # 旧速率补充 3 token -> 5
            bucket.change_refill_rate(4.0)
            assert bucket.refill_rate == 4.0
            # 切换瞬间已按旧速率补到 5（不重置）
            assert bucket.get_available_tokens() == pytest.approx(5.0)


# ════════════════════════════════════════════════════════════════════════════
# DynamicRateLimiter: 热更新（已存在桶时走 change_* 路径）
# ════════════════════════════════════════════════════════════════════════════


class TestDynamicRateLimiterHotUpdate:
    def test_set_domain_limit_hot_updates_existing_bucket(self):
        limiter = DynamicRateLimiter(default_config=RateLimitConfig(burst_size=100))
        # 先触发创建 payment 桶
        limiter.allow(_make_event(domain="payment"))
        # 再热更新该领域配置 -> 走 change_capacity/change_refill_rate 分支
        limiter.set_domain_limit("payment", RateLimitConfig(requests_per_second=5.0, burst_size=10))
        bucket = limiter._get_domain_bucket("payment")
        assert bucket.capacity == 10.0
        assert bucket.refill_rate == 5.0

    def test_set_event_limit_hot_updates_existing_bucket(self):
        limiter = DynamicRateLimiter(default_config=RateLimitConfig(burst_size=100))
        limiter.allow(_make_event("evt.x"))
        limiter.set_event_limit("evt.x", RateLimitConfig(requests_per_second=7.0, burst_size=14))
        bucket = limiter._get_event_bucket("evt.x")
        assert bucket.capacity == 14.0
        assert bucket.refill_rate == 7.0

    def test_set_domain_limit_no_existing_bucket_only_stores_config(self):
        limiter = DynamicRateLimiter(default_config=RateLimitConfig(burst_size=100))
        # 未创建桶时设置配置：仅存储 config，不触发 change_*
        limiter.set_domain_limit(
            "brand_new", RateLimitConfig(requests_per_second=3.0, burst_size=6)
        )
        # 首次使用时才按配置建桶
        bucket = limiter._get_domain_bucket("brand_new")
        assert bucket.capacity == 6.0
        assert bucket.refill_rate == 3.0


class TestDynamicRateLimiterChangeDefaults:
    def test_change_limit_for_period_non_positive_raises(self):
        limiter = DynamicRateLimiter()
        with pytest.raises(ValueError, match="new_rps must be positive"):
            limiter.change_limit_for_period(0)

    def test_change_limit_for_period_updates_config_and_global_bucket(self):
        limiter = DynamicRateLimiter(default_config=RateLimitConfig(requests_per_second=10.0))
        limiter.change_limit_for_period(33.0)
        assert limiter._default_config.requests_per_second == 33.0
        assert limiter._global_bucket.refill_rate == 33.0

    def test_change_burst_size_non_positive_raises(self):
        limiter = DynamicRateLimiter()
        with pytest.raises(ValueError, match="new_burst must be positive"):
            limiter.change_burst_size(-5)

    def test_change_burst_size_updates_config_and_global_capacity(self):
        limiter = DynamicRateLimiter(default_config=RateLimitConfig(burst_size=20))
        limiter.change_burst_size(77)
        assert limiter._default_config.burst_size == 77
        assert limiter._global_bucket.capacity == 77.0


class TestDynamicRateLimiterDrain:
    def test_drain_domain_existing(self):
        limiter = DynamicRateLimiter(default_config=RateLimitConfig(burst_size=100))
        limiter.allow(_make_event(domain="payment"))
        limiter.drain_domain("payment")
        bucket = limiter._get_domain_bucket("payment")
        # drain 后令牌应为 0（同时刻读取近似 0）
        assert bucket.get_available_tokens() < 1.0

    def test_drain_domain_missing_is_noop(self):
        limiter = DynamicRateLimiter()
        # 不存在的领域 -> bucket is None 分支，不抛异常
        limiter.drain_domain("ghost")
        assert "ghost" not in limiter._domain_buckets

    def test_drain_event_existing(self):
        limiter = DynamicRateLimiter(default_config=RateLimitConfig(burst_size=100))
        limiter.allow(_make_event("evt.y"))
        limiter.drain_event("evt.y")
        bucket = limiter._get_event_bucket("evt.y")
        assert bucket.get_available_tokens() < 1.0

    def test_drain_event_missing_is_noop(self):
        limiter = DynamicRateLimiter()
        limiter.drain_event("ghost.evt")
        assert "ghost.evt" not in limiter._event_buckets


# ════════════════════════════════════════════════════════════════════════════
# NeuroRateLimiter: 薄包装委托（patch 内部 _limiter 验证委托）
# ════════════════════════════════════════════════════════════════════════════


class TestNeuroRateLimiterDelegation:
    def test_try_check_rate_delegates(self):
        limiter = NeuroRateLimiter()
        limiter._limiter = MagicMock()
        limiter._limiter.try_allow.return_value = (False, 1.5)
        event = _make_event()
        result = limiter.try_check_rate(event)
        assert result == (False, 1.5)
        limiter._limiter.try_allow.assert_called_once_with(event)

    def test_set_domain_limit_delegates(self):
        limiter = NeuroRateLimiter()
        limiter._limiter = MagicMock()
        cfg = RateLimitConfig(requests_per_second=9.0, burst_size=18)
        limiter.set_domain_limit("payment", cfg)
        limiter._limiter.set_domain_limit.assert_called_once_with("payment", cfg)

    def test_set_event_limit_delegates(self):
        limiter = NeuroRateLimiter()
        limiter._limiter = MagicMock()
        cfg = RateLimitConfig(requests_per_second=2.0, burst_size=4)
        limiter.set_event_limit("evt.z", cfg)
        limiter._limiter.set_event_limit.assert_called_once_with("evt.z", cfg)

    def test_change_default_limit_delegates(self):
        limiter = NeuroRateLimiter()
        limiter._limiter = MagicMock()
        limiter.change_default_limit(42.0)
        limiter._limiter.change_limit_for_period.assert_called_once_with(42.0)

    def test_change_default_burst_delegates(self):
        limiter = NeuroRateLimiter()
        limiter._limiter = MagicMock()
        limiter.change_default_burst(64)
        limiter._limiter.change_burst_size.assert_called_once_with(64)

    def test_drain_domain_delegates(self):
        limiter = NeuroRateLimiter()
        limiter._limiter = MagicMock()
        limiter.drain_domain("payment")
        limiter._limiter.drain_domain.assert_called_once_with("payment")

    def test_drain_event_delegates(self):
        limiter = NeuroRateLimiter()
        limiter._limiter = MagicMock()
        limiter.drain_event("evt.q")
        limiter._limiter.drain_event.assert_called_once_with("evt.q")

    def test_get_all_metrics_shape(self):
        limiter = NeuroRateLimiter()
        # 真实跑一次让 global 桶产生统计
        limiter.check_rate(_make_event(domain="intent"))
        metrics = limiter.get_all_metrics()
        # 验证聚合结构字段齐全且与 base 对应
        for key in (
            "allowed",
            "rejected",
            "available_tokens",
            "wait_time_avg",
            "config_snapshot",
            "global",
            "domains",
            "event_types",
        ):
            assert key in metrics
        assert isinstance(metrics["domains"], dict)
        assert isinstance(metrics["event_types"], dict)
        # global 即 base 快照本身
        assert metrics["global"]["allowed"] == metrics["allowed"]

    def test_neuro_rate_limiter_domain_configs_applied(self):
        # NeuroRateLimiter 构造时应把 DOMAIN_LIMITS 注入各领域配置（payment 保守）
        limiter = NeuroRateLimiter()
        bucket = limiter._limiter._get_domain_bucket("payment")
        assert bucket.capacity == 10.0
        assert bucket.refill_rate == 5.0
