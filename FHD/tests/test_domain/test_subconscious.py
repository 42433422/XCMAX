"""Tests for app.domain.neuro.processors.subconscious — coverage ramp."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.neuro.processors.subconscious import (
    BatchBuffer,
    LoggingHandler,
    MetricsHandler,
    SubconsciousProcessor,
    get_subconscious_processor,
    subconscious_log,
)


def _make_event(event_type: str = "test_event", payload: dict | None = None):
    from app.neuro_bus.events.base import EventMetadata, EventPriority, NeuroEvent

    meta = EventMetadata(event_id=f"evt-{event_type}", source="test", trace_id="c1")
    return NeuroEvent(
        event_type=event_type,
        payload=payload or {"key": "value"},
        metadata=meta,
        priority=EventPriority.NORMAL,
    )


# ---------------------------------------------------------------------------
# BatchBuffer
# ---------------------------------------------------------------------------


class TestBatchBuffer:
    def test_creation(self):
        buf = BatchBuffer(events=[], max_size=10, max_wait_ms=5.0, created_at=0.0)
        assert buf.max_size == 10
        assert buf.events == []


# ---------------------------------------------------------------------------
# SubconsciousProcessor
# ---------------------------------------------------------------------------


class TestSubconsciousProcessorInit:
    def test_default_init(self):
        with patch("app.domain.neuro.processors.subconscious.get_neuro_bus"):
            proc = SubconsciousProcessor()
            assert proc._running is False
            assert proc._processed_count == 0
            assert proc._enable_batching is True

    def test_custom_init(self):
        mock_bus = MagicMock()
        proc = SubconsciousProcessor(bus=mock_bus, enable_batching=False, batch_size=5)
        assert proc._bus is mock_bus
        assert proc._enable_batching is False
        assert proc._batch_size == 5


class TestSubconsciousProcessorStartStop:
    @pytest.mark.asyncio
    async def test_start(self):
        with patch("app.domain.neuro.processors.subconscious.get_neuro_bus"):
            proc = SubconsciousProcessor(enable_batching=False)
            await proc.start()
            assert proc._running is True
            await proc.stop()

    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        with patch("app.domain.neuro.processors.subconscious.get_neuro_bus"):
            proc = SubconsciousProcessor(enable_batching=False)
            await proc.start()
            await proc.start()  # Should not error
            assert proc._running is True
            await proc.stop()

    @pytest.mark.asyncio
    async def test_stop_flushes_batches(self):
        with patch("app.domain.neuro.processors.subconscious.get_neuro_bus"):
            proc = SubconsciousProcessor(enable_batching=True)
            await proc.start()
            batch_handler = AsyncMock()
            proc.register_handler(
                "test", AsyncMock(), supports_batching=True, batch_handler=batch_handler
            )
            proc._batches["test"].events.append(_make_event())
            await proc.stop()
            assert proc._running is False


class TestSubconsciousProcessorRegisterHandler:
    def test_register_handler(self):
        with patch("app.domain.neuro.processors.subconscious.get_neuro_bus"):
            proc = SubconsciousProcessor(enable_batching=False)
            handler = MagicMock()
            proc.register_handler("test_event", handler)
            assert "test_event" in proc._handlers

    def test_register_batch_handler(self):
        with patch("app.domain.neuro.processors.subconscious.get_neuro_bus"):
            proc = SubconsciousProcessor(enable_batching=True)
            handler = MagicMock()
            batch_handler = MagicMock()
            proc.register_handler(
                "test_event", handler, supports_batching=True, batch_handler=batch_handler
            )
            assert "test_event" in proc._batch_handlers
            assert "test_event" in proc._batches


class TestSubconsciousProcessorProcess:
    @pytest.mark.asyncio
    async def test_process_no_handler(self):
        with patch("app.domain.neuro.processors.subconscious.get_neuro_bus"):
            proc = SubconsciousProcessor(enable_batching=False)
            result = await proc.process(_make_event())
            assert result is False

    @pytest.mark.asyncio
    async def test_process_async_handler(self):
        with patch("app.domain.neuro.processors.subconscious.get_neuro_bus"):
            proc = SubconsciousProcessor(enable_batching=False)
            handler = AsyncMock()
            proc.register_handler("test_event", handler)
            result = await proc.process(_make_event("test_event"))
            assert result is True
            handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_sync_handler(self):
        with patch("app.domain.neuro.processors.subconscious.get_neuro_bus"):
            proc = SubconsciousProcessor(enable_batching=False)
            handler = MagicMock()
            proc.register_handler("test_event", handler)
            result = await proc.process(_make_event("test_event"))
            assert result is True

    @pytest.mark.asyncio
    async def test_process_timeout(self):
        with patch("app.domain.neuro.processors.subconscious.get_neuro_bus"):
            proc = SubconsciousProcessor(enable_batching=False)

            async def slow_handler(event):
                await asyncio.sleep(60)

            proc.register_handler("test_event", slow_handler)
            result = await proc.process(_make_event("test_event"))
            assert result is False
            assert proc._timeout_count > 0

    @pytest.mark.asyncio
    async def test_process_error(self):
        with patch("app.domain.neuro.processors.subconscious.get_neuro_bus"):
            proc = SubconsciousProcessor(enable_batching=False)
            handler = AsyncMock(side_effect=RuntimeError("handler error"))
            proc.register_handler("test_event", handler)
            result = await proc.process(_make_event("test_event"))
            assert result is False
            assert proc._error_count > 0

    @pytest.mark.asyncio
    async def test_batch_process(self):
        with patch("app.domain.neuro.processors.subconscious.get_neuro_bus"):
            proc = SubconsciousProcessor(enable_batching=True, batch_size=2)
            batch_handler = AsyncMock()
            proc.register_handler(
                "test_event", AsyncMock(), supports_batching=True, batch_handler=batch_handler
            )
            result = await proc.process(_make_event("test_event"))
            assert result is True
            assert proc._batched_count == 1

    @pytest.mark.asyncio
    async def test_batch_flush_on_size(self):
        with patch("app.domain.neuro.processors.subconscious.get_neuro_bus"):
            proc = SubconsciousProcessor(enable_batching=True, batch_size=1)
            batch_handler = AsyncMock()
            proc.register_handler(
                "test_event", AsyncMock(), supports_batching=True, batch_handler=batch_handler
            )
            await proc.process(_make_event("test_event"))
            batch_handler.assert_called_once()


class TestSubconsciousProcessorStats:
    def test_get_stats_initial(self):
        with patch("app.domain.neuro.processors.subconscious.get_neuro_bus"):
            proc = SubconsciousProcessor()
            stats = proc.get_stats()
            assert stats["processed"] == 0
            assert stats["batched"] == 0
            assert stats["errors"] == 0
            assert stats["running"] is False

    def test_get_stats_with_latency(self):
        with patch("app.domain.neuro.processors.subconscious.get_neuro_bus"):
            proc = SubconsciousProcessor()
            proc._latency_history.append(5.0)
            proc._latency_history.append(10.0)
            stats = proc.get_stats()
            assert stats["avg_latency_ms"] == 7.5


# ---------------------------------------------------------------------------
# LoggingHandler
# ---------------------------------------------------------------------------


class TestLoggingHandler:
    @pytest.mark.asyncio
    async def test_handle(self):
        handler = LoggingHandler()
        event = _make_event()
        await handler.handle(event)  # Should not raise


# ---------------------------------------------------------------------------
# MetricsHandler
# ---------------------------------------------------------------------------


class TestMetricsHandler:
    @pytest.mark.asyncio
    async def test_handle_batch(self):
        handler = MetricsHandler()
        events = [_make_event("type_a"), _make_event("type_b"), _make_event("type_a")]
        await handler.handle_batch(events)
        assert handler._counters["type_a"] == 2
        assert handler._counters["type_b"] == 1


# ---------------------------------------------------------------------------
# subconscious_log
# ---------------------------------------------------------------------------


class TestSubconsciousLog:
    @pytest.mark.asyncio
    async def test_log_info(self):
        await subconscious_log("test message", level="info")

    @pytest.mark.asyncio
    async def test_log_with_context(self):
        await subconscious_log("test message", context={"key": "value"})


# ---------------------------------------------------------------------------
# get_subconscious_processor
# ---------------------------------------------------------------------------


class TestGetSubconsciousProcessor:
    def test_returns_instance(self):
        import app.domain.neuro.processors.subconscious as mod

        mod._subconscious = None
        with patch("app.domain.neuro.processors.subconscious.get_neuro_bus"):
            proc = get_subconscious_processor()
            assert isinstance(proc, SubconsciousProcessor)
        mod._subconscious = None  # reset
