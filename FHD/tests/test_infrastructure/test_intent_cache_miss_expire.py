"""Tests for app.infrastructure.cache.intent_cache — coverage ramp C3.3-b.

Covers:
* ``_normalize_text`` whitespace + case folding.
* ``_digest`` 16 hex char output.
* ``IntentCache.get_or_compute`` miss / hit / backend failure.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.infrastructure.cache.intent_cache import (
    IntentCache,
    _digest,
    _normalize_text,
)


class TestNormalize:
    def test_lowercases_and_folds_whitespace(self) -> None:
        assert _normalize_text("  Hello   World  ") == "hello world"

    def test_empty_returns_empty(self) -> None:
        assert _normalize_text("") == ""
        assert _normalize_text(None) == ""  # type: ignore[arg-type]

    def test_punctuation_preserved(self) -> None:
        assert _normalize_text("Hi?") == "hi?"


class TestDigest:
    def test_returns_16_hex_chars(self) -> None:
        d = _digest("hello world")
        assert len(d) == 16
        assert all(c in "0123456789abcdef" for c in d)

    def test_same_input_same_digest(self) -> None:
        assert _digest("foo") == _digest("foo")

    def test_different_input_different_digest(self) -> None:
        assert _digest("foo") != _digest("bar")


class TestIntentCache:
    def test_disabled_cache_always_computes(self) -> None:
        cache = IntentCache(backend=None, enabled=False)
        compute = MagicMock(return_value={"intent": "shipment.create"})
        out = cache.get_or_compute(text="hi", mod_id="m1", compute_fn=compute)
        assert out == {"intent": "shipment.create"}
        compute.assert_called_once()

    def test_get_or_compute_with_backend_hit(self) -> None:
        backend = MagicMock()
        backend.get.return_value = {"intent": "cached"}
        cache = IntentCache(backend=backend, enabled=True, default_ttl=60)
        out = cache.get_or_compute(text="hi", mod_id="m1", compute_fn=lambda: {"intent": "fresh"})
        assert out == {"intent": "cached"}
        backend.get.assert_called_once()

    def test_get_or_compute_with_backend_miss_stores(self) -> None:
        backend = MagicMock()
        backend.get.return_value = None
        cache = IntentCache(backend=backend, enabled=True, default_ttl=60)
        compute = MagicMock(return_value={"intent": "fresh"})
        out = cache.get_or_compute(text="hi", mod_id="m1", compute_fn=compute)
        assert out == {"intent": "fresh"}
        backend.set.assert_called_once()

    def test_backend_failure_falls_through_to_compute(self) -> None:
        backend = MagicMock()
        backend.get.side_effect = ConnectionError("redis down")
        cache = IntentCache(backend=backend, enabled=True)
        compute = MagicMock(return_value={"intent": "computed"})
        out = cache.get_or_compute(text="hi", mod_id="m1", compute_fn=compute)
        assert out == {"intent": "computed"}
        compute.assert_called_once()
