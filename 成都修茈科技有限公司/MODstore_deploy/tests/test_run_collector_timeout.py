"""Tests for ``_run_collector_with_timeout`` in workflow_scheduler."""

from __future__ import annotations

import threading
import time

import pytest

from modstore_server.workflow_scheduler import _run_collector_with_timeout


def test_fast_returning_fn_returns_result():
    result = _run_collector_with_timeout(
        lambda: "ok", label="test-fast", timeout=5.0
    )
    assert result == "ok"


def test_fn_exception_propagates():
    def _boom():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        _run_collector_with_timeout(_boom, label="test-boom", timeout=5.0)


def test_hanging_fn_returns_none_within_timeout_plus_buffer():
    event = threading.Event()

    def _hang():
        event.wait(timeout=30)

    started = time.monotonic()
    result = _run_collector_with_timeout(_hang, label="test-hang", timeout=1.0)
    elapsed = time.monotonic() - started

    assert result is None
    assert elapsed < 2.0
    event.set()


def test_hanging_fn_does_not_block_subsequent_call():
    event = threading.Event()

    def _hang():
        event.wait(timeout=30)

    started = time.monotonic()
    r1 = _run_collector_with_timeout(_hang, label="test-seq-1", timeout=0.5)
    e1 = time.monotonic() - started
    assert r1 is None
    assert e1 < 1.5

    started = time.monotonic()
    r2 = _run_collector_with_timeout(
        lambda: "second-ok", label="test-seq-2", timeout=2.0
    )
    e2 = time.monotonic() - started
    assert r2 == "second-ok"
    assert e2 < 1.0

    event.set()


def test_timeout_value_respected():
    event = threading.Event()

    def _hang():
        event.wait(timeout=30)

    started = time.monotonic()
    result = _run_collector_with_timeout(_hang, label="test-timeout-val", timeout=2.0)
    elapsed = time.monotonic() - started

    assert result is None
    assert 1.8 <= elapsed < 3.0
    event.set()


def test_fn_returns_none_legitimately_distinguished_from_timeout():
    def _returns_none():
        return None

    r1 = _run_collector_with_timeout(_returns_none, label="test-none", timeout=2.0)
    assert r1 is None

    event = threading.Event()

    def _hangs():
        event.wait(timeout=30)

    r2 = _run_collector_with_timeout(_hangs, label="test-none-timeout", timeout=0.5)
    assert r2 is None
    event.set()
