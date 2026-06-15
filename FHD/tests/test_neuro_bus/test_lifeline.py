"""neuro_bus lifeline 单测。"""

from __future__ import annotations

from app.neuro_bus.events.base import EventMetadata, EventPriority, NeuroEvent
from app.neuro_bus.lifeline import (
    Lifeline,
    NeuroLifeline,
    SystemLoad,
    is_critical_path,
)


def _event(
    event_type: str = "test.event",
    priority: EventPriority = EventPriority.NORMAL,
    domain: str = "test",
) -> NeuroEvent:
    return NeuroEvent(
        event_type=event_type,
        payload={},
        priority=priority,
        metadata=EventMetadata(domain=domain),
    )


def test_lifeline_normal_load_accepts_background():
    ll = Lifeline(queue_threshold_normal=1000)
    ll._last_check = 0
    assert ll.check_system_load(queue_depth=10) == SystemLoad.NORMAL
    assert ll.should_process(_event(priority=EventPriority.BACKGROUND), queue_depth=10) is True


def test_lifeline_high_load_drops_background():
    ll = Lifeline(queue_threshold_high=100, queue_threshold_critical=500)
    ll._last_check = 0
    assert ll.check_system_load(queue_depth=200) == SystemLoad.HIGH
    low = _event(priority=EventPriority.BACKGROUND)
    high = _event(priority=EventPriority.HIGH)
    assert ll.should_process(low, queue_depth=200) is False
    assert ll.should_process(high, queue_depth=200) is True


def test_lifeline_load_change_callback():
    ll = Lifeline(queue_threshold_high=50)
    seen: list[tuple[SystemLoad, SystemLoad]] = []

    def on_change(old: SystemLoad, new: SystemLoad) -> None:
        seen.append((old, new))

    ll.set_load_change_callback(on_change)
    ll._last_check = 0
    ll.check_system_load(queue_depth=100)
    assert seen and seen[0][0] == SystemLoad.NORMAL


def test_lifeline_emergency_recommendations():
    ll = Lifeline()
    ll._current_load = SystemLoad.EMERGENCY
    recs = ll.get_emergency_recommendations()
    assert recs and "CRITICAL" in recs[0]


def test_neuro_lifeline_without_queue_provider():
    nl = NeuroLifeline()
    assert nl.check_event(_event()) is True


def test_neuro_lifeline_with_queue_provider():
    nl = NeuroLifeline()
    nl.set_queue_depth_provider(lambda: 10_000)
    nl._lifeline._last_check = 0
    assert nl.check_event(_event(priority=EventPriority.BACKGROUND)) is False


def test_is_critical_path_domain_and_type():
    assert is_critical_path(_event(domain="payment", priority=EventPriority.LOW)) is True
    assert is_critical_path(_event(event_type="user.login")) is True
    assert is_critical_path(_event(priority=EventPriority.CRITICAL)) is True
    assert is_critical_path(_event(priority=EventPriority.LOW, domain="catalog")) is False
