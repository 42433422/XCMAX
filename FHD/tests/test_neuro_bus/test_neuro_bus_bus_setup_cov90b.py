"""Real-behavior tests for app/neuro_bus/bus_setup.py (second coverage wave).

Targets the previously-uncovered manager lifecycle branches, the synchronous
``init_neuro_bus`` entry point, the lifespan context managers, and the
convenience publish/subscribe/decorator helpers.

Every external dependency (the real ``NeuroBus``, the intent domain, the global
singletons) is mocked. The module-level ``_neuro_bus_manager`` and ``_neuro_bus``
singletons are reset before and after each test so the suite is deterministic and
order-independent.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.neuro_bus.bus_setup as bs
from app.neuro_bus.events.base import EventPriority, NeuroEvent


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Isolate the bus_setup module-level singletons for each test."""
    bs._neuro_bus_manager = None
    yield
    bs._neuro_bus_manager = None


def _fake_bus():
    """A NeuroBus stand-in with the async start/stop coroutines used by start()."""
    bus = MagicMock(name="NeuroBus")
    bus.start = AsyncMock(name="start")
    bus.stop = AsyncMock(name="stop")
    # subscribe / publish / get_stats are plain (sync) calls in the source.
    bus.subscribe = MagicMock(name="subscribe", return_value="SUBSCRIPTION")
    bus.publish = MagicMock(name="publish", return_value=True)
    bus.get_stats = MagicMock(return_value={"queue_size": 7, "published": 3})
    return bus


# ---------------------------------------------------------------------------
# NeuroBusManager.start / stop / _register_system_handlers (lines 33-44, 55-63)
# ---------------------------------------------------------------------------
async def test_manager_start_subscribes_system_handler(monkeypatch):
    """start() pulls the singleton bus, starts it, and subscribes system.* ."""
    bus = _fake_bus()
    monkeypatch.setattr(bs, "get_neuro_bus", lambda: bus)

    mgr = bs.NeuroBusManager()
    await mgr.start()

    assert mgr._started is True
    assert mgr.get_bus() is bus
    bus.start.assert_awaited_once()
    # _register_system_handlers wires a "system.*" subscription with priority=100.
    bus.subscribe.assert_called_once()
    args, kwargs = bus.subscribe.call_args
    assert args[0] == "system.*"
    assert kwargs.get("priority") == 100
    # The handler passed in is the inner on_system_event coroutine fn.
    handler = args[1]
    assert asyncio.iscoroutinefunction(handler)


async def test_manager_system_handler_logs_event(monkeypatch, caplog):
    """The registered system handler logs event_type + source (line 60)."""
    bus = _fake_bus()
    captured = {}
    bus.subscribe = MagicMock(side_effect=lambda et, h, **k: captured.setdefault("handler", h))
    monkeypatch.setattr(bs, "get_neuro_bus", lambda: bus)

    mgr = bs.NeuroBusManager()
    await mgr.start()

    handler = captured["handler"]
    event = NeuroEvent(event_type="system.ping", payload={})
    event.metadata.source = "unit-test-source"
    with caplog.at_level(logging.DEBUG, logger="app.neuro_bus.bus_setup"):
        await handler(event)

    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "system.ping" in joined
    assert "unit-test-source" in joined


async def test_manager_start_idempotent(monkeypatch, caplog):
    """A second start() short-circuits with a warning (lines 33-35)."""
    bus = _fake_bus()
    monkeypatch.setattr(bs, "get_neuro_bus", lambda: bus)

    mgr = bs.NeuroBusManager()
    await mgr.start()
    bus.start.reset_mock()
    bus.subscribe.reset_mock()

    with caplog.at_level(logging.WARNING, logger="app.neuro_bus.bus_setup"):
        await mgr.start()

    # No re-start / re-subscribe on the second call.
    bus.start.assert_not_awaited()
    bus.subscribe.assert_not_called()
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "already started" in joined


async def test_manager_stop_when_started(monkeypatch):
    """stop() after start() stops the bus and flips _started off (lines 51-53)."""
    bus = _fake_bus()
    monkeypatch.setattr(bs, "get_neuro_bus", lambda: bus)

    mgr = bs.NeuroBusManager()
    await mgr.start()
    await mgr.stop()

    bus.stop.assert_awaited_once()
    assert mgr._started is False


async def test_manager_stop_noop_when_never_started():
    """stop() is a no-op when nothing was started (line 48-49)."""
    mgr = bs.NeuroBusManager()
    # No bus assigned; should return cleanly without raising.
    await mgr.stop()
    assert mgr._started is False
    assert mgr.get_bus() is None


# ---------------------------------------------------------------------------
# is_running / get_health (lines 71, 73-87)
# ---------------------------------------------------------------------------
async def test_manager_is_running_transitions(monkeypatch):
    """is_running() reflects start/stop transitions (line 71)."""
    bus = _fake_bus()
    monkeypatch.setattr(bs, "get_neuro_bus", lambda: bus)

    mgr = bs.NeuroBusManager()
    assert mgr.is_running() is False  # not started, no bus

    await mgr.start()
    assert mgr.is_running() is True

    await mgr.stop()
    # _started flipped off -> not running even though bus is still set.
    assert mgr.is_running() is False


def test_manager_get_health_down_when_no_bus():
    """get_health() returns the 'down' shape when no bus exists."""
    mgr = bs.NeuroBusManager()
    health = mgr.get_health()
    assert health == {"status": "down", "running": False, "queue_size": 0}


async def test_manager_get_health_healthy(monkeypatch):
    """get_health() merges bus stats and reports 'healthy' when started."""
    bus = _fake_bus()
    monkeypatch.setattr(bs, "get_neuro_bus", lambda: bus)

    mgr = bs.NeuroBusManager()
    await mgr.start()
    health = mgr.get_health()

    assert health["status"] == "healthy"
    assert health["running"] is True
    # stats are spread in.
    assert health["queue_size"] == 7
    assert health["published"] == 3


# ---------------------------------------------------------------------------
# get_neuro_bus_manager / setup_neuro_bus (singleton + async setup)
# ---------------------------------------------------------------------------
def test_get_neuro_bus_manager_is_singleton():
    """Repeated calls return the same lazily-created manager."""
    m1 = bs.get_neuro_bus_manager()
    m2 = bs.get_neuro_bus_manager()
    assert m1 is m2
    assert isinstance(m1, bs.NeuroBusManager)


async def test_setup_neuro_bus_starts_and_returns_bus(monkeypatch):
    """setup_neuro_bus() starts the singleton manager and returns its bus."""
    bus = _fake_bus()
    monkeypatch.setattr(bs, "get_neuro_bus", lambda: bus)

    returned = await bs.setup_neuro_bus()
    assert returned is bus
    assert bs.get_neuro_bus_manager().is_running() is True


# ---------------------------------------------------------------------------
# init_neuro_bus — sync entry point (lines 115-129)
# ---------------------------------------------------------------------------
async def test_init_neuro_bus_with_running_loop(monkeypatch, caplog):
    """Inside a running loop -> skips asyncio.run, logs, still wires intent (120)."""
    # asyncio.run must NOT be called when a loop is already running.
    called = {"run": 0, "intent": 0}
    monkeypatch.setattr(
        bs.asyncio, "run", lambda coro: called.__setitem__("run", called["run"] + 1)
    )

    fake_intent_mod = SimpleNamespace(
        get_intent_domain=lambda: called.__setitem__("intent", called["intent"] + 1)
    )
    monkeypatch.setitem(
        __import__("sys").modules, "app.neuro_bus.domains.intent_domain", fake_intent_mod
    )

    sentinel_bus = object()
    monkeypatch.setattr(bs, "get_neuro_bus", lambda: sentinel_bus)

    with caplog.at_level(logging.DEBUG, logger="app.neuro_bus.bus_setup"):
        result = bs.init_neuro_bus()

    assert result is sentinel_bus
    assert called["run"] == 0  # running loop -> else branch
    assert called["intent"] == 1  # intent domain wired
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "event loop already running" in joined


def test_init_neuro_bus_no_loop_runs_setup(monkeypatch):
    """No running loop -> asyncio.run(setup_neuro_bus()) is invoked (lines 117-118)."""
    ran = {"run": 0, "intent": 0}

    def fake_run(coro):
        ran["run"] += 1
        # The coroutine must be consumed to avoid 'never awaited' warnings.
        coro.close()

    monkeypatch.setattr(bs.asyncio, "run", fake_run)

    fake_intent_mod = SimpleNamespace(
        get_intent_domain=lambda: ran.__setitem__("intent", ran["intent"] + 1)
    )
    monkeypatch.setitem(
        __import__("sys").modules, "app.neuro_bus.domains.intent_domain", fake_intent_mod
    )

    sentinel_bus = object()
    monkeypatch.setattr(bs, "get_neuro_bus", lambda: sentinel_bus)

    # Called from a synchronous context -> no running loop -> asyncio.run path.
    result = bs.init_neuro_bus()

    assert ran["run"] == 1
    assert ran["intent"] == 1
    assert result is sentinel_bus


def test_init_neuro_bus_intent_import_failure_is_swallowed(monkeypatch, caplog):
    """Intent-domain import raising a RECOVERABLE_ERRORS is logged not raised (126-127)."""
    monkeypatch.setattr(bs.asyncio, "run", lambda coro: coro.close())

    fake_intent_mod = SimpleNamespace(
        get_intent_domain=lambda: (_ for _ in ()).throw(RuntimeError("intent boom"))
    )
    monkeypatch.setitem(
        __import__("sys").modules, "app.neuro_bus.domains.intent_domain", fake_intent_mod
    )

    sentinel_bus = object()
    monkeypatch.setattr(bs, "get_neuro_bus", lambda: sentinel_bus)

    with caplog.at_level(logging.WARNING, logger="app.neuro_bus.bus_setup"):
        result = bs.init_neuro_bus()

    assert result is sentinel_bus  # still returns the bus despite the failure
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "intent domain setup" in joined


# ---------------------------------------------------------------------------
# teardown_neuro_bus / neuro_bus_lifespan (lines 132-149)
# ---------------------------------------------------------------------------
async def test_teardown_neuro_bus_stops_manager(monkeypatch):
    """teardown_neuro_bus() stops the started singleton manager."""
    bus = _fake_bus()
    monkeypatch.setattr(bs, "get_neuro_bus", lambda: bus)

    await bs.setup_neuro_bus()
    assert bs.get_neuro_bus_manager().is_running() is True

    await bs.teardown_neuro_bus()
    bus.stop.assert_awaited_once()
    assert bs.get_neuro_bus_manager().is_running() is False


async def test_neuro_bus_lifespan_setup_yield_teardown(monkeypatch):
    """neuro_bus_lifespan yields the bus and tears down on exit (145-149)."""
    bus = _fake_bus()
    monkeypatch.setattr(bs, "get_neuro_bus", lambda: bus)

    async with bs.neuro_bus_lifespan() as yielded:
        # setup ran -> bus is started and yielded.
        assert yielded is bus
        bus.start.assert_awaited_once()
        bus.stop.assert_not_awaited()

    # exiting the context tears the bus down.
    bus.stop.assert_awaited_once()


# ---------------------------------------------------------------------------
# create_neuro_bus_lifespan (lines 165-180)
# ---------------------------------------------------------------------------
async def test_create_neuro_bus_lifespan_wires_app_state(monkeypatch):
    """The FastAPI lifespan sets up the bus, stores the manager, tears down."""
    bus = _fake_bus()
    monkeypatch.setattr(bs, "get_neuro_bus", lambda: bus)

    app = SimpleNamespace(state=SimpleNamespace())
    lifespan_cm = bs.create_neuro_bus_lifespan(app)

    async with lifespan_cm(app):
        bus.start.assert_awaited_once()
        # manager registered onto app.state.
        assert app.state.neuro_bus_manager is bs.get_neuro_bus_manager()
        bus.stop.assert_not_awaited()

    bus.stop.assert_awaited_once()


# ---------------------------------------------------------------------------
# publish_event (lines 206-214)
# ---------------------------------------------------------------------------
def test_publish_event_success(monkeypatch):
    """publish_event builds a domain-tagged event and forwards it to the bus."""
    bus = _fake_bus()
    monkeypatch.setattr(bs, "get_neuro_bus", lambda: bus)

    ok = bs.publish_event(
        "order.created",
        {"order_id": 42},
        priority=EventPriority.HIGH,
        domain="orders",
    )

    assert ok is True
    bus.publish.assert_called_once()
    published = bus.publish.call_args.args[0]
    assert isinstance(published, NeuroEvent)
    assert published.event_type == "order.created"
    assert published.payload["order_id"] == 42
    assert published.priority is EventPriority.HIGH
    assert published.metadata.domain == "orders"


def test_publish_event_no_bus_returns_false(monkeypatch, caplog):
    """publish_event with a falsy bus warns and returns False (lines 207-209)."""
    monkeypatch.setattr(bs, "get_neuro_bus", lambda: None)

    with caplog.at_level(logging.WARNING, logger="app.neuro_bus.bus_setup"):
        ok = bs.publish_event("x.y", {"a": 1})

    assert ok is False
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "Cannot publish" in joined


def test_publish_event_returns_bus_result(monkeypatch):
    """publish_event propagates the bus.publish() boolean (line 214)."""
    bus = _fake_bus()
    bus.publish = MagicMock(return_value=False)
    monkeypatch.setattr(bs, "get_neuro_bus", lambda: bus)

    assert bs.publish_event("x.y", {}) is False


# ---------------------------------------------------------------------------
# subscribe_event (lines 231-236)
# ---------------------------------------------------------------------------
def test_subscribe_event_success(monkeypatch):
    """subscribe_event forwards to bus.subscribe with the given args (line 236)."""
    bus = _fake_bus()
    monkeypatch.setattr(bs, "get_neuro_bus", lambda: bus)

    def handler(event):
        return None

    result = bs.subscribe_event("user.login", handler, priority=5, is_async=False)

    assert result == "SUBSCRIPTION"
    bus.subscribe.assert_called_once_with("user.login", handler, 5, False)


def test_subscribe_event_no_bus_returns_none(monkeypatch, caplog):
    """subscribe_event with no bus warns and returns None (lines 232-234)."""
    monkeypatch.setattr(bs, "get_neuro_bus", lambda: None)

    with caplog.at_level(logging.WARNING, logger="app.neuro_bus.bus_setup"):
        result = bs.subscribe_event("user.login", lambda e: None)

    assert result is None
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "Cannot subscribe" in joined


# ---------------------------------------------------------------------------
# on_event decorator (lines 257-261)
# ---------------------------------------------------------------------------
def test_on_event_decorator_subscribes_and_returns_func(monkeypatch):
    """@on_event subscribes the wrapped function and returns it unchanged."""
    bus = _fake_bus()
    monkeypatch.setattr(bs, "get_neuro_bus", lambda: bus)

    @bs.on_event("payment.done", priority=2, is_async=True)
    def handle_payment(event):
        return "handled"

    # The original function is returned (decorator is transparent).
    assert handle_payment.__name__ == "handle_payment"
    assert handle_payment(None) == "handled"
    # subscribe_event -> bus.subscribe wired with the decorator args.
    bus.subscribe.assert_called_once_with("payment.done", handle_payment, 2, True)
