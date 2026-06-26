"""Branch-coverage tests for app.infrastructure.cache.intent_cache.

Targets branches NOT already covered by test_intent_cache_miss_expire.py:
* ``IntentCache._resolve_backend`` — backend cached, _build_redis_client returns None,
  RECOVERABLE_ERRORS path.
* ``IntentCache.get`` — disabled, empty text, backend None, RECOVERABLE_ERRORS.
* ``IntentCache.set`` — disabled, empty text, None value, backend None, RECOVERABLE_ERRORS,
  ttl override.
* ``IntentCache.get_or_compute`` — text empty (skips lookup), backend None,
  should_cache predicate True/False, custom should_cache, set failure.
* ``IntentCache.invalidate`` — backend None, empty text, RECOVERABLE_ERRORS.
* ``_default_should_cache_intent`` — None, dict with intent=unk, confidence=0,
  non-dict, valid dict.
* ``_build_redis_client`` — import failure, env var resolution, ping failure.
* ``_observe_hit`` / ``_observe_miss`` / ``_observe_error`` — metrics import failure.
* ``get_intent_cache`` singleton.
* ``make_key`` — mod_id None / empty / whitespace.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.cache.intent_cache import (
    IntentCache,
    _default_should_cache_intent,
    _digest,
    _normalize_text,
    _observe_error,
    _observe_hit,
    _observe_miss,
    get_intent_cache,
)


# ---------------------------------------------------------------------------
# make_key
# ---------------------------------------------------------------------------


class TestMakeKey:
    def test_mod_id_none_uses_global(self) -> None:
        cache = IntentCache(backend=MagicMock(), enabled=True)
        key = cache.make_key("hello", None)
        assert "_global" in key

    def test_mod_id_empty_uses_global(self) -> None:
        cache = IntentCache(backend=MagicMock(), enabled=True)
        key = cache.make_key("hello", "")
        assert "_global" in key

    def test_mod_id_whitespace_uses_global(self) -> None:
        cache = IntentCache(backend=MagicMock(), enabled=True)
        key = cache.make_key("hello", "   ")
        assert "_global" in key

    def test_mod_id_stripped(self) -> None:
        cache = IntentCache(backend=MagicMock(), enabled=True)
        key = cache.make_key("hello", "  mod-1  ")
        assert "mod-1" in key

    def test_key_format(self) -> None:
        cache = IntentCache(scope="test", version="2", backend=MagicMock(), enabled=True)
        key = cache.make_key("hello", "mod-1")
        # format: {scope}:v{version}:{tenant}:{digest}
        assert key.startswith("test:v2:mod-1:")

    def test_same_text_different_mod_id_different_key(self) -> None:
        cache = IntentCache(backend=MagicMock(), enabled=True)
        k1 = cache.make_key("hello", "mod-1")
        k2 = cache.make_key("hello", "mod-2")
        assert k1 != k2


# ---------------------------------------------------------------------------
# _resolve_backend
# ---------------------------------------------------------------------------


class TestResolveBackend:
    def test_returns_cached_backend(self) -> None:
        backend = MagicMock()
        cache = IntentCache(backend=backend, enabled=True)
        assert cache._resolve_backend() is backend

    def test_build_redis_client_returns_none(self) -> None:
        cache = IntentCache(backend=None, enabled=True)
        with patch(
            "app.infrastructure.cache.intent_cache._build_redis_client",
            return_value=None,
        ):
            assert cache._resolve_backend() is None

    def test_builds_and_caches_backend(self) -> None:
        cache = IntentCache(backend=None, enabled=True)
        mock_redis_client = MagicMock()
        mock_redis_cache = MagicMock()
        with (
            patch(
                "app.infrastructure.cache.intent_cache._build_redis_client",
                return_value=mock_redis_client,
            ),
            patch(
                "app.infrastructure.cache.intent_cache.get_redis_cache",
                return_value=mock_redis_cache,
            ),
        ):
            result1 = cache._resolve_backend()
            result2 = cache._resolve_backend()
        assert result1 is mock_redis_cache
        assert result2 is mock_redis_cache
        # _build_redis_client should only be called once (cached)
        assert cache._backend is mock_redis_cache

    def test_recoverable_error_returns_none(self) -> None:
        cache = IntentCache(backend=None, enabled=True)
        with patch(
            "app.infrastructure.cache.intent_cache._build_redis_client",
            side_effect=ConnectionError("redis down"),
        ):
            assert cache._resolve_backend() is None


# ---------------------------------------------------------------------------
# IntentCache.get
# ---------------------------------------------------------------------------


class TestGet:
    def test_disabled_returns_none(self) -> None:
        cache = IntentCache(backend=MagicMock(), enabled=False)
        assert cache.get("hello", "mod-1") is None

    def test_empty_text_returns_none(self) -> None:
        backend = MagicMock()
        cache = IntentCache(backend=backend, enabled=True)
        assert cache.get("", "mod-1") is None
        backend.get.assert_not_called()

    def test_backend_none_returns_none(self) -> None:
        cache = IntentCache(backend=None, enabled=True)
        with patch(
            "app.infrastructure.cache.intent_cache._build_redis_client",
            return_value=None,
        ):
            assert cache.get("hello", "mod-1") is None

    def test_backend_returns_value(self) -> None:
        backend = MagicMock()
        backend.get.return_value = {"intent": "cached"}
        cache = IntentCache(backend=backend, enabled=True)
        assert cache.get("hello", "mod-1") == {"intent": "cached"}

    def test_recoverable_error_returns_none(self) -> None:
        backend = MagicMock()
        backend.get.side_effect = ConnectionError("redis down")
        cache = IntentCache(backend=backend, enabled=True)
        assert cache.get("hello", "mod-1") is None


# ---------------------------------------------------------------------------
# IntentCache.set
# ---------------------------------------------------------------------------


class TestSet:
    def test_disabled_returns_false(self) -> None:
        cache = IntentCache(backend=MagicMock(), enabled=False)
        assert cache.set("hello", {"v": 1}, "mod-1") is False

    def test_empty_text_returns_false(self) -> None:
        backend = MagicMock()
        cache = IntentCache(backend=backend, enabled=True)
        assert cache.set("", {"v": 1}, "mod-1") is False

    def test_none_value_returns_false(self) -> None:
        backend = MagicMock()
        cache = IntentCache(backend=backend, enabled=True)
        assert cache.set("hello", None, "mod-1") is False

    def test_backend_none_returns_false(self) -> None:
        cache = IntentCache(backend=None, enabled=True)
        with patch(
            "app.infrastructure.cache.intent_cache._build_redis_client",
            return_value=None,
        ):
            assert cache.set("hello", {"v": 1}, "mod-1") is False

    def test_successful_set_returns_true(self) -> None:
        backend = MagicMock()
        backend.set.return_value = True
        cache = IntentCache(backend=backend, enabled=True, default_ttl=60)
        assert cache.set("hello", {"v": 1}, "mod-1") is True
        backend.set.assert_called_once()
        # verify ttl passed
        args, kwargs = backend.set.call_args
        assert kwargs.get("ttl") == 60 or args[-1] == 60

    def test_ttl_override(self) -> None:
        backend = MagicMock()
        backend.set.return_value = True
        cache = IntentCache(backend=backend, enabled=True, default_ttl=60)
        cache.set("hello", {"v": 1}, "mod-1", ttl=120)
        args, kwargs = backend.set.call_args
        assert kwargs.get("ttl") == 120 or args[-1] == 120

    def test_recoverable_error_returns_false(self) -> None:
        backend = MagicMock()
        backend.set.side_effect = ConnectionError("redis down")
        cache = IntentCache(backend=backend, enabled=True)
        assert cache.set("hello", {"v": 1}, "mod-1") is False


# ---------------------------------------------------------------------------
# IntentCache.get_or_compute — additional branches
# ---------------------------------------------------------------------------


class TestGetOrComputeExtra:
    def test_empty_text_skips_lookup_computes(self) -> None:
        backend = MagicMock()
        cache = IntentCache(backend=backend, enabled=True)
        compute = MagicMock(return_value={"intent": "fresh", "confidence": 0.9})
        out = cache.get_or_compute(text="", mod_id="m1", compute_fn=compute)
        assert out == {"intent": "fresh", "confidence": 0.9}
        # backend.get should NOT be called because text is empty
        backend.get.assert_not_called()
        compute.assert_called_once()

    def test_backend_none_computes_directly(self) -> None:
        cache = IntentCache(backend=None, enabled=True)
        with patch(
            "app.infrastructure.cache.intent_cache._build_redis_client",
            return_value=None,
        ):
            compute = MagicMock(return_value={"intent": "fresh", "confidence": 0.9})
            out = cache.get_or_compute(text="hi", mod_id="m1", compute_fn=compute)
            assert out == {"intent": "fresh", "confidence": 0.9}
            compute.assert_called_once()

    def test_should_cache_false_skips_set(self) -> None:
        backend = MagicMock()
        backend.get.return_value = None
        cache = IntentCache(backend=backend, enabled=True)
        # intent=unk → _default_should_cache_intent returns False
        compute = MagicMock(return_value={"intent": "unk"})
        out = cache.get_or_compute(text="hi", mod_id="m1", compute_fn=compute)
        assert out == {"intent": "unk"}
        backend.set.assert_not_called()

    def test_custom_should_cache_predicate(self) -> None:
        backend = MagicMock()
        backend.get.return_value = None
        cache = IntentCache(backend=backend, enabled=True)
        compute = MagicMock(return_value={"intent": "x", "confidence": 0.9})
        cache.get_or_compute(
            text="hi",
            mod_id="m1",
            compute_fn=compute,
            should_cache=lambda r: False,
        )
        backend.set.assert_not_called()

    def test_custom_should_cache_true_stores(self) -> None:
        backend = MagicMock()
        backend.get.return_value = None
        cache = IntentCache(backend=backend, enabled=True)
        compute = MagicMock(return_value={"custom": "data"})
        cache.get_or_compute(
            text="hi",
            mod_id="m1",
            compute_fn=compute,
            should_cache=lambda r: True,
        )
        backend.set.assert_called_once()

    def test_set_failure_does_not_raise(self) -> None:
        backend = MagicMock()
        backend.get.return_value = None
        backend.set.side_effect = ConnectionError("redis down")
        cache = IntentCache(backend=backend, enabled=True)
        compute = MagicMock(return_value={"intent": "x", "confidence": 0.9})
        out = cache.get_or_compute(text="hi", mod_id="m1", compute_fn=compute)
        assert out == {"intent": "x", "confidence": 0.9}

    def test_lookup_failure_falls_through_to_compute(self) -> None:
        backend = MagicMock()
        backend.get.side_effect = ConnectionError("redis down")
        cache = IntentCache(backend=backend, enabled=True)
        compute = MagicMock(return_value={"intent": "x", "confidence": 0.9})
        out = cache.get_or_compute(text="hi", mod_id="m1", compute_fn=compute)
        assert out == {"intent": "x", "confidence": 0.9}
        compute.assert_called_once()

    def test_text_empty_with_backend_still_computes(self) -> None:
        backend = MagicMock()
        cache = IntentCache(backend=backend, enabled=True)
        compute = MagicMock(return_value={"intent": "x", "confidence": 0.9})
        out = cache.get_or_compute(text="", mod_id="m1", compute_fn=compute)
        assert out == {"intent": "x", "confidence": 0.9}
        # key is None when text empty → set skipped
        backend.set.assert_not_called()


# ---------------------------------------------------------------------------
# IntentCache.invalidate
# ---------------------------------------------------------------------------


class TestInvalidate:
    def test_backend_none_noop(self) -> None:
        cache = IntentCache(backend=None, enabled=True)
        with patch(
            "app.infrastructure.cache.intent_cache._build_redis_client",
            return_value=None,
        ):
            cache.invalidate("hello", "mod-1")  # should not raise

    def test_empty_text_noop(self) -> None:
        backend = MagicMock()
        cache = IntentCache(backend=backend, enabled=True)
        cache.invalidate("", "mod-1")
        backend.delete.assert_not_called()

    def test_successful_invalidate(self) -> None:
        backend = MagicMock()
        cache = IntentCache(backend=backend, enabled=True)
        cache.invalidate("hello", "mod-1")
        backend.delete.assert_called_once()

    def test_recoverable_error_noop(self) -> None:
        backend = MagicMock()
        backend.delete.side_effect = ConnectionError("redis down")
        cache = IntentCache(backend=backend, enabled=True)
        cache.invalidate("hello", "mod-1")  # should not raise


# ---------------------------------------------------------------------------
# _default_should_cache_intent
# ---------------------------------------------------------------------------


class TestDefaultShouldCacheIntent:
    def test_none_returns_false(self) -> None:
        assert _default_should_cache_intent(None) is False

    def test_dict_with_unk_intent_returns_false(self) -> None:
        assert _default_should_cache_intent({"intent": "unk"}) is False

    def test_dict_with_empty_intent_returns_false(self) -> None:
        assert _default_should_cache_intent({"intent": ""}) is False

    def test_dict_with_zero_confidence_returns_false(self) -> None:
        assert _default_should_cache_intent({"intent": "x", "confidence": 0}) is False

    def test_dict_with_none_confidence_returns_false(self) -> None:
        assert _default_should_cache_intent({"intent": "x", "confidence": None}) is False

    def test_dict_with_valid_intent_and_confidence_returns_true(self) -> None:
        assert _default_should_cache_intent({"intent": "x", "confidence": 0.9}) is True

    def test_dict_with_valid_intent_no_confidence_returns_false(self) -> None:
        # When confidence is missing, `result.get("confidence") or 0` → 0
        # → float(0) <= 0 → returns False
        assert _default_should_cache_intent({"intent": "x"}) is False

    def test_non_dict_returns_true(self) -> None:
        assert _default_should_cache_intent("string") is True
        assert _default_should_cache_intent(42) is True
        assert _default_should_cache_intent([1, 2]) is True

    def test_dict_with_negative_confidence_returns_false(self) -> None:
        assert _default_should_cache_intent({"intent": "x", "confidence": -0.5}) is False


# ---------------------------------------------------------------------------
# _build_redis_client
# ---------------------------------------------------------------------------


class TestBuildRedisClient:
    def test_import_failure_returns_none(self) -> None:
        import builtins

        original_import = builtins.__import__

        def _fail_import(name, *args, **kwargs):
            if name == "redis":
                raise ImportError("no redis")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_fail_import):
            from app.infrastructure.cache.intent_cache import _build_redis_client

            assert _build_redis_client() is None

    def test_uses_cache_redis_url_env_var(self) -> None:
        mock_redis = MagicMock()
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_redis.from_url.return_value = mock_client
        with (
            patch.dict(
                os.environ,
                {"CACHE_REDIS_URL": "redis://custom:6380/1"},
                clear=False,
            ),
            patch("redis.from_url", mock_redis.from_url) if False else patch.dict(
                "sys.modules", {"redis": mock_redis}
            ),
        ):
            from app.infrastructure.cache.intent_cache import _build_redis_client

            result = _build_redis_client()
            assert result is mock_client
            mock_redis.from_url.assert_called_once()
            call_args = mock_redis.from_url.call_args
            assert "redis://custom:6380/1" in call_args[0]

    def test_uses_redis_url_fallback(self) -> None:
        mock_redis = MagicMock()
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_redis.from_url.return_value = mock_client
        # Ensure CACHE_REDIS_URL is not set
        env = {k: v for k, v in os.environ.items() if k != "CACHE_REDIS_URL"}
        env["REDIS_URL"] = "redis://fallback:6379/2"
        with (
            patch.dict(os.environ, env, clear=True),
            patch.dict("sys.modules", {"redis": mock_redis}),
        ):
            from app.infrastructure.cache.intent_cache import _build_redis_client

            result = _build_redis_client()
            assert result is mock_client
            call_args = mock_redis.from_url.call_args
            assert "redis://fallback:6379/2" in call_args[0]

    def test_ping_failure_returns_none(self) -> None:
        mock_redis = MagicMock()
        mock_client = MagicMock()
        mock_client.ping.side_effect = ConnectionError("ping failed")
        mock_redis.from_url.return_value = mock_client
        with (
            patch.dict(os.environ, {"CACHE_REDIS_URL": "redis://x:6379/0"}, clear=True),
            patch.dict("sys.modules", {"redis": mock_redis}),
        ):
            from app.infrastructure.cache.intent_cache import _build_redis_client

            assert _build_redis_client() is None


# ---------------------------------------------------------------------------
# metrics observers
# ---------------------------------------------------------------------------


class TestObserveMetrics:
    def test_observe_hit_metrics_import_failure_noop(self) -> None:
        # Force metrics import to fail by making app.utils.metrics raise on attribute access
        import sys

        original = sys.modules.get("app.utils.metrics")
        sys.modules["app.utils.metrics"] = None  # type: ignore
        try:
            _observe_hit("test", "mod-1")  # should not raise
        finally:
            if original is not None:
                sys.modules["app.utils.metrics"] = original
            else:
                sys.modules.pop("app.utils.metrics", None)

    def test_observe_miss_metrics_import_failure_noop(self) -> None:
        import sys

        original = sys.modules.get("app.utils.metrics")
        sys.modules["app.utils.metrics"] = None  # type: ignore
        try:
            _observe_miss("test", "mod-1", 0.5)  # should not raise
        finally:
            if original is not None:
                sys.modules["app.utils.metrics"] = original
            else:
                sys.modules.pop("app.utils.metrics", None)

    def test_observe_error_metrics_import_failure_noop(self) -> None:
        import sys

        original = sys.modules.get("app.utils.metrics")
        sys.modules["app.utils.metrics"] = None  # type: ignore
        try:
            _observe_error("test", "get")  # should not raise
        finally:
            if original is not None:
                sys.modules["app.utils.metrics"] = original
            else:
                sys.modules.pop("app.utils.metrics", None)

    def test_observe_hit_with_real_metrics_module(self) -> None:
        # The real app.utils.metrics module exists; verify _observe_hit doesn't raise
        # and exercises the success path (labels().inc() called).
        _observe_hit("test-scope", "mod-1")  # should not raise
        _observe_hit("test-scope", None)  # mod_id None → "_global"

    def test_observe_miss_with_real_metrics_module(self) -> None:
        # The real app.utils.metrics module exists; verify _observe_miss doesn't raise.
        _observe_miss("test-scope", "mod-1", 0.5)  # should not raise
        _observe_miss("test-scope", None, 0.0)  # mod_id None → "_global"

    def test_observe_error_with_real_metrics_module(self) -> None:
        # The real app.utils.metrics module exists; verify _observe_error doesn't raise.
        _observe_error("test-scope", "get")  # should not raise
        _observe_error("test-scope", "set")  # should not raise

    def test_observe_hit_mod_id_none_uses_global(self) -> None:
        # Verify mod_id None is converted to "_global" — just ensure no raise.
        _observe_hit("test", None)

    def test_observe_miss_mod_id_none_uses_global(self) -> None:
        _observe_miss("test", None, 0.1)


# ---------------------------------------------------------------------------
# get_intent_cache singleton
# ---------------------------------------------------------------------------


class TestGetIntentCache:
    def test_returns_singleton(self) -> None:
        # Reset singleton
        import app.infrastructure.cache.intent_cache as mod

        original = mod._default_intent_cache
        mod._default_intent_cache = None
        try:
            c1 = get_intent_cache()
            c2 = get_intent_cache()
            assert c1 is c2
        finally:
            mod._default_intent_cache = original


# ---------------------------------------------------------------------------
# _normalize_text / _digest — additional edge cases
# ---------------------------------------------------------------------------


class TestNormalizeTextExtra:
    def test_none_returns_empty(self) -> None:
        assert _normalize_text(None) == ""  # type: ignore[arg-type]

    def test_internal_whitespace_collapsed(self) -> None:
        assert _normalize_text("hello    world\tfoo") == "hello world foo"

    def test_mixed_case_lowered(self) -> None:
        assert _normalize_text("HeLLo WORLD") == "hello world"


class TestDigestExtra:
    def test_empty_string_returns_digest(self) -> None:
        d = _digest("")
        assert len(d) == 16

    def test_none_raises(self) -> None:
        # _digest calls text.encode — None.encode raises AttributeError
        # which is NOT in RECOVERABLE_ERRORS, so it propagates.
        # This documents the behavior.
        with pytest.raises(AttributeError):
            _digest(None)  # type: ignore[arg-type]
