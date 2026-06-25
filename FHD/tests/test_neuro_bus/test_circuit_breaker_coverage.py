"""熔断器 (CircuitBreaker) 真实行为测试。

覆盖状态机转换 CLOSED -> OPEN -> HALF_OPEN -> CLOSED/OPEN、
连续失败快速熔断、滑动窗口失败率熔断、慢调用率熔断、
半开试探配额、超时自动转半开（惰性检查）、
execute/execute_async 的成功/失败/fallback/超时路径、
RollingWindowCounter 桶计数与过期、metrics/Prometheus 输出、
以及 NeuroCircuitBreakerManager 的多熔断器管理。

monotonic 时间用 monkeypatch 控制状态机的超时与窗口逻辑。
"""

from __future__ import annotations

import asyncio

import pytest

import app.neuro_bus.circuit_breaker as cb_mod
from app.neuro_bus.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpen,
    CircuitState,
    NeuroCircuitBreakerManager,
    RollingWindowCounter,
    get_circuit_breaker,
)


class FakeClock:
    """可控的 monotonic 时钟。"""

    def __init__(self, start: float = 1000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock()
    monkeypatch.setattr(cb_mod.time, "monotonic", c)
    return c


# ========================================================================
# RollingWindowCounter
# ========================================================================


def test_rolling_window_basic_counts(clock):
    w = RollingWindowCounter(window_size_seconds=10.0, bucket_size_seconds=1.0)
    w.record_success()
    w.record_success()
    w.record_failure()
    w.record_timeout()
    w.record_slow_call()
    w.record_rejection()
    stats = w.get_stats()
    # total 不含 rejection
    assert stats["total"] == 4  # 2 success + 1 failure + 1 timeout
    assert stats["success"] == 2
    assert stats["failure"] == 1
    assert stats["timeout"] == 1
    assert stats["rejection"] == 1
    assert stats["slow_call"] == 1
    # failure_rate = (failure + timeout) / total
    assert stats["failure_rate"] == pytest.approx(2 / 4)
    assert stats["slow_call_rate"] == pytest.approx(1 / 4)


def test_rolling_window_empty_rates_zero(clock):
    w = RollingWindowCounter()
    stats = w.get_stats()
    assert stats["total"] == 0
    assert stats["failure_rate"] == 0.0
    assert stats["slow_call_rate"] == 0.0


def test_rolling_window_bucket_expiry(clock):
    w = RollingWindowCounter(window_size_seconds=5.0, bucket_size_seconds=1.0)
    w.record_failure()
    assert w.get_stats()["failure"] == 1
    # 推进超过窗口 -> 旧桶被淘汰
    clock.advance(10.0)
    w.record_success()
    stats = w.get_stats()
    assert stats["failure"] == 0  # 过期失败已淘汰
    assert stats["success"] == 1


def test_rolling_window_reuses_current_bucket(clock):
    w = RollingWindowCounter(window_size_seconds=10.0, bucket_size_seconds=1.0)
    w.record_success()
    w.record_success()  # 同一桶内复用
    # 在同一秒内，应只有一个桶
    assert len(w._buckets) == 1
    assert w.get_stats()["success"] == 2


def test_rolling_window_reset(clock):
    w = RollingWindowCounter()
    w.record_failure()
    w.reset()
    assert w.get_stats()["total"] == 0


# ========================================================================
# 初始状态 & 状态属性
# ========================================================================


def test_initial_state_closed(clock):
    cb = CircuitBreaker("svc")
    assert cb.state == CircuitState.CLOSED
    assert cb.can_execute() is True


# ========================================================================
# CLOSED -> OPEN: 连续失败快速熔断
# ========================================================================


def test_consecutive_failure_opens(clock):
    cb = CircuitBreaker("svc", CircuitBreakerConfig(failure_threshold=3))
    for _ in range(2):
        cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    cb.record_failure()  # 第3次达阈值
    assert cb.state == CircuitState.OPEN
    # OPEN 状态拒绝执行（未到超时）
    assert cb.can_execute() is False


def test_success_resets_consecutive_failures(clock):
    cb = CircuitBreaker("svc", CircuitBreakerConfig(failure_threshold=3))
    cb.record_failure()
    cb.record_failure()
    cb.record_success()  # 重置连续失败计数
    assert cb.get_stats()["failure_count"] == 0
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED  # 未连续达 3


# ========================================================================
# CLOSED -> OPEN: 滑动窗口失败率熔断
# ========================================================================


def test_failure_rate_threshold_opens(clock):
    # failure_threshold 很高，避免快速熔断先触发；靠失败率熔断
    cfg = CircuitBreakerConfig(
        failure_threshold=1000,
        minimum_number_of_calls=10,
        failure_rate_threshold=0.5,
    )
    cb = CircuitBreaker("svc", cfg)
    # 6 成功 + 5 失败 = 11 calls, failure_rate = 5/11 < 0.5 -> 仍 CLOSED
    for _ in range(6):
        cb.record_success()
    for _ in range(4):
        cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    # 再加失败拉高失败率到 >= 0.5
    for _ in range(6):
        cb.record_failure()
    assert cb.state == CircuitState.OPEN


def test_failure_rate_below_minimum_calls_no_open(clock):
    cfg = CircuitBreakerConfig(
        failure_threshold=1000,
        minimum_number_of_calls=20,
        failure_rate_threshold=0.5,
    )
    cb = CircuitBreaker("svc", cfg)
    # 全失败但样本量 < minimum -> 不熔断
    for _ in range(5):
        cb.record_failure()
    assert cb.state == CircuitState.CLOSED


# ========================================================================
# CLOSED -> OPEN: 慢调用率熔断
# ========================================================================


def test_slow_call_rate_threshold_opens(clock):
    cfg = CircuitBreakerConfig(
        failure_threshold=1000,
        minimum_number_of_calls=10,
        failure_rate_threshold=0.99,  # 失败率不会触发
        slow_call_rate_threshold=0.8,
    )
    cb = CircuitBreaker("svc", cfg)
    # 10 次调用，9 次慢 + 记一次失败触发判定路径
    for _ in range(9):
        cb.record_success()
        cb.record_slow_call()
    # 此时 total=9, slow=9；但需达 minimum=10 且通过 record_failure 触发判定
    cb.record_failure()  # total -> 10, slow_call_rate = 9/10 = 0.9 >= 0.8
    assert cb.state == CircuitState.OPEN


# ========================================================================
# OPEN -> HALF_OPEN: 超时自动转半开（惰性检查）
# ========================================================================


def test_open_to_half_open_after_timeout(clock):
    cfg = CircuitBreakerConfig(failure_threshold=1, timeout_seconds=30.0)
    cb = CircuitBreaker("svc", cfg)
    cb.record_failure()  # -> OPEN
    assert cb.state == CircuitState.OPEN
    assert cb.can_execute() is False
    # 推进超过 timeout_seconds -> 惰性转 HALF_OPEN
    clock.advance(31.0)
    assert cb.can_execute() is True  # 惰性转半开并放行第一个试探
    assert cb.state == CircuitState.HALF_OPEN


def test_open_stays_open_before_timeout(clock):
    cfg = CircuitBreakerConfig(failure_threshold=1, timeout_seconds=30.0)
    cb = CircuitBreaker("svc", cfg)
    cb.record_failure()
    clock.advance(10.0)  # 未到 timeout
    assert cb.can_execute() is False
    assert cb.state == CircuitState.OPEN


def test_open_no_auto_transition_when_disabled(clock):
    cfg = CircuitBreakerConfig(
        failure_threshold=1,
        timeout_seconds=30.0,
        automatic_transition_from_open_to_half_open=False,
    )
    cb = CircuitBreaker("svc", cfg)
    cb.record_failure()
    clock.advance(100.0)  # 即使超时也不自动转
    assert cb.can_execute() is False
    assert cb.state == CircuitState.OPEN


# ========================================================================
# HALF_OPEN -> CLOSED / OPEN
# ========================================================================


def test_half_open_to_closed_on_success_threshold(clock):
    cfg = CircuitBreakerConfig(failure_threshold=1, timeout_seconds=30.0, success_threshold=2)
    cb = CircuitBreaker("svc", cfg)
    cb.record_failure()  # OPEN
    clock.advance(31.0)
    assert cb.can_execute() is True  # -> HALF_OPEN
    assert cb.state == CircuitState.HALF_OPEN
    cb.record_success()
    assert cb.state == CircuitState.HALF_OPEN  # 1 < 2
    cb.record_success()
    assert cb.state == CircuitState.CLOSED  # 达 success_threshold
    # CLOSED 后计数器已重置
    assert cb.get_stats()["failure_count"] == 0


def test_half_open_to_open_on_failure(clock):
    cfg = CircuitBreakerConfig(failure_threshold=1, timeout_seconds=30.0)
    cb = CircuitBreaker("svc", cfg)
    cb.record_failure()  # OPEN
    clock.advance(31.0)
    cb.can_execute()  # -> HALF_OPEN
    assert cb.state == CircuitState.HALF_OPEN
    cb.record_failure()  # 半开再次失败 -> 立即 OPEN
    assert cb.state == CircuitState.OPEN


def test_record_slow_call_in_half_open(clock):
    """半开状态下慢调用同时计入主窗口与半开窗口。"""
    cfg = CircuitBreakerConfig(failure_threshold=1, timeout_seconds=30.0)
    cb = CircuitBreaker("svc", cfg)
    cb.record_failure()  # OPEN
    clock.advance(31.0)
    cb.can_execute()  # -> HALF_OPEN
    assert cb.state == CircuitState.HALF_OPEN
    cb.record_slow_call()
    assert cb.get_metrics()["slow_calls"] == 1


def test_record_success_closed_no_prior_failures(clock):
    """CLOSED 状态成功、且无在途失败计数时直接返回（不重置分支）。"""
    cb = CircuitBreaker("svc")
    cb.record_success()  # failure_count 本就为 0
    assert cb.get_stats()["failure_count"] == 0
    assert cb.state == CircuitState.CLOSED


def test_half_open_limits_probe_calls(clock):
    cfg = CircuitBreakerConfig(failure_threshold=1, timeout_seconds=30.0, half_open_max_calls=2)
    cb = CircuitBreaker("svc", cfg)
    cb.record_failure()
    clock.advance(31.0)
    # 第一个 can_execute 触发转半开并放行（不计入配额）
    assert cb.can_execute() is True
    assert cb.state == CircuitState.HALF_OPEN
    # 后续 can_execute 计入 half_open_calls 配额 (max=2)
    assert cb.can_execute() is True  # call 1
    assert cb.can_execute() is True  # call 2
    assert cb.can_execute() is False  # 超出配额


# ========================================================================
# 状态转换回调
# ========================================================================


def test_state_change_callback_fired(clock):
    cfg = CircuitBreakerConfig(failure_threshold=1)
    cb = CircuitBreaker("svc", cfg)
    transitions = []
    cb.on_state_change(lambda old, new, ctx: transitions.append((old, new, ctx.get("reason"))))
    cb.record_failure()  # CLOSED -> OPEN
    assert transitions == [
        (CircuitState.CLOSED, CircuitState.OPEN, "consecutive_failure_threshold")
    ]


def test_state_change_callback_exception_swallowed(clock):
    cfg = CircuitBreakerConfig(failure_threshold=1)
    cb = CircuitBreaker("svc", cfg)

    def boom(old, new, ctx):
        raise RuntimeError("callback exploded")

    cb.on_state_change(boom)
    # 回调异常不应影响熔断
    cb.record_failure()
    assert cb.state == CircuitState.OPEN


def test_transition_to_same_state_noop(clock):
    cb = CircuitBreaker("svc")
    fired = []
    cb.on_state_change(lambda o, n, c: fired.append((o, n)))
    cb._transition_to(CircuitState.CLOSED)  # 已是 CLOSED
    assert fired == []  # 无转换，不触发回调


# ========================================================================
# execute (sync)
# ========================================================================


def test_execute_success(clock):
    cb = CircuitBreaker("svc")
    result = cb.execute(lambda x: x * 2, 21)
    assert result == 42
    assert cb.get_metrics()["successful_calls"] == 1


def test_execute_failure_propagates_without_fallback(clock):
    cb = CircuitBreaker("svc", CircuitBreakerConfig(failure_threshold=10))

    def fail():
        raise ValueError("boom")

    with pytest.raises(ValueError):
        cb.execute(fail)
    assert cb.get_metrics()["failed_calls"] == 1


def test_execute_failure_uses_fallback(clock):
    cfg = CircuitBreakerConfig(failure_threshold=10, fallback=lambda: "fallback-value")
    cb = CircuitBreaker("svc", cfg)

    def fail():
        raise ValueError("boom")

    result = cb.execute(fail)
    assert result == "fallback-value"
    m = cb.get_metrics()
    assert m["failed_calls"] == 1
    assert m["fallback_success"] == 1


def test_execute_open_uses_fallback(clock):
    cfg = CircuitBreakerConfig(failure_threshold=1, fallback=lambda: "fb")
    cb = CircuitBreaker("svc", cfg)
    cb.record_failure()  # OPEN
    result = cb.execute(lambda: "should-not-run")
    assert result == "fb"
    assert cb.get_metrics()["rejected_calls"] == 1


def test_execute_open_no_fallback_raises(clock):
    cfg = CircuitBreakerConfig(failure_threshold=1)
    cb = CircuitBreaker("svc", cfg)
    cb.record_failure()  # OPEN
    with pytest.raises(CircuitBreakerOpen):
        cb.execute(lambda: 1)
    assert cb.get_metrics()["rejected_calls"] == 1


def test_execute_records_slow_call(clock):
    cfg = CircuitBreakerConfig(slow_call_duration_threshold=0.5)
    cb = CircuitBreaker("svc", cfg)

    def slow():
        clock.advance(1.0)  # 推进 monotonic 模拟耗时 1s > 0.5s
        return "ok"

    result = cb.execute(slow)
    assert result == "ok"
    assert cb.get_metrics()["slow_calls"] == 1


def test_execute_slow_call_on_failure(clock):
    cfg = CircuitBreakerConfig(failure_threshold=10, slow_call_duration_threshold=0.5)
    cb = CircuitBreaker("svc", cfg)

    def slow_fail():
        clock.advance(1.0)
        raise ValueError("slow boom")

    with pytest.raises(ValueError):
        cb.execute(slow_fail)
    m = cb.get_metrics()
    assert m["slow_calls"] == 1
    assert m["failed_calls"] == 1


def test_execute_non_recoverable_propagates(clock):
    """非 RECOVERABLE_ERRORS 异常不被熔断捕获，直接透传且不记录失败。"""
    cb = CircuitBreaker("svc", CircuitBreakerConfig(failure_threshold=1))

    def fail():
        raise SystemExit("not recoverable")

    with pytest.raises(SystemExit):
        cb.execute(fail)
    # SystemExit 不在 RECOVERABLE_ERRORS，不记失败、不熔断
    assert cb.state == CircuitState.CLOSED
    assert cb.get_metrics()["failed_calls"] == 0


def test_fallback_sync_timeout(clock, monkeypatch):
    """同步 fallback 超时抛 TimeoutError 且计入 fallback_failure。"""
    import threading
    import time as real_time

    block = threading.Event()

    def slow_fallback():
        block.wait(5.0)  # 阻塞超过 fallback_timeout
        return "late"

    cfg = CircuitBreakerConfig(
        failure_threshold=1, fallback=slow_fallback, fallback_timeout_seconds=0.05
    )
    cb = CircuitBreaker("svc", cfg)
    cb.record_failure()  # OPEN
    with pytest.raises(TimeoutError):
        cb.execute(lambda: 1)
    block.set()  # 释放后台线程
    real_time.sleep(0.01)
    assert cb.get_metrics()["fallback_failure"] == 1


def test_fallback_sync_propagates_exception(clock):
    def bad_fallback():
        raise RuntimeError("fallback broke")

    cfg = CircuitBreakerConfig(failure_threshold=1, fallback=bad_fallback)
    cb = CircuitBreaker("svc", cfg)
    cb.record_failure()  # OPEN
    with pytest.raises(RuntimeError, match="fallback broke"):
        cb.execute(lambda: 1)
    assert cb.get_metrics()["fallback_failure"] == 1


# ========================================================================
# execute_async
# ========================================================================


def test_execute_async_success(clock):
    cb = CircuitBreaker("svc")

    async def coro(x):
        return x + 1

    result = asyncio.run(cb.execute_async(coro, 41))
    assert result == 42
    assert cb.get_metrics()["successful_calls"] == 1


def test_execute_async_failure_propagates(clock):
    cb = CircuitBreaker("svc", CircuitBreakerConfig(failure_threshold=10))

    async def coro():
        raise ValueError("async boom")

    with pytest.raises(ValueError):
        asyncio.run(cb.execute_async(coro))
    assert cb.get_metrics()["failed_calls"] == 1


def test_execute_async_failure_uses_async_fallback(clock):
    async def fb():
        return "async-fb"

    cfg = CircuitBreakerConfig(failure_threshold=10, fallback=fb)
    cb = CircuitBreaker("svc", cfg)

    async def coro():
        raise ValueError("boom")

    result = asyncio.run(cb.execute_async(coro))
    assert result == "async-fb"
    assert cb.get_metrics()["fallback_success"] == 1


def test_execute_async_open_uses_fallback(clock):
    async def fb():
        return "fb"

    cfg = CircuitBreakerConfig(failure_threshold=1, fallback=fb)
    cb = CircuitBreaker("svc", cfg)
    cb.record_failure()  # OPEN

    async def coro():
        return "nope"

    result = asyncio.run(cb.execute_async(coro))
    assert result == "fb"
    assert cb.get_metrics()["rejected_calls"] == 1


def test_execute_async_open_no_fallback_raises(clock):
    cfg = CircuitBreakerConfig(failure_threshold=1)
    cb = CircuitBreaker("svc", cfg)
    cb.record_failure()  # OPEN

    async def coro():
        return 1

    with pytest.raises(CircuitBreakerOpen):
        asyncio.run(cb.execute_async(coro))


def test_execute_async_sync_fallback_value(clock):
    """fallback 返回非协程值（同步 fallback 在 async 上下文中）。"""
    cfg = CircuitBreakerConfig(failure_threshold=1, fallback=lambda: "sync-in-async")
    cb = CircuitBreaker("svc", cfg)
    cb.record_failure()  # OPEN

    async def coro():
        return 1

    result = asyncio.run(cb.execute_async(coro))
    assert result == "sync-in-async"
    assert cb.get_metrics()["fallback_success"] == 1


def test_execute_async_records_slow_call(clock):
    cfg = CircuitBreakerConfig(slow_call_duration_threshold=0.5)
    cb = CircuitBreaker("svc", cfg)

    async def slow():
        clock.advance(1.0)
        return "ok"

    result = asyncio.run(cb.execute_async(slow))
    assert result == "ok"
    assert cb.get_metrics()["slow_calls"] == 1


def test_execute_async_fallback_failure(clock):
    async def bad_fb():
        raise RuntimeError("async fb broke")

    cfg = CircuitBreakerConfig(failure_threshold=1, fallback=bad_fb)
    cb = CircuitBreaker("svc", cfg)
    cb.record_failure()  # OPEN

    async def coro():
        return 1

    with pytest.raises(RuntimeError, match="async fb broke"):
        asyncio.run(cb.execute_async(coro))
    assert cb.get_metrics()["fallback_failure"] == 1


# ========================================================================
# metrics / stats
# ========================================================================


def test_get_metrics_fields(clock):
    cb = CircuitBreaker("svc")
    cb.record_success()
    cb.record_failure()
    m = cb.get_metrics()
    assert m["name"] == "svc"
    assert m["state"] == "closed"
    assert m["total_calls"] == 2
    assert m["successful_calls"] == 1
    assert m["failed_calls"] == 1
    assert "concurrent_executions" in m


def test_get_stats_legacy_fields(clock):
    cb = CircuitBreaker("svc", CircuitBreakerConfig(failure_threshold=5))
    cb.record_failure()
    cb.record_failure()
    s = cb.get_stats()
    assert s["name"] == "svc"
    assert s["state"] == "closed"
    assert s["failure_count"] == 2
    assert "success_count" in s
    assert "half_open_calls" in s
    assert "failure_rate" in s


# ========================================================================
# NeuroCircuitBreakerManager
# ========================================================================


def test_manager_get_breaker_caches(clock):
    mgr = NeuroCircuitBreakerManager()
    b1 = mgr.get_breaker("payment")
    b2 = mgr.get_breaker("payment")
    assert b1 is b2
    # 不同 event_type 不同 breaker
    b3 = mgr.get_breaker("payment", "charge")
    assert b3 is not b1


def test_manager_domain_config_applied(clock):
    mgr = NeuroCircuitBreakerManager()
    payment = mgr.get_breaker("payment")
    # payment 配置 failure_threshold=3
    assert payment._config.failure_threshold == 3
    # 未知领域用 default
    other = mgr.get_breaker("unknown_domain")
    assert other._config.failure_threshold == CircuitBreakerConfig().failure_threshold


def test_manager_check_record(clock):
    mgr = NeuroCircuitBreakerManager()
    assert mgr.check("intent") is True
    mgr.record_success("intent")
    mgr.record_failure("intent")
    stats = mgr.get_all_stats()
    assert "intent" in stats
    assert stats["intent"]["failure_count"] == 1


def test_manager_record_failure_opens_breaker(clock):
    mgr = NeuroCircuitBreakerManager()
    # payment failure_threshold=3
    for _ in range(3):
        mgr.record_failure("payment")
    assert mgr.check("payment") is False  # OPEN -> 拒绝


def test_manager_get_all_metrics(clock):
    mgr = NeuroCircuitBreakerManager()
    mgr.record_success("wechat")
    metrics = mgr.get_all_metrics()
    assert "wechat" in metrics
    assert metrics["wechat"]["successful_calls"] == 1


def test_manager_prometheus_metrics_format(clock):
    mgr = NeuroCircuitBreakerManager()
    mgr.record_success("payment")
    mgr.record_failure("payment")
    text = mgr.get_prometheus_metrics()
    assert "# HELP circuit_breaker_state" in text
    assert "# TYPE circuit_breaker_state gauge" in text
    assert 'circuit_breaker_state{name="payment"} 0' in text  # CLOSED = 0
    assert 'circuit_breaker_total_calls{name="payment"}' in text
    assert text.endswith("\n")


def test_manager_prometheus_open_state_value(clock):
    mgr = NeuroCircuitBreakerManager()
    for _ in range(3):
        mgr.record_failure("payment")  # -> OPEN
    text = mgr.get_prometheus_metrics()
    assert 'circuit_breaker_state{name="payment"} 2' in text  # OPEN = 2


def test_manager_prometheus_empty(clock):
    mgr = NeuroCircuitBreakerManager()
    # 无 breaker 时也输出 HELP/TYPE 头（lines 非空）
    text = mgr.get_prometheus_metrics()
    assert "# HELP circuit_breaker_state" in text


def test_get_circuit_breaker_singleton(monkeypatch):
    monkeypatch.setattr(cb_mod, "_neuro_circuit_manager", None)
    a = get_circuit_breaker()
    b = get_circuit_breaker()
    assert a is b
    assert isinstance(a, NeuroCircuitBreakerManager)
