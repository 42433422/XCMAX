"""app/utils/decorators 单测：无优化组件时的直通路径 + retry/circuit_breaker。"""

from __future__ import annotations

import pytest

from app.utils.decorators import (
    OptimizedServiceMixin,
    cached,
    circuit_breaker,
    combined_optimization,
    get_optimizer_components,
    rate_limited,
    retry,
)


class TestOptimizerComponents:
    def test_get_optimizer_components_keys(self):
        c = get_optimizer_components()
        assert set(c.keys()) == {"cache", "monitor", "deduplicator", "async_manager"}


class TestPassthroughDecorators:
    def test_cached_without_backend(self):
        @cached(ttl=60, key_prefix="p:")
        def add(a, b):
            return a + b

        assert add(1, 2) == 3

    def test_rate_limited_without_backend(self):
        @rate_limited(max_requests=1)
        def echo(x):
            return x

        assert echo("hi") == "hi"


class TestRetryDecorator:
    def test_succeeds_after_retry(self, monkeypatch):
        calls = {"n": 0}
        monkeypatch.setattr("app.utils.decorators.time.sleep", lambda _s: None)

        @retry(max_retries=2, delay=0.01, exceptions=(ValueError,))
        def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise ValueError("retry me")
            return "ok"

        assert flaky() == "ok"
        assert calls["n"] == 2

    def test_exhausted_raises(self, monkeypatch):
        monkeypatch.setattr("app.utils.decorators.time.sleep", lambda _s: None)

        @retry(max_retries=1, delay=0.01, exceptions=(ValueError,))
        def always():
            raise ValueError("nope")

        with pytest.raises(ValueError):
            always()


class TestCircuitBreakerDecorator:
    def test_fallback_when_open(self, monkeypatch):
        monkeypatch.setattr("app.utils.decorators.time.time", lambda: 1000.0)

        @circuit_breaker(failure_threshold=1, recovery_timeout=9999, fallback_func=lambda: {"down": True})
        def fail():
            raise OSError("net")

        with pytest.raises(OSError):
            fail()
        out = fail()
        assert out == {"down": True}


class TestCombinedOptimization:
    def test_zero_config_is_identity(self):
        @combined_optimization()
        def identity(x):
            return x * 2

        assert identity(3) == 6


class TestOptimizedServiceMixin:
    def test_init_optimizers(self):
        class Svc(OptimizedServiceMixin):
            def __init__(self):
                self._init_optimizers()

        s = Svc()
        assert hasattr(s, "_cache")
