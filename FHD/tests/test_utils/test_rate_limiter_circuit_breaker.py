"""COVERAGE_RAMP C3.0: 限流器熔断/Redis 后端/fail-closed 路径。

覆盖：
- _InMemoryRateLimiter 窗口滚动 / reset_time
- _CircuitBreaker open → half-open → closed 状态机
- _RedisRateLimiter 不可用 → fail-closed 行为
- get_rate_limiter 单例化 + RateLimitBackendError 抛错
- check_rate_limit 拒绝分支
- reset_circuit_breaker / ensure_rate_limit_backend
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

import app.utils.rate_limiter as rl


@pytest.fixture(autouse=True)
def _reset_singletons():
    rl._rate_limiters.clear()
    rl._circuit_breakers.clear()
    rl._redis_client = None
    rl._redis_init_attempted = False
    yield
    rl._rate_limiters.clear()
    rl._circuit_breakers.clear()
    rl._redis_client = None
    rl._redis_init_attempted = False


# ---------------------------------------------------------------------------
# _InMemoryRateLimiter
# ---------------------------------------------------------------------------


def test_inmemory_limiter_allows_under_max():
    limiter = rl._InMemoryRateLimiter(max_requests=3, window_seconds=60)
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is False


def test_inmemory_limiter_window_expiry(monkeypatch: pytest.MonkeyPatch):
    limiter = rl._InMemoryRateLimiter(max_requests=1, window_seconds=1)
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is False
    # 模拟时间前进到下一个窗口（捕获原始 time.time，避免 lambda 自递归）
    _orig_time = time.time
    monkeypatch.setattr(rl.time, "time", lambda: _orig_time() + 2)
    assert limiter.is_allowed("u1") is True


def test_inmemory_limiter_remaining_and_reset():
    limiter = rl._InMemoryRateLimiter(max_requests=2, window_seconds=60)
    limiter.is_allowed("u1")
    assert limiter.get_remaining("u1") == 1
    assert limiter.get_reset_time("u1") is not None


def test_inmemory_limiter_reset_time_empty_key():
    limiter = rl._InMemoryRateLimiter(max_requests=2, window_seconds=60)
    assert limiter.get_reset_time("never_used") is None
    assert limiter.get_remaining("never_used") == 2


def test_inmemory_limiter_clean_old_deletes_empty():
    limiter = rl._InMemoryRateLimiter(max_requests=1, window_seconds=1)
    limiter.is_allowed("u1")
    # 把全部旧时间戳推过 cutoff
    with patch.object(rl.time, "time", return_value=time.time() + 10):
        assert limiter.is_allowed("u1") is True


# ---------------------------------------------------------------------------
# _CircuitBreaker
# ---------------------------------------------------------------------------


def test_circuit_breaker_initial_state_closed():
    cb = rl._CircuitBreaker(failure_threshold=2, recovery_timeout=60)
    assert cb.state == "closed"


def test_circuit_breaker_opens_after_threshold_failures():
    cb = rl._CircuitBreaker(failure_threshold=2, recovery_timeout=60, expected_exception=ValueError)

    def boom():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        cb.call(boom)
    with pytest.raises(ValueError):
        cb.call(boom)

    assert cb.state == "open"
    with pytest.raises(Exception, match="Circuit breaker is open"):
        cb.call(boom)


def test_circuit_breaker_recovery_open_to_halfopen_to_closed(monkeypatch: pytest.MonkeyPatch):
    # 用可控时钟，避免 recovery_timeout=0 + 真实时钟导致的瞬时 half-open 抖动
    clock = {"t": 1000.0}
    monkeypatch.setattr(rl.time, "time", lambda: clock["t"])
    cb = rl._CircuitBreaker(failure_threshold=1, recovery_timeout=5, expected_exception=ValueError)
    with pytest.raises(ValueError):
        cb.call(lambda: (_ for _ in ()).throw(ValueError("x")))
    # 刚失败、未过 recovery_timeout → open
    assert cb.state == "open"

    # 时间越过 recovery_timeout → half-open
    clock["t"] = 1010.0
    assert cb.state == "half-open"

    def good():
        return "ok"

    # 成功后回到 closed
    assert cb.call(good) == "ok"
    assert cb.state == "closed"


def test_circuit_breaker_reset():
    cb = rl._CircuitBreaker(failure_threshold=1, recovery_timeout=60, expected_exception=ValueError)
    with pytest.raises(ValueError):
        cb.call(lambda: (_ for _ in ()).throw(ValueError("x")))
    assert cb.state == "open"
    cb.reset()
    assert cb.state == "closed"


# ---------------------------------------------------------------------------
# _RedisRateLimiter
# ---------------------------------------------------------------------------


def test_redis_limiter_allow_under_max():
    fake_redis = MagicMock()
    fake_pipe = MagicMock()
    fake_pipe.execute.return_value = [1, True]
    fake_redis.pipeline.return_value = fake_pipe
    with patch.object(rl, "_get_redis_client", return_value=fake_redis):
        limiter = rl._RedisRateLimiter(max_requests=5, window_seconds=60)
    assert limiter.is_allowed("u1") is True


def test_redis_limiter_deny_over_max():
    fake_redis = MagicMock()
    fake_pipe = MagicMock()
    fake_pipe.execute.return_value = [6, True]
    fake_redis.pipeline.return_value = fake_pipe
    with patch.object(rl, "_get_redis_client", return_value=fake_redis):
        limiter = rl._RedisRateLimiter(max_requests=5, window_seconds=60)
    assert limiter.is_allowed("u1") is False


def test_redis_limiter_no_redis_fail_closed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(rl, "_fail_closed_without_redis", lambda: True)
    with patch.object(rl, "_get_redis_client", return_value=None):
        limiter = rl._RedisRateLimiter(max_requests=5, window_seconds=60)
    assert limiter.is_allowed("u1") is False


def test_redis_limiter_no_redis_fail_open(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(rl, "_fail_closed_without_redis", lambda: False)
    with patch.object(rl, "_get_redis_client", return_value=None):
        limiter = rl._RedisRateLimiter(max_requests=5, window_seconds=60)
    assert limiter.is_allowed("u1") is True


def test_redis_limiter_remaining_no_redis_returns_max():
    with patch.object(rl, "_get_redis_client", return_value=None):
        limiter = rl._RedisRateLimiter(max_requests=5, window_seconds=60)
    assert limiter.get_remaining("u1") == 5


def test_redis_limiter_remaining_get_error_returns_zero():
    fake_redis = MagicMock()
    fake_redis.get.side_effect = Exception("boom")
    with patch.object(rl, "_get_redis_client", return_value=fake_redis):
        limiter = rl._RedisRateLimiter(max_requests=5, window_seconds=60)
    assert limiter.get_remaining("u1") == 0


def test_redis_limiter_window_key_uses_bucket():
    with patch.object(rl, "_get_redis_client", return_value=None):
        limiter = rl._RedisRateLimiter(max_requests=5, window_seconds=60)
    bucket = int(time.time()) // 60
    assert limiter._window_key("k") == f"ratelimit:k:{bucket}"


def test_redis_limiter_reset_time_next_bucket():
    with patch.object(rl, "_get_redis_client", return_value=None):
        limiter = rl._RedisRateLimiter(max_requests=5, window_seconds=60)
    bucket = int(time.time()) // 60
    assert limiter.get_reset_time("u1") == (bucket + 1) * 60


# ---------------------------------------------------------------------------
# _get_redis_client
# ---------------------------------------------------------------------------


def test_get_redis_client_no_url():
    with patch.object(rl, "redis_url_from_env", return_value=""):
        rl._redis_client = None
        rl._redis_init_attempted = False
        assert rl._get_redis_client() is None


def test_get_redis_client_ping_failure():
    with patch.object(rl, "redis_url_from_env", return_value="redis://x"):
        with patch.dict("sys.modules", {"redis": MagicMock()}):
            fake_redis_mod = __import__("sys").modules["redis"]
            fake_redis_mod.from_url.return_value.ping.side_effect = Exception("down")
            rl._redis_client = None
            rl._redis_init_attempted = False
            assert rl._get_redis_client() is None


def test_get_redis_client_singleton():
    with patch.object(rl, "redis_url_from_env", return_value="redis://x"):
        fake_redis_mod = MagicMock()
        fake_redis_mod.from_url.return_value.ping.return_value = True
        with patch.dict("sys.modules", {"redis": fake_redis_mod}):
            rl._redis_client = None
            rl._redis_init_attempted = False
            c1 = rl._get_redis_client()
            c2 = rl._get_redis_client()
            assert c1 is c2


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def test_get_rate_limiter_uses_redis(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(rl, "_get_redis_client", lambda: object())
    limiter = rl.get_rate_limiter("ep1", max_requests=10, window_seconds=60)
    assert isinstance(limiter, rl._RedisRateLimiter)


def test_get_rate_limiter_fails_closed_without_redis(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(rl, "_get_redis_client", lambda: None)
    monkeypatch.setattr(rl, "_fail_closed_without_redis", lambda: True)
    with pytest.raises(rl.RateLimitBackendError):
        rl.get_rate_limiter("ep_strict", max_requests=10, window_seconds=60)


def test_get_rate_limiter_uses_in_memory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(rl, "_get_redis_client", lambda: None)
    monkeypatch.setattr(rl, "_fail_closed_without_redis", lambda: False)
    limiter = rl.get_rate_limiter("ep_local", max_requests=10, window_seconds=60)
    assert isinstance(limiter, rl._InMemoryRateLimiter)


def test_get_rate_limiter_singleton(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(rl, "_get_redis_client", lambda: None)
    monkeypatch.setattr(rl, "_fail_closed_without_redis", lambda: False)
    a = rl.get_rate_limiter("ep_same", max_requests=10, window_seconds=60)
    b = rl.get_rate_limiter("ep_same", max_requests=99, window_seconds=99)
    assert a is b


def test_ensure_rate_limit_backend_skips_when_not_required(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(rl, "distributed_rate_limit_required", lambda: False)
    # 不抛错即通过
    rl.ensure_rate_limit_backend()


def test_ensure_rate_limit_backend_raises_when_no_redis(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(rl, "distributed_rate_limit_required", lambda: True)
    monkeypatch.setattr(rl, "_get_redis_client", lambda: None)
    with pytest.raises(rl.RateLimitBackendError):
        rl.ensure_rate_limit_backend()


def test_check_rate_limit_allow(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(rl, "_get_redis_client", lambda: None)
    monkeypatch.setattr(rl, "_fail_closed_without_redis", lambda: False)
    res = rl.check_rate_limit("u", "ep", max_requests=10, window_seconds=60)
    assert res["allowed"] is True
    assert res["remaining"] == 9
    assert res["reset_time"] is not None
    assert res["retry_after"] is None


def test_check_rate_limit_deny(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(rl, "_get_redis_client", lambda: None)
    monkeypatch.setattr(rl, "_fail_closed_without_redis", lambda: False)
    monkeypatch.setattr(rl.time, "time", lambda: 1000.0)
    res = rl.check_rate_limit("u", "ep", max_requests=1, window_seconds=60)
    assert res["allowed"] is True  # 第一次
    res2 = rl.check_rate_limit("u", "ep", max_requests=1, window_seconds=60)
    assert res2["allowed"] is False
    assert res2["remaining"] == 0
    assert res2["reset_time"] is not None
    assert res2["retry_after"] is not None


def test_get_circuit_breaker_singleton():
    a = rl.get_circuit_breaker("x", failure_threshold=3, recovery_timeout=10)
    b = rl.get_circuit_breaker("x", failure_threshold=99, recovery_timeout=99)
    assert a is b


def test_reset_circuit_breaker(monkeypatch: pytest.MonkeyPatch):
    cb = rl.get_circuit_breaker("y", failure_threshold=1, recovery_timeout=60)
    with pytest.raises(ValueError):
        cb.call(lambda: (_ for _ in ()).throw(ValueError("x")))
    assert cb.state == "open"
    rl.reset_circuit_breaker("y")
    assert cb.state == "closed"


def test_reset_circuit_breaker_missing_name():
    rl.reset_circuit_breaker("nope")  # 不存在也不抛错
