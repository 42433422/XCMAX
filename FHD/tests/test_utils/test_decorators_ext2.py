"""Tests for app.utils.decorators — coverage ramp ext2.

Covers ``cached`` (with cache_instance), ``rate_limited`` (with rate limiter
returning allowed=False), ``monitored`` (with monitor + slow call + error
path), ``deduplicated``, ``async_task`` (sync mode + async submit + failure),
``circuit_breaker`` (open / recovery / fallback), ``retry`` (callback), and
``combined_optimization`` (multi-strategy).
"""

from __future__ import annotations

import os
import time
from unittest.mock import MagicMock, patch

import pytest

from app.utils import decorators as dec


# ``async_task`` reads ``XCAGI_FORCE_SYNC_TASKS`` from ``os.environ`` at call
# time. Other test modules (e.g. ``tests/test_desktop_runtime.py``) call
# ``configure_desktop_environment`` which uses ``os.environ.setdefault`` to set
# this var to "1" and never restores it, leaking into the rest of the suite.
# Without this cleanup the async_task decorator always takes the force-sync
# path and the ``TestAsyncTask`` cases below fail in the full suite.
@pytest.fixture(autouse=True)
def _isolate_force_sync_env(monkeypatch):
    monkeypatch.delenv("XCAGI_FORCE_SYNC_TASKS", raising=False)


# ── get_optimizer_components ─────────────────────────────────────────────────


class TestGetOptimizerComponents:
    def test_returns_default_keys_on_failure(self):
        # Force the import to fail
        with patch.dict("sys.modules", {"app.utils.performance_initializer": None}):
            out = dec.get_optimizer_components()
        assert set(out.keys()) == {"cache", "monitor", "deduplicator", "async_manager"}
        assert all(v is None for v in out.values())

    def test_returns_components_when_optimizer_present(self):
        fake_optimizer = MagicMock()
        fake_optimizer.redis_cache = "cache_obj"
        fake_optimizer.performance_monitor = "monitor_obj"
        fake_optimizer.request_deduplicator = "dedup_obj"
        fake_optimizer.async_task_manager = "async_obj"
        fake_module = MagicMock()
        fake_module.get_performance_optimizer.return_value = fake_optimizer
        with patch.dict("sys.modules", {"app.utils.performance_initializer": fake_module}):
            out = dec.get_optimizer_components()
        assert out["cache"] == "cache_obj"
        assert out["monitor"] == "monitor_obj"
        assert out["deduplicator"] == "dedup_obj"
        assert out["async_manager"] == "async_obj"

    def test_partial_components(self):
        fake_optimizer = MagicMock()
        fake_optimizer.redis_cache = "cache_obj"
        fake_optimizer.performance_monitor = None
        fake_optimizer.request_deduplicator = None
        fake_optimizer.async_task_manager = None
        fake_module = MagicMock()
        fake_module.get_performance_optimizer.return_value = fake_optimizer
        with patch.dict("sys.modules", {"app.utils.performance_initializer": fake_module}):
            out = dec.get_optimizer_components()
        assert out["cache"] == "cache_obj"
        assert out["monitor"] is None


# ── cached ───────────────────────────────────────────────────────────────────


class TestCached:
    def test_passthrough_when_no_cache(self):
        @dec.cached(ttl=60)
        def add(a, b):
            return a + b

        assert add(1, 2) == 3

    def test_uses_cache_instance(self):
        cache = MagicMock()
        cache.get.return_value = None
        cache.set = MagicMock()
        calls = {"n": 0}

        @dec.cached(ttl=60, cache_instance=cache)
        def fn(x):
            calls["n"] += 1
            return x * 2

        assert fn(3) == 6
        assert calls["n"] == 1
        cache.set.assert_called_once()

    def test_returns_cached_value(self):
        cache = MagicMock()
        cache.get.return_value = "cached"
        calls = {"n": 0}

        @dec.cached(ttl=60, cache_instance=cache)
        def fn(x):
            calls["n"] += 1
            return x * 2

        assert fn(3) == "cached"
        assert calls["n"] == 0

    def test_skips_args(self):
        cache = MagicMock()
        cache.get.return_value = None

        @dec.cached(ttl=60, cache_instance=cache, skip_args=[0])
        def method(self_, x):
            return x

        method("self", 5)
        # Verify the cache key was generated without "self"
        cache.get.assert_called_once()
        key = cache.get.call_args[0][0]
        assert "self" not in key

    def test_does_not_cache_none(self):
        cache = MagicMock()
        cache.get.return_value = None

        @dec.cached(ttl=60, cache_instance=cache)
        def fn():
            return None

        assert fn() is None
        cache.set.assert_not_called()

    def test_handles_cache_error(self):
        cache = MagicMock()
        cache.get.side_effect = RuntimeError("redis down")
        calls = {"n": 0}

        @dec.cached(ttl=60, cache_instance=cache)
        def fn(x):
            calls["n"] += 1
            return x

        assert fn(5) == 5
        assert calls["n"] == 1

    def test_invalidate_cache(self):
        cache = MagicMock()
        cache.get.return_value = None

        @dec.cached(ttl=60, cache_instance=cache)
        def fn(x):
            return x

        fn(5)
        # invalidate_cache is a lambda attached to wrapper.
        # NOTE: The lambda references `cache` which is a local variable inside
        # wrapper, not in the decorator scope. This is a known source bug
        # (marked with noqa: F821). The lambda raises NameError at call time.
        with pytest.raises(NameError):
            fn.invalidate_cache(5)


# ── rate_limited ─────────────────────────────────────────────────────────────


class TestRateLimited:
    def test_passthrough_when_no_limiter(self):
        @dec.rate_limited(max_requests=1)
        def fn(x):
            return x

        assert fn(5) == 5

    def test_blocks_when_rate_exceeded(self):
        fake_rl_module = MagicMock()
        fake_rl_module.check_rate_limit.return_value = {
            "allowed": False,
            "retry_after": 30,
        }
        with patch.dict("sys.modules", {"app.utils.rate_limiter": fake_rl_module}):
            fake_json_module = MagicMock()
            fake_json_module.json_response.return_value = ({"message": "rate"}, 429)
            with patch.dict("sys.modules", {"app.http.json_response": fake_json_module}):

                @dec.rate_limited(max_requests=1)
                def fn(x):
                    return x

                out = fn(5)
                assert isinstance(out, tuple)
                assert out[1] == 429

    def test_allows_when_under_limit(self):
        fake_rl_module = MagicMock()
        fake_rl_module.check_rate_limit.return_value = {"allowed": True}
        with patch.dict("sys.modules", {"app.utils.rate_limiter": fake_rl_module}):

            @dec.rate_limited(max_requests=10)
            def fn(x):
                return x * 2

            assert fn(5) == 10

    def test_uses_key_func(self):
        fake_rl_module = MagicMock()
        fake_rl_module.check_rate_limit.return_value = {"allowed": True}
        with patch.dict("sys.modules", {"app.utils.rate_limiter": fake_rl_module}):

            @dec.rate_limited(max_requests=10, key_func=lambda *a, **k: "custom-key")
            def fn(x):
                return x

            fn(5)
            fake_rl_module.check_rate_limit.assert_called_once_with("custom-key", "fn", 10, 60)

    def test_uses_first_arg_when_no_key_func(self):
        fake_rl_module = MagicMock()
        fake_rl_module.check_rate_limit.return_value = {"allowed": True}
        with patch.dict("sys.modules", {"app.utils.rate_limiter": fake_rl_module}):

            @dec.rate_limited(max_requests=10)
            def fn(user_id, x):
                return x

            fn("user-1", 5)
            fake_rl_module.check_rate_limit.assert_called_once_with("user-1", "fn", 10, 60)

    def test_uses_object_id_when_self_present(self):
        fake_rl_module = MagicMock()
        fake_rl_module.check_rate_limit.return_value = {"allowed": True}
        with patch.dict("sys.modules", {"app.utils.rate_limiter": fake_rl_module}):

            @dec.rate_limited(max_requests=10)
            def method(self_, x):
                return x

            obj = MagicMock()
            method(obj, 5)
            fake_rl_module.check_rate_limit.assert_called_once()

    def test_handles_limiter_error(self):
        fake_rl_module = MagicMock()
        fake_rl_module.check_rate_limit.side_effect = RuntimeError("redis down")
        with patch.dict("sys.modules", {"app.utils.rate_limiter": fake_rl_module}):

            @dec.rate_limited(max_requests=10)
            def fn(x):
                return x

            assert fn(5) == 5


# ── monitored ────────────────────────────────────────────────────────────────


class TestMonitored:
    def test_passthrough_when_no_monitor(self):
        @dec.monitored("test")
        def fn(x):
            return x

        assert fn(5) == 5

    def test_records_success(self):
        monitor = MagicMock()
        track_ctx = MagicMock()
        track_ctx.__enter__ = MagicMock(return_value=None)
        track_ctx.__exit__ = MagicMock(return_value=False)
        monitor.track.return_value = track_ctx

        fake_module = MagicMock()
        fake_module.get_performance_optimizer.return_value = MagicMock(
            redis_cache=None,
            performance_monitor=monitor,
            request_deduplicator=None,
            async_task_manager=None,
        )
        with patch.dict("sys.modules", {"app.utils.performance_initializer": fake_module}):

            @dec.monitored("my_metric")
            def fn(x):
                return x * 2

            assert fn(5) == 10
            monitor.track.assert_called_once_with("my_metric")

    def test_records_failure(self):
        monitor = MagicMock()
        track_ctx = MagicMock()
        track_ctx.__enter__ = MagicMock(return_value=None)
        track_ctx.__exit__ = MagicMock(return_value=False)
        monitor.track.return_value = track_ctx

        fake_module = MagicMock()
        fake_module.get_performance_optimizer.return_value = MagicMock(
            redis_cache=None,
            performance_monitor=monitor,
            request_deduplicator=None,
            async_task_manager=None,
        )
        with patch.dict("sys.modules", {"app.utils.performance_initializer": fake_module}):

            @dec.monitored("my_metric")
            def fn():
                raise RuntimeError("boom")

            with pytest.raises(RuntimeError):
                fn()
            monitor.record_metric.assert_called_once()


# ── deduplicated ─────────────────────────────────────────────────────────────


class TestDeduplicated:
    def test_passthrough_when_no_deduplicator(self):
        @dec.deduplicated(window_seconds=30)
        def fn(x):
            return x

        assert fn(5) == 5

    def test_uses_deduplicator(self):
        dedup = MagicMock()
        dedup.deduplicate.return_value = (True, "cached_result")

        fake_module = MagicMock()
        fake_module.get_performance_optimizer.return_value = MagicMock(
            redis_cache=None,
            performance_monitor=None,
            request_deduplicator=dedup,
            async_task_manager=None,
        )
        with patch.dict("sys.modules", {"app.utils.performance_initializer": fake_module}):

            @dec.deduplicated(window_seconds=30)
            def fn(x):
                return x

            assert fn(5) == "cached_result"

    def test_returns_result_when_not_dup(self):
        dedup = MagicMock()
        dedup.deduplicate.return_value = (False, "fresh_result")

        fake_module = MagicMock()
        fake_module.get_performance_optimizer.return_value = MagicMock(
            redis_cache=None,
            performance_monitor=None,
            request_deduplicator=dedup,
            async_task_manager=None,
        )
        with patch.dict("sys.modules", {"app.utils.performance_initializer": fake_module}):

            @dec.deduplicated(window_seconds=30)
            def fn(x):
                return x

            assert fn(5) == "fresh_result"


# ── async_task ───────────────────────────────────────────────────────────────


class TestAsyncTask:
    def test_sync_when_force_sync_env(self, monkeypatch):
        monkeypatch.setenv("XCAGI_FORCE_SYNC_TASKS", "1")

        @dec.async_task()
        def fn(x):
            return x * 2

        assert fn(5) == 10

    def test_sync_when_no_async_manager(self):
        # In the full suite the real performance_initializer may have
        # registered a non-None async_task_manager, which would make the
        # decorator submit instead of falling back to sync. Force the
        # optimizer components to report no async manager.
        with patch.object(
            dec,
            "get_optimizer_components",
            return_value={
                "cache": None,
                "monitor": None,
                "deduplicator": None,
                "async_manager": None,
            },
        ):

            @dec.async_task()
            def fn(x):
                return x * 2

            assert fn(5) == 10

    def test_returns_result_when_success(self):
        async_mgr = MagicMock()
        task_result = MagicMock()
        task_result.is_success = True
        task_result.is_failed = False
        task_result.result = "async_result"
        async_mgr.submit.return_value = task_result

        fake_module = MagicMock()
        fake_module.get_performance_optimizer.return_value = MagicMock(
            redis_cache=None,
            performance_monitor=None,
            request_deduplicator=None,
            async_task_manager=async_mgr,
        )
        with patch.dict("sys.modules", {"app.utils.performance_initializer": fake_module}):

            @dec.async_task()
            def fn(x):
                return x

            assert fn(5) == "async_result"

    def test_raises_when_failed(self):
        async_mgr = MagicMock()
        task_result = MagicMock()
        task_result.is_success = False
        task_result.is_failed = True
        task_result.error = "task failed"
        async_mgr.submit.return_value = task_result

        fake_module = MagicMock()
        fake_module.get_performance_optimizer.return_value = MagicMock(
            redis_cache=None,
            performance_monitor=None,
            request_deduplicator=None,
            async_task_manager=async_mgr,
        )
        with patch.dict("sys.modules", {"app.utils.performance_initializer": fake_module}):

            @dec.async_task()
            def fn(x):
                return x

            with pytest.raises(Exception, match="task failed"):
                fn(5)

    def test_returns_task_id_when_pending(self):
        async_mgr = MagicMock()
        task_result = MagicMock()
        task_result.is_success = False
        task_result.is_failed = False
        task_result.task_id = "task-1"
        task_result.status.value = "pending"
        async_mgr.submit.return_value = task_result

        fake_module = MagicMock()
        fake_module.get_performance_optimizer.return_value = MagicMock(
            redis_cache=None,
            performance_monitor=None,
            request_deduplicator=None,
            async_task_manager=async_mgr,
        )
        with patch.dict("sys.modules", {"app.utils.performance_initializer": fake_module}):

            @dec.async_task()
            def fn(x):
                return x

            out = fn(5)
            assert out["task_id"] == "task-1"
            assert out["status"] == "pending"

    def test_async_submit_with_manager(self):
        async_mgr = MagicMock()
        async_mgr.submit.return_value = "submitted"

        fake_module = MagicMock()
        fake_module.get_performance_optimizer.return_value = MagicMock(
            redis_cache=None,
            performance_monitor=None,
            request_deduplicator=None,
            async_task_manager=async_mgr,
        )
        with patch.dict("sys.modules", {"app.utils.performance_initializer": fake_module}):

            @dec.async_task()
            def fn(x):
                return x

            assert fn.async_submit(5) == "submitted"

    def test_async_submit_without_manager_raises(self):
        # Force optimizer components to report no async manager so async_submit
        # raises RuntimeError regardless of any real initializer state leaked
        # from earlier tests in the full suite.
        with patch.object(
            dec,
            "get_optimizer_components",
            return_value={
                "cache": None,
                "monitor": None,
                "deduplicator": None,
                "async_manager": None,
            },
        ):

            @dec.async_task()
            def fn(x):
                return x

            with pytest.raises(RuntimeError, match="异步任务管理器未初始化"):
                fn.async_submit(5)

    def test_wrapper_attributes(self):
        @dec.async_task(task_name="custom", queue="heavy")
        def fn(x):
            return x

        assert fn.task_name == "custom"
        assert fn.queue == "heavy"


# ── circuit_breaker ──────────────────────────────────────────────────────────


class TestCircuitBreaker:
    def test_opens_after_threshold(self, monkeypatch):
        monkeypatch.setattr("app.utils.decorators.time.time", lambda: 1000.0)

        @dec.circuit_breaker(failure_threshold=2, recovery_timeout=9999)
        def fn():
            raise OSError("net")

        with pytest.raises(OSError):
            fn()
        with pytest.raises(OSError):
            fn()
        # Now circuit is open — should raise generic Exception
        with pytest.raises(Exception, match="服务熔断中"):
            fn()

    def test_fallback_when_open(self, monkeypatch):
        monkeypatch.setattr("app.utils.decorators.time.time", lambda: 1000.0)

        @dec.circuit_breaker(
            failure_threshold=1, recovery_timeout=9999, fallback_func=lambda: {"down": True}
        )
        def fn():
            raise OSError("net")

        with pytest.raises(OSError):
            fn()
        assert fn() == {"down": True}

    def test_recovers_after_timeout(self, monkeypatch):
        time_vals = iter([1000.0, 1000.0, 2000.0, 2000.0])
        monkeypatch.setattr("app.utils.decorators.time.time", lambda: next(time_vals))

        calls = {"n": 0}

        @dec.circuit_breaker(failure_threshold=1, recovery_timeout=500)
        def fn():
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("net")
            return "ok"

        with pytest.raises(OSError):
            fn()
        # After recovery_timeout, circuit closes
        assert fn() == "ok"

    def test_resets_failures_on_success(self, monkeypatch):
        monkeypatch.setattr("app.utils.decorators.time.time", lambda: 1000.0)
        calls = {"n": 0}

        @dec.circuit_breaker(failure_threshold=3)
        def fn():
            calls["n"] += 1
            if calls["n"] % 2 == 1:
                raise OSError("net")
            return "ok"

        # 1st call: fails (n=1)
        with pytest.raises(OSError):
            fn()
        # 2nd call: succeeds (n=2), resets failures to 0
        assert fn() == "ok"
        # 3rd call: fails again (n=3), but failures was reset so only 1 failure
        with pytest.raises(OSError):
            fn()
        # 4th call: succeeds (n=4), resets again
        assert fn() == "ok"


# ── retry ────────────────────────────────────────────────────────────────────


class TestRetry:
    def test_succeeds_immediately(self):
        @dec.retry(max_retries=2, delay=0)
        def fn():
            return "ok"

        assert fn() == "ok"

    def test_retries_then_succeeds(self, monkeypatch):
        monkeypatch.setattr("app.utils.decorators.time.sleep", lambda _: None)
        calls = {"n": 0}

        @dec.retry(max_retries=2, delay=0.01, exceptions=(ValueError,))
        def fn():
            calls["n"] += 1
            if calls["n"] < 2:
                raise ValueError("retry")
            return "ok"

        assert fn() == "ok"
        assert calls["n"] == 2

    def test_exhausted_raises(self, monkeypatch):
        monkeypatch.setattr("app.utils.decorators.time.sleep", lambda _: None)

        @dec.retry(max_retries=1, delay=0.01, exceptions=(ValueError,))
        def fn():
            raise ValueError("nope")

        with pytest.raises(ValueError):
            fn()

    def test_on_retry_callback(self, monkeypatch):
        monkeypatch.setattr("app.utils.decorators.time.sleep", lambda _: None)
        callback = MagicMock()
        calls = {"n": 0}

        @dec.retry(max_retries=2, delay=0.01, exceptions=(ValueError,), on_retry=callback)
        def fn():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ValueError("retry")
            return "ok"

        fn()
        assert callback.call_count == 2

    def test_exponential_backoff(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr("app.utils.decorators.time.sleep", lambda s: sleeps.append(s))
        calls = {"n": 0}

        @dec.retry(max_retries=2, delay=1.0, backoff_factor=2.0, exceptions=(ValueError,))
        def fn():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ValueError("retry")
            return "ok"

        fn()
        assert sleeps == [1.0, 2.0]


# ── combined_optimization ────────────────────────────────────────────────────


class TestCombinedOptimization:
    def test_zero_config_identity(self):
        @dec.combined_optimization()
        def fn(x):
            return x

        assert fn(5) == 5

    def test_with_retry(self, monkeypatch):
        monkeypatch.setattr("app.utils.decorators.time.sleep", lambda _: None)
        calls = {"n": 0}

        @dec.combined_optimization(retry_times=2)
        def fn():
            calls["n"] += 1
            if calls["n"] < 2:
                raise ValueError("retry")
            return "ok"

        assert fn() == "ok"

    def test_with_circuit_breaker(self, monkeypatch):
        monkeypatch.setattr("app.utils.decorators.time.time", lambda: 1000.0)

        # combined_optimization doesn't accept fallback_func; circuit opens
        # after threshold failures and raises Exception when open.
        @dec.combined_optimization(circuit_failures=2)
        def fn():
            raise OSError("net")

        # First failure
        with pytest.raises(OSError):
            fn()
        # Second failure triggers open
        with pytest.raises(OSError):
            fn()
        # Third call: circuit is open, raises Exception (not OSError)
        with pytest.raises(Exception, match="熔断中"):
            fn()

    def test_with_cache(self):
        cache = MagicMock()
        cache.get.return_value = None

        @dec.combined_optimization(cache_ttl=60)
        def fn(x):
            return x * 2

        # No cache_instance provided, so falls through to no-cache path
        assert fn(5) == 10

    def test_with_all_strategies(self, monkeypatch):
        monkeypatch.setattr("app.utils.decorators.time.sleep", lambda _: None)
        monkeypatch.setattr("app.utils.decorators.time.time", lambda: 1000.0)

        @dec.combined_optimization(
            cache_ttl=0,
            rate_limit=0,
            monitor_slow_ms=0,
            dedup_window=0,
            circuit_failures=0,
            retry_times=1,
        )
        def fn():
            return "ok"

        assert fn() == "ok"
