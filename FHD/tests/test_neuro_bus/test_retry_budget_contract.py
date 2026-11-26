from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from contextlib import closing

import pytest

from app.neuro_bus.bus import NeuroBus
from app.neuro_bus.bus_primitives import HandlerSubscription
from app.neuro_bus.dead_letter_queue import (
    DeadLetterQueue,
    DeadLetterReason,
    NeuroBusDLQIntegration,
)
from app.neuro_bus.events.events_base import NeuroEvent
from app.neuro_bus.retry_handler import NeuroRetryHandler, RetryConfig, RetryHandler


def make_bus(
    monkeypatch: pytest.MonkeyPatch,
    *,
    budget: float = 1.0,
    max_retries: int = 3,
    delay: float = 0.0,
) -> tuple[NeuroBus, DeadLetterQueue]:
    monkeypatch.setenv("FHD_ENV", "test")
    monkeypatch.setenv("XCAGI_NEURO_BUS_CIRCUIT", "0")
    bus = NeuroBus(enable_metrics=False, handler_timeout_sec=budget)
    retry = NeuroRetryHandler()
    retry._handlers["global"] = RetryHandler(
        RetryConfig(max_retries=max_retries, base_delay=delay, jitter=False)
    )
    bus._rel_retry_handler = retry
    dlq = DeadLetterQueue()
    bus._dlq_integration = NeuroBusDLQIntegration(dlq)
    return bus, dlq


@pytest.mark.parametrize(
    ("max_retries", "errors", "expected_retries", "reason"),
    [
        (3, [ValueError], 0, DeadLetterReason.INVALID_PAYLOAD),
        (2, [ConnectionError] * 3, 2, DeadLetterReason.RETRY_EXHAUSTED),
        (5, [ConnectionError] * 6, 5, DeadLetterReason.RETRY_EXHAUSTED),
        (3, [ConnectionError] * 3 + [ValueError], 3, DeadLetterReason.INVALID_PAYLOAD),
        (0, [ConnectionError], 0, DeadLetterReason.RETRY_EXHAUSTED),
    ],
)
def test_dlq_records_invocations_and_terminal_reason(
    monkeypatch, max_retries, errors, expected_retries, reason
):
    bus, dlq = make_bus(monkeypatch, max_retries=max_retries)
    calls = 0

    async def handler(event):
        nonlocal calls
        error = errors[calls]
        calls += 1
        raise error("handler failed")

    try:
        subscription = HandlerSubscription("test.event", handler)
        assert not asyncio.run(bus._call_handler(subscription, NeuroEvent("test.event", {})))
        (entry,) = dlq.get_all_entries()
        assert calls == expected_retries + 1
        assert entry.retry_count == expected_retries
        assert entry.reason == reason
    finally:
        bus._executor.shutdown(wait=True)


def test_backoff_that_cannot_fit_budget_is_not_an_attempt(monkeypatch):
    bus, dlq = make_bus(monkeypatch, budget=0.1, delay=2.0)
    calls = 0

    async def handler(event):
        nonlocal calls
        calls += 1
        raise ConnectionError("retryable")

    try:
        subscription = HandlerSubscription("test.event", handler)
        assert not asyncio.run(bus._call_handler(subscription, NeuroEvent("test.event", {})))
        (entry,) = dlq.get_all_entries()
        assert calls == 1
        assert entry.retry_count == 0
        assert entry.reason == DeadLetterReason.TIMEOUT
    finally:
        bus._executor.shutdown(wait=True)


def test_timeout_during_actual_retry_uses_original_budget(monkeypatch):
    bus, dlq = make_bus(monkeypatch, budget=0.1)
    calls = 0

    async def handler(event):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("retryable")
        await asyncio.sleep(10)

    try:
        subscription = HandlerSubscription("test.event", handler)
        assert not asyncio.run(bus._call_handler(subscription, NeuroEvent("test.event", {})))
        (entry,) = dlq.get_all_entries()
        assert calls == 2
        assert entry.retry_count == 1
        assert entry.reason == DeadLetterReason.TIMEOUT
    finally:
        bus._executor.shutdown(wait=True)


def test_event_expiry_prevents_new_invocation(monkeypatch):
    bus, dlq = make_bus(monkeypatch)
    calls = 0

    async def handler(event):
        nonlocal calls
        calls += 1

    try:
        event = NeuroEvent("test.event", {}).with_timeout(100)
        event.metadata.timestamp -= 1
        subscription = HandlerSubscription("test.event", handler)
        assert not asyncio.run(bus._call_handler(subscription, event))
        (entry,) = dlq.get_all_entries()
        assert calls == 0
        assert entry.retry_count == 0
        assert entry.reason == DeadLetterReason.TIMEOUT
    finally:
        bus._executor.shutdown(wait=True)


def test_successful_retry_reports_actual_attempts():
    retry = RetryHandler(RetryConfig(max_retries=3, base_delay=0, jitter=False))
    context = retry.new_context("operation")
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("retryable")
        return "ok"

    async def run():
        return await retry.execute(
            operation, retry_context=context, deadline=asyncio.get_running_loop().time() + 1
        )

    assert asyncio.run(run()) == "ok"
    assert context.get_report()["attempts"] == calls == 2
    assert context.retry_count == 1
    assert context.get_report()["success"] is True


def test_sync_timeout_not_retried(monkeypatch):
    bus, dlq = make_bus(monkeypatch)
    calls = 0

    def handler(event):
        nonlocal calls
        calls += 1
        raise TimeoutError("side effect outcome unknown")

    try:
        subscription = HandlerSubscription("test.event", handler, is_async=False)
        assert not asyncio.run(bus._call_handler(subscription, NeuroEvent("test.event", {})))
        (entry,) = dlq.get_all_entries()
        assert calls == 1
        assert entry.retry_count == 0
        assert entry.reason == DeadLetterReason.TIMEOUT
    finally:
        bus._executor.shutdown(wait=True)


def test_sync_budget_expiry_drains_original_future_without_retry(monkeypatch):
    bus, dlq = make_bus(monkeypatch, budget=0.1)
    started = threading.Event()
    finished = threading.Event()
    calls = 0

    def handler(event):
        nonlocal calls
        calls += 1
        started.set()
        time.sleep(0.2)
        finished.set()

    try:
        subscription = HandlerSubscription("test.event", handler, is_async=False)
        assert not asyncio.run(bus._call_handler(subscription, NeuroEvent("test.event", {})))
        (entry,) = dlq.get_all_entries()
        assert started.is_set() and finished.is_set()
        assert calls == 1
        assert entry.retry_count == 0
        assert entry.reason == DeadLetterReason.TIMEOUT
    finally:
        bus._executor.shutdown(wait=True)


def test_cancelled_backoff_does_not_count_scheduled_retry():
    retry = RetryHandler(RetryConfig(max_retries=3, base_delay=10, jitter=False))
    context = retry.new_context("operation")
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        raise ConnectionError("retryable")

    async def run():
        waiting = asyncio.Event()

        def on_retry(error, number):
            waiting.set()

        task = asyncio.create_task(
            retry.execute(operation, retry_context=context, on_retry=on_retry)
        )
        await asyncio.wait_for(waiting.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert calls == context.get_report()["attempts"] == 1
    assert context.retry_count == 0
    assert not context.retry_exhausted


def test_async_handler_cannot_report_success_after_budget(monkeypatch):
    bus, dlq = make_bus(monkeypatch, budget=0.1)

    async def handler(event):
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            return

    try:
        subscription = HandlerSubscription("test.event", handler)
        assert not asyncio.run(bus._call_handler(subscription, NeuroEvent("test.event", {})))
        (entry,) = dlq.get_all_entries()
        assert entry.retry_count == 0
        assert entry.reason == DeadLetterReason.TIMEOUT
    finally:
        bus._executor.shutdown(wait=True)


@pytest.mark.parametrize("committed", [False, True])
def test_timeout_does_not_prove_absence_of_committed_effect(monkeypatch, tmp_path, committed):
    bus, dlq = make_bus(monkeypatch, budget=0.5)
    receipt_path = tmp_path / "independent-receipts.sqlite3"
    event = NeuroEvent("test.event", {})
    event_id = event.metadata.event_id
    with closing(sqlite3.connect(receipt_path)) as writer, writer:
        writer.execute("CREATE TABLE receipts (event_id TEXT PRIMARY KEY)")
    calls = 0

    async def handler(incoming):
        nonlocal calls
        calls += 1
        if committed:
            with closing(sqlite3.connect(receipt_path)) as writer, writer:
                writer.execute("INSERT INTO receipts VALUES (?)", (incoming.metadata.event_id,))
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            # The handler returns late, regardless of whether it committed.
            return

    try:
        subscription = HandlerSubscription("test.event", handler)
        assert not asyncio.run(bus._call_handler(subscription, event))
        (entry,) = dlq.get_all_entries()
        assert entry.original_event.metadata.event_id == event_id
        assert entry.retry_count == 0
        assert entry.reason == DeadLetterReason.TIMEOUT
        assert calls == 1
        # A separate connection reads durable state rather than handler claims.
        with closing(sqlite3.connect(receipt_path)) as reader:
            rows = reader.execute(
                "SELECT event_id FROM receipts WHERE event_id = ?", (event_id,)
            ).fetchall()
        assert rows == ([(event_id,)] if committed else [])
    finally:
        bus._executor.shutdown(wait=True)
