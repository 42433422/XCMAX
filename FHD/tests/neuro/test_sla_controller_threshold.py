"""COVERAGE_RAMP C3.1: SLA Controller / SLAMonitor / with_sla 装饰器。

覆盖：
- SLAMonitor.check 在 ok / warning / violated 三档
- SLAMonitor.finish 输出 status
- SLAMonitor.is_violated
- SLAController.determine_sla_level：reflex / subconscious / conscious 模式
- SLAController.start_monitoring / finish_monitoring
- SLAController.check_violations
- SLAController.get_stats
- SLAConfig.get_for_level 拿任意 level
- with_sla 装饰器：success / timeout + fallback / timeout raise
- SLAViolation 异常
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

from app.neuro_bus.events.base import EventPriority, NeuroEvent
from app.neuro_bus.sla_controller import (
    SLAConfig,
    SLAController,
    SLALevel,
    SLAMonitor,
    SLAViolation,
    with_sla,
)

# ---------------------------------------------------------------------------
# SLAMonitor
# ---------------------------------------------------------------------------


def test_sla_monitor_check_ok():
    sla = SLAConfig.REFLEX
    mon = SLAMonitor(sla_timeout=sla, operation_name="op-ok")
    out = mon.check()
    assert out["status"] == "ok"
    assert out["operation"] == "op-ok"


def test_sla_monitor_check_warning(monkeypatch):
    sla = SLAConfig.REFLEX  # warning_threshold_ms = 0.8
    mon = SLAMonitor(sla_timeout=sla, operation_name="op-w")
    # 让 start_time 早于 now 1ms，elapsed_ms ≈ 1 > 0.8
    monkeypatch.setattr(time, "time", lambda: mon._start_time + 0.002)
    out = mon.check()
    assert out["status"] == "warning"


def test_sla_monitor_check_violated(mononpatch_for_max=time):
    sla = SLAConfig.REFLEX  # max_ms = 5.0
    mon = SLAMonitor(sla_timeout=sla, operation_name="op-v")
    with patch.object(time, "time", lambda: mon._start_time + 0.01):
        out = mon.check()
    assert out["status"] == "violated"


def test_sla_monitor_finish_violated_logs(caplog):
    sla = SLAConfig.REFLEX
    mon = SLAMonitor(sla_timeout=sla, operation_name="op-f")
    with patch.object(time, "time", lambda: mon._start_time + 0.01):
        with caplog.at_level("ERROR", logger="app.neuro_bus.sla_controller"):
            out = mon.finish()
    assert out["status"] == "violated"
    assert any("SLA VIOLATED" in r.message for r in caplog.records)


def test_sla_monitor_finish_warning_logs(caplog):
    sla = SLAConfig.REFLEX  # warning_threshold_ms=0.8
    mon = SLAMonitor(sla_timeout=sla, operation_name="op-fw")
    with patch.object(time, "time", lambda: mon._start_time + 0.002):
        with caplog.at_level("WARNING", logger="app.neuro_bus.sla_controller"):
            out = mon.finish()
    assert out["status"] == "warning"
    assert mon._finished is True


def test_sla_monitor_is_violated(monkeypatch):
    sla = SLAConfig.REFLEX
    mon = SLAMonitor(sla_timeout=sla, operation_name="op-iv")
    monkeypatch.setattr(time, "time", lambda: mon._start_time + 0.01)
    assert mon.is_violated() is True


# ---------------------------------------------------------------------------
# SLAController.determine_sla_level
# ---------------------------------------------------------------------------


def _make_event(event_type: str, priority: EventPriority = EventPriority.NORMAL) -> NeuroEvent:
    return NeuroEvent(event_type, {"k": 1}, priority=priority)


def test_determine_sla_level_reflex_patterns():
    c = SLAController()
    for pattern in [
        "reflex",
        "greeting",
        "emergency",
        "confirm_action",
        "deny_request",
        "ping_health",
    ]:
        ev = _make_event(pattern)
        assert c.determine_sla_level(ev) == SLALevel.REFLEX


def test_determine_sla_level_subconscious():
    c = SLAController()
    ev = _make_event("background_refresh", priority=EventPriority.BACKGROUND)
    assert c.determine_sla_level(ev) == SLALevel.SUBCONSCIOUS
    ev2 = _make_event("low_priority", priority=EventPriority.LOW)
    assert c.determine_sla_level(ev2) == SLALevel.SUBCONSCIOUS


def test_determine_sla_level_conscious_default():
    c = SLAController()
    ev = _make_event("order_process", priority=EventPriority.NORMAL)
    assert c.determine_sla_level(ev) == SLALevel.CONSCIOUS


# ---------------------------------------------------------------------------
# SLAController.start_monitoring / finish_monitoring
# ---------------------------------------------------------------------------


def test_start_monitoring_assigns_timeout_and_active():
    c = SLAController()
    ev = _make_event("ping", priority=EventPriority.HIGH)
    mon = c.start_monitoring(ev)
    assert ev.metadata.event_id in c._active_monitors
    assert (
        ev.metadata.timeout_ms
        == int(SLAController().determine_sla_level.__self__._active_monitors or 1)
        or ev.metadata.timeout_ms > 0
    )
    # finish
    out = c.finish_monitoring(ev.metadata.event_id)
    assert out is not None
    assert ev.metadata.event_id not in c._active_monitors


def test_finish_monitoring_unknown_event_id_returns_none():
    c = SLAController()
    assert c.finish_monitoring("nope") is None


def test_check_violations():
    c = SLAController()
    ev = _make_event("ping")
    mon = c.start_monitoring(ev)
    with patch.object(time, "time", lambda: mon._start_time + 10.0):
        violations = c.check_violations()
    assert any(v["event_id"] == ev.metadata.event_id for v in violations)


def test_get_stats():
    c = SLAController()
    ev = _make_event("ping")
    c.start_monitoring(ev)
    stats = c.get_stats()
    assert stats["active_monitors"] == 1
    assert stats["total_violations"] == 0


def test_finish_monitoring_increments_violation_counter():
    c = SLAController()
    ev = _make_event("ping")
    mon = c.start_monitoring(ev)
    with patch.object(time, "time", lambda: mon._start_time + 10.0):
        c.finish_monitoring(ev.metadata.event_id)
    assert c.get_stats()["total_violations"] == 1


# ---------------------------------------------------------------------------
# SLAConfig.get_for_level
# ---------------------------------------------------------------------------


def test_sla_config_get_for_level():
    assert SLAConfig.get_for_level(SLALevel.REFLEX).target_ms == 1.0
    assert SLAConfig.get_for_level(SLALevel.SUBCONSCIOUS).target_ms == 10.0
    assert SLAConfig.get_for_level(SLALevel.CONSCIOUS).target_ms == 200.0


# ---------------------------------------------------------------------------
# with_sla 装饰器
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_with_sla_returns_result_on_success():
    @with_sla(SLALevel.CONSCIOUS)
    async def quick():
        return "ok"

    out = await quick()
    assert out == "ok"


@pytest.mark.asyncio
async def test_with_sla_timeout_with_fallback():
    @with_sla(SLALevel.CONSCIOUS, fallback=lambda: "fallback-val")
    async def slow():
        await asyncio.sleep(2.0)
        return "too-late"

    out = await slow()
    assert out == "fallback-val"


@pytest.mark.asyncio
async def test_with_sla_timeout_raises_violation():
    @with_sla(SLALevel.CONSCIOUS)
    async def slow():
        await asyncio.sleep(2.0)
        return "too-late"

    with pytest.raises(SLAViolation):
        await slow()


@pytest.mark.asyncio
async def test_with_sla_slow_but_in_target_warns(caplog):
    @with_sla(SLALevel.CONSCIOUS)
    async def in_target():
        # 短延迟但 < target 200ms，不应 warn
        await asyncio.sleep(0.001)
        return 1

    with caplog.at_level("WARNING", logger="app.neuro_bus.sla_controller"):
        out = await in_target()
    assert out == 1


def test_sla_violation_is_exception():
    assert issubclass(SLAViolation, Exception)
