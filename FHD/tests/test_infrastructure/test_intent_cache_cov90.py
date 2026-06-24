"""Behavioral tests for app.infrastructure.cache.intent_cache — coverage ramp cov90.

Targets the previously-uncovered units:
* ``IntentCache._resolve_backend`` — lazy build via ``_build_redis_client`` (None / object / raises).
* ``IntentCache.get`` — disabled, empty text, backend None, success, recoverable error.
* ``IntentCache.set`` — disabled, empty text, None value, backend None, success, recoverable error.
* ``IntentCache.get_or_compute`` — backfill failure swallowed.
* ``IntentCache.invalidate`` — backend None, empty text, success, recoverable error.
* ``_default_should_cache_intent`` — None result branch.
* ``_build_redis_client`` — import absent, url resolution, ping success, connect failure.
* ``_observe_hit`` / ``_observe_miss`` / ``_observe_error`` — metric increments + swallow.

All external deps (redis, redis_cache, metrics) are mocked; tests are offline & deterministic.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.cache.intent_cache import (
    IntentCache,
    _build_redis_client,
    _default_should_cache_intent,
    _observe_error,
    _observe_hit,
    _observe_miss,
)

MODPATH = "app.infrastructure.cache.intent_cache"


# ---------------------------------------------------------------------------
# _resolve_backend (lines 96-107)
# ---------------------------------------------------------------------------
class TestResolveBackend:
    def test_returns_injected_backend_without_building(self) -> None:
        injected = MagicMock(name="injected_backend")
        cache = IntentCache(backend=injected)
        with patch(f"{MODPATH}._build_redis_client") as build:
            assert cache._resolve_backend() is injected
            build.assert_not_called()

    def test_build_returns_none_client_yields_none(self) -> None:
        cache = IntentCache(backend=None)
        with patch(f"{MODPATH}._build_redis_client", return_value=None) as build:
            assert cache._resolve_backend() is None
            build.assert_called_once()
        # backend stays None so a second call retries the build.
        assert cache._backend is None

    def test_build_client_wraps_into_redis_cache_and_caches(self) -> None:
        cache = IntentCache(backend=None)
        fake_client = object()
        fake_wrapped = MagicMock(name="wrapped")
        with (
            patch(f"{MODPATH}._build_redis_client", return_value=fake_client),
            patch(f"{MODPATH}.get_redis_cache", return_value=fake_wrapped) as grc,
        ):
            out = cache._resolve_backend()
        assert out is fake_wrapped
        grc.assert_called_once_with(fake_client)
        # second resolve hits the cached backend, no rebuild.
        with patch(f"{MODPATH}._build_redis_client") as build2:
            assert cache._resolve_backend() is fake_wrapped
            build2.assert_not_called()

    def test_recoverable_error_during_build_returns_none(self) -> None:
        cache = IntentCache(backend=None)
        with patch(f"{MODPATH}._build_redis_client", side_effect=ConnectionError("boom")):
            assert cache._resolve_backend() is None


# ---------------------------------------------------------------------------
# get (lines 114-125)
# ---------------------------------------------------------------------------
class TestGet:
    def test_disabled_returns_none(self) -> None:
        cache = IntentCache(backend=MagicMock(), enabled=False)
        assert cache.get("hello", "m1") is None

    def test_empty_text_returns_none(self) -> None:
        backend = MagicMock()
        cache = IntentCache(backend=backend, enabled=True)
        assert cache.get("", "m1") is None
        backend.get.assert_not_called()

    def test_backend_none_returns_none(self) -> None:
        cache = IntentCache(backend=None, enabled=True)
        with patch.object(cache, "_resolve_backend", return_value=None):
            assert cache.get("hello", "m1") is None

    def test_success_returns_backend_value(self) -> None:
        backend = MagicMock()
        backend.get.return_value = {"intent": "x"}
        cache = IntentCache(backend=backend, enabled=True)
        assert cache.get("hello", "m1") == {"intent": "x"}
        backend.get.assert_called_once()

    def test_recoverable_error_returns_none_and_observes(self) -> None:
        backend = MagicMock()
        backend.get.side_effect = ValueError("bad payload")
        cache = IntentCache(backend=backend, enabled=True, scope="intent")
        with patch(f"{MODPATH}._observe_error") as obs:
            assert cache.get("hello", "m1") is None
            obs.assert_called_once_with("intent", "get")


# ---------------------------------------------------------------------------
# set (lines 134-146)
# ---------------------------------------------------------------------------
class TestSet:
    def test_disabled_returns_false(self) -> None:
        cache = IntentCache(backend=MagicMock(), enabled=False)
        assert cache.set("hi", {"intent": "a"}) is False

    def test_empty_text_returns_false(self) -> None:
        backend = MagicMock()
        cache = IntentCache(backend=backend, enabled=True)
        assert cache.set("", {"intent": "a"}) is False
        backend.set.assert_not_called()

    def test_none_value_returns_false(self) -> None:
        backend = MagicMock()
        cache = IntentCache(backend=backend, enabled=True)
        assert cache.set("hi", None) is False
        backend.set.assert_not_called()

    def test_backend_none_returns_false(self) -> None:
        cache = IntentCache(backend=None, enabled=True)
        with patch.object(cache, "_resolve_backend", return_value=None):
            assert cache.set("hi", {"intent": "a"}) is False

    def test_success_uses_default_ttl_and_returns_bool(self) -> None:
        backend = MagicMock()
        backend.set.return_value = 1  # truthy non-bool -> coerced to True
        cache = IntentCache(backend=backend, enabled=True, default_ttl=42)
        result = cache.set("hi", {"intent": "a"}, mod_id="m1")
        assert result is True
        _, kwargs = backend.set.call_args
        assert kwargs["ttl"] == 42

    def test_explicit_ttl_overrides_default(self) -> None:
        backend = MagicMock()
        backend.set.return_value = True
        cache = IntentCache(backend=backend, enabled=True, default_ttl=42)
        cache.set("hi", {"intent": "a"}, ttl=7)
        _, kwargs = backend.set.call_args
        assert kwargs["ttl"] == 7

    def test_recoverable_error_returns_false_and_observes(self) -> None:
        backend = MagicMock()
        backend.set.side_effect = OSError("disk")
        cache = IntentCache(backend=backend, enabled=True, scope="intent")
        with patch(f"{MODPATH}._observe_error") as obs:
            assert cache.set("hi", {"intent": "a"}) is False
            obs.assert_called_once_with("intent", "set")


# ---------------------------------------------------------------------------
# get_or_compute — set backfill failure (lines 196-198)
# ---------------------------------------------------------------------------
class TestGetOrComputeBackfillError:
    def test_backfill_set_error_is_swallowed_and_result_returned(self) -> None:
        backend = MagicMock()
        backend.get.return_value = None  # miss
        backend.set.side_effect = RuntimeError("redis write failed")
        cache = IntentCache(backend=backend, enabled=True, scope="intent")
        compute = MagicMock(return_value={"intent": "create", "confidence": 0.8})
        with patch(f"{MODPATH}._observe_error") as obs:
            out = cache.get_or_compute(text="hi", mod_id="m1", compute_fn=compute)
        assert out == {"intent": "create", "confidence": 0.8}
        compute.assert_called_once()
        obs.assert_called_once_with("intent", "set")

    def test_lookup_error_then_recompute_and_backfill(self) -> None:
        # exercises the lookup except branch (lines 181-183). NOTE: ``key`` is
        # assigned *before* backend.get inside the try, so a get failure still
        # leaves a valid key and the backfill set proceeds afterward.
        backend = MagicMock()
        backend.get.side_effect = ConnectionError("redis down on get")
        cache = IntentCache(backend=backend, enabled=True, scope="intent")
        compute = MagicMock(return_value={"intent": "x", "confidence": 0.5})
        with patch(f"{MODPATH}._observe_error") as obs:
            out = cache.get_or_compute(text="hi", compute_fn=compute)
        assert out == {"intent": "x", "confidence": 0.5}
        obs.assert_called_once_with("intent", "lookup")
        # backfill still happens because key was already computed before the raise.
        backend.set.assert_called_once()

    def test_low_quality_result_not_cached(self) -> None:
        backend = MagicMock()
        backend.get.return_value = None
        cache = IntentCache(backend=backend, enabled=True)
        compute = MagicMock(return_value={"intent": "unk"})
        out = cache.get_or_compute(text="hi", compute_fn=compute)
        assert out == {"intent": "unk"}
        backend.set.assert_not_called()


# ---------------------------------------------------------------------------
# invalidate (lines 202-209)
# ---------------------------------------------------------------------------
class TestInvalidate:
    def test_backend_none_no_op(self) -> None:
        cache = IntentCache(backend=None, enabled=True)
        with patch.object(cache, "_resolve_backend", return_value=None):
            assert cache.invalidate("hi", "m1") is None

    def test_empty_text_no_op(self) -> None:
        backend = MagicMock()
        cache = IntentCache(backend=backend, enabled=True)
        assert cache.invalidate("", "m1") is None
        backend.delete.assert_not_called()

    def test_success_deletes_key(self) -> None:
        backend = MagicMock()
        cache = IntentCache(backend=backend, enabled=True)
        expected_key = cache.make_key("hi", "m1")
        cache.invalidate("hi", "m1")
        backend.delete.assert_called_once_with(expected_key)

    def test_recoverable_error_swallowed(self) -> None:
        backend = MagicMock()
        backend.delete.side_effect = TimeoutError("redis timeout")
        cache = IntentCache(backend=backend, enabled=True)
        # must not raise
        assert cache.invalidate("hi", "m1") is None


# ---------------------------------------------------------------------------
# _default_should_cache_intent (line 215 and others)
# ---------------------------------------------------------------------------
class TestDefaultShouldCacheIntent:
    def test_none_result_not_cached(self) -> None:
        assert _default_should_cache_intent(None) is False

    def test_unk_intent_not_cached(self) -> None:
        assert _default_should_cache_intent({"intent": "unk"}) is False

    def test_missing_intent_not_cached(self) -> None:
        assert _default_should_cache_intent({"intent": ""}) is False

    def test_zero_confidence_not_cached(self) -> None:
        assert _default_should_cache_intent({"intent": "go", "confidence": 0}) is False

    def test_negative_confidence_not_cached(self) -> None:
        assert _default_should_cache_intent({"intent": "go", "confidence": -1}) is False

    def test_good_dict_cached(self) -> None:
        assert _default_should_cache_intent({"intent": "go", "confidence": 0.9}) is True

    def test_non_dict_truthy_cached(self) -> None:
        assert _default_should_cache_intent("a string result") is True


# ---------------------------------------------------------------------------
# _build_redis_client (lines 237-252)
# ---------------------------------------------------------------------------
class TestBuildRedisClient:
    def test_import_error_returns_none(self) -> None:
        # Simulate `import redis` failing inside the function.
        with patch.dict(sys.modules, {"redis": None}):
            assert _build_redis_client() is None

    def test_ping_success_returns_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_client = MagicMock(name="client")
        fake_client.ping.return_value = True
        fake_redis = MagicMock(name="redis_module")
        fake_redis.from_url.return_value = fake_client
        monkeypatch.setenv("CACHE_REDIS_URL", "redis://example:6379/2")
        with patch.dict(sys.modules, {"redis": fake_redis}):
            out = _build_redis_client()
        assert out is fake_client
        fake_client.ping.assert_called_once()
        args, kwargs = fake_redis.from_url.call_args
        assert args[0] == "redis://example:6379/2"
        assert kwargs["decode_responses"] is True
        assert kwargs["socket_connect_timeout"] == 1

    def test_url_fallback_to_redis_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CACHE_REDIS_URL", raising=False)
        monkeypatch.setenv("REDIS_URL", "redis://fallback:6379/3")
        fake_client = MagicMock()
        fake_client.ping.return_value = True
        fake_redis = MagicMock()
        fake_redis.from_url.return_value = fake_client
        with patch.dict(sys.modules, {"redis": fake_redis}):
            _build_redis_client()
        args, _ = fake_redis.from_url.call_args
        assert args[0] == "redis://fallback:6379/3"

    def test_url_default_when_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CACHE_REDIS_URL", raising=False)
        monkeypatch.delenv("REDIS_URL", raising=False)
        fake_client = MagicMock()
        fake_client.ping.return_value = True
        fake_redis = MagicMock()
        fake_redis.from_url.return_value = fake_client
        with patch.dict(sys.modules, {"redis": fake_redis}):
            _build_redis_client()
        args, _ = fake_redis.from_url.call_args
        assert args[0] == "redis://localhost:6379/0"

    def test_connect_failure_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_client = MagicMock()
        fake_client.ping.side_effect = ConnectionError("refused")
        fake_redis = MagicMock()
        fake_redis.from_url.return_value = fake_client
        monkeypatch.setenv("CACHE_REDIS_URL", "redis://dead:6379/0")
        with patch.dict(sys.modules, {"redis": fake_redis}):
            assert _build_redis_client() is None


# ---------------------------------------------------------------------------
# _observe_* metric helpers (lines 255-280)
# ---------------------------------------------------------------------------
class TestObserveHelpers:
    # The helpers do ``from app.utils import metrics as _m`` which resolves the
    # ``metrics`` attribute on the already-imported ``app.utils`` package, so we
    # patch the real metric objects in place.
    METRICS = "app.utils.metrics"

    def test_observe_hit_increments_counter(self) -> None:
        labeled = MagicMock()
        counter = MagicMock(labels=MagicMock(return_value=labeled))
        with patch(f"{self.METRICS}.intent_cache_hits_total", counter):
            _observe_hit("intent", "m1")
        counter.labels.assert_called_once_with(scope="intent", mod_id="m1")
        labeled.inc.assert_called_once()

    def test_observe_hit_default_mod_id_global(self) -> None:
        counter = MagicMock(labels=MagicMock(return_value=MagicMock()))
        with patch(f"{self.METRICS}.intent_cache_hits_total", counter):
            _observe_hit("intent", None)
        counter.labels.assert_called_once_with(scope="intent", mod_id="_global")

    def test_observe_hit_swallows_error(self) -> None:
        # a recoverable error raised while emitting must not propagate.
        counter = MagicMock(labels=MagicMock(side_effect=RuntimeError("metrics broken")))
        with patch(f"{self.METRICS}.intent_cache_hits_total", counter):
            assert _observe_hit("intent", "m1") is None

    def test_observe_miss_increments_and_observes(self) -> None:
        miss_labeled = MagicMock()
        miss_counter = MagicMock(labels=MagicMock(return_value=miss_labeled))
        hist_labeled = MagicMock()
        hist = MagicMock(labels=MagicMock(return_value=hist_labeled))
        with (
            patch(f"{self.METRICS}.intent_cache_misses_total", miss_counter),
            patch(f"{self.METRICS}.intent_cache_compute_seconds", hist),
        ):
            _observe_miss("intent", "m1", 0.123)
        miss_counter.labels.assert_called_once_with(scope="intent", mod_id="m1")
        miss_labeled.inc.assert_called_once()
        hist.labels.assert_called_once_with(scope="intent")
        hist_labeled.observe.assert_called_once_with(0.123)

    def test_observe_miss_swallows_error(self) -> None:
        miss_counter = MagicMock(labels=MagicMock(side_effect=ValueError("boom")))
        with patch(f"{self.METRICS}.intent_cache_misses_total", miss_counter):
            assert _observe_miss("intent", None, 1.0) is None

    def test_observe_error_increments(self) -> None:
        labeled = MagicMock()
        counter = MagicMock(labels=MagicMock(return_value=labeled))
        with patch(f"{self.METRICS}.intent_cache_errors_total", counter):
            _observe_error("intent", "get")
        counter.labels.assert_called_once_with(scope="intent", stage="get")
        labeled.inc.assert_called_once()

    def test_observe_error_swallows_error(self) -> None:
        counter = MagicMock(labels=MagicMock(side_effect=OSError("io")))
        with patch(f"{self.METRICS}.intent_cache_errors_total", counter):
            assert _observe_error("intent", "set") is None


# ---------------------------------------------------------------------------
# make_key behaviour touched by the above paths
# ---------------------------------------------------------------------------
class TestMakeKey:
    def test_global_tenant_when_mod_id_none(self) -> None:
        cache = IntentCache(scope="intent", version="3")
        key = cache.make_key("Hi There", None)
        assert key.startswith("intent:v3:_global:")

    def test_blank_mod_id_falls_back_to_global(self) -> None:
        cache = IntentCache()
        assert ":_global:" in cache.make_key("hi", "   ")

    def test_normalization_collapses_equivalent_inputs(self) -> None:
        cache = IntentCache()
        assert cache.make_key("Hello   World", "m1") == cache.make_key("hello world", "m1")
