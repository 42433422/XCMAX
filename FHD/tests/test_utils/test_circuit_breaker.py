"""app/utils/circuit_breaker 单测：熔断器状态机。"""

from __future__ import annotations

import time

import importlib

import pytest

from app.errors import DatabaseLockError
from app.utils.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpen,
    CircuitState,
    circuit_breaker,
    get_all_circuit_breakers,
    get_circuit_breaker,
)


@pytest.fixture(autouse=True)
def _reset_breakers():
    cb_mod = importlib.import_module("app.utils.circuit_breaker")
    cb_mod._circuit_breakers.clear()
    yield
    cb_mod._circuit_breakers.clear()


class TestCircuitBreaker:
    def test_closed_success_resets_failures(self):
        cb = CircuitBreaker("t1", failure_threshold=2)
        assert cb.call(lambda: 1) == 1
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_threshold(self):
        cb = CircuitBreaker("t2", failure_threshold=2, recovery_timeout=60)

        def fail():
            raise ValueError("x")

        with pytest.raises(ValueError):
            cb.call(fail)
        with pytest.raises(ValueError):
            cb.call(fail)
        assert cb.state == CircuitState.OPEN

    def test_open_rejects_calls(self):
        cb = CircuitBreaker("t3", failure_threshold=1, recovery_timeout=60)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("x")))
        with pytest.raises(CircuitBreakerOpen):
            cb.call(lambda: 1)

    def test_half_open_recovery(self, monkeypatch):
        clock = [1000.0]
        monkeypatch.setattr(time, "time", lambda: clock[0])
        cb = CircuitBreaker("t4", failure_threshold=1, recovery_timeout=0.01, half_open_max_calls=1)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("x")))
        assert cb.state == CircuitState.OPEN
        clock[0] += 1
        assert cb.call(lambda: "ok") == "ok"
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens(self, monkeypatch):
        clock = [1000.0]
        monkeypatch.setattr(time, "time", lambda: clock[0])
        cb = CircuitBreaker("t5", failure_threshold=1, recovery_timeout=0.01)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("x")))
        clock[0] += 1
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("x")))
        assert cb.state == CircuitState.OPEN

    def test_decorator_and_singleton(self):
        @circuit_breaker("shared", failure_threshold=5)
        def fn():
            return 9

        assert fn() == 9
        assert get_circuit_breaker("shared") is get_circuit_breaker("shared")

    def test_get_stats(self):
        cb = CircuitBreaker("stats", failure_threshold=3)
        cb.call(lambda: 1)
        s = cb.get_stats()
        assert s["name"] == "stats"
        assert s["call_count"] == 1
        assert s["success_count"] == 1

    def test_expected_exceptions_only(self):
        cb = CircuitBreaker("exp", failure_threshold=1, expected_exceptions=(DatabaseLockError,))
        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        assert cb.state == CircuitState.CLOSED
