"""COVERAGE_RAMP C3.1: NeuroBusInitializer 注册顺序 / 异常回滚 / 关闭。

覆盖：
- 重复 initialize 短路
- 注入异常时返回 False
- shutdown 幂等（_initialized=False 后再调用不抛）
- get_initializer 单例化
- get_status 反映 components 状态
- shutdown 错误被吞
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.neuro_bus import initializer as init_mod
from app.neuro_bus.event_store import EventStoreMode
from app.neuro_bus.initializer import NeuroBusInitializer, get_initializer

# ---------------------------------------------------------------------------
# 重复初始化
# ---------------------------------------------------------------------------


def test_initialize_short_circuits_when_already_initialized(monkeypatch):
    init = NeuroBusInitializer()
    init._initialized = True
    # 不应该触发任何 get_* 调用
    assert init.initialize() is True


# ---------------------------------------------------------------------------
# 异常回滚
# ---------------------------------------------------------------------------


def test_initialize_returns_false_on_exception(monkeypatch):
    init = NeuroBusInitializer()
    # 让 event_store 抛错，触发 except 分支
    fake_es = MagicMock(side_effect=RuntimeError("event store init fail"))

    monkeypatch.setattr(init_mod, "get_neuro_bus", lambda: MagicMock())
    monkeypatch.setattr(init_mod, "get_dead_letter_queue", lambda: MagicMock())
    monkeypatch.setattr(init_mod, "get_event_store", fake_es)
    monkeypatch.setattr(init_mod, "get_health_monitor", lambda: MagicMock())
    monkeypatch.setattr(init_mod, "get_retry_handler", lambda: MagicMock())
    monkeypatch.setattr(init_mod, "get_circuit_breaker", lambda: MagicMock())
    monkeypatch.setattr(init_mod, "get_deduplicator", lambda: MagicMock())

    assert init.initialize() is False
    assert init._initialized is False


def test_initialize_with_event_store_mode_passes(monkeypatch):
    init = NeuroBusInitializer()
    monkeypatch.setattr(init_mod, "get_neuro_bus", lambda: MagicMock())
    monkeypatch.setattr(init_mod, "get_dead_letter_queue", lambda: MagicMock())
    monkeypatch.setattr(init_mod, "get_event_store", lambda **k: MagicMock())
    monkeypatch.setattr(init_mod, "get_health_monitor", lambda: MagicMock())
    monkeypatch.setattr(init_mod, "get_retry_handler", lambda: MagicMock())
    monkeypatch.setattr(init_mod, "get_circuit_breaker", lambda: MagicMock())
    monkeypatch.setattr(init_mod, "get_deduplicator", lambda: MagicMock())

    assert init.initialize(event_store_mode=EventStoreMode.SQLITE) is True
    assert init._initialized is True


# ---------------------------------------------------------------------------
# shutdown 幂等
# ---------------------------------------------------------------------------


def test_shutdown_when_not_initialized_is_noop():
    init = NeuroBusInitializer()
    init._initialized = False
    init.shutdown()  # 不抛


def test_shutdown_stops_health_monitor_and_resets():
    init = NeuroBusInitializer()
    init._initialized = True
    fake_hm = MagicMock()
    init._health_monitor = fake_hm
    init.shutdown()
    fake_hm.stop_monitoring.assert_called_once()
    assert init._initialized is False


def test_shutdown_swallows_health_monitor_exception(monkeypatch):
    init = NeuroBusInitializer()
    init._initialized = True
    fake_hm = MagicMock()
    fake_hm.stop_monitoring.side_effect = RuntimeError("hm stop fail")
    init._health_monitor = fake_hm
    init.shutdown()  # 不抛
    assert init._initialized is False  # 仍正确清理


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


def test_get_status_reports_components():
    init = NeuroBusInitializer()
    init._bus = MagicMock()
    init._dlq = MagicMock()
    init._event_store = MagicMock()
    init._health_monitor = MagicMock()
    init._retry_handler = MagicMock()
    init._circuit_breaker = MagicMock()
    init._deduplicator = MagicMock()

    status = init.get_status()
    assert status["initialized"] is False
    for comp, val in status["components"].items():
        assert val is True, f"{comp} should be True"


def test_get_status_with_none_components():
    init = NeuroBusInitializer()
    status = init.get_status()
    assert status["initialized"] is False
    for comp, val in status["components"].items():
        assert val is False


# ---------------------------------------------------------------------------
# 单例
# ---------------------------------------------------------------------------


def test_get_initializer_returns_singleton(monkeypatch):
    init_mod._initializer = None
    a = get_initializer()
    b = get_initializer()
    assert a is b
    init_mod._initializer = None


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------


def test_initialize_neuro_bus_delegates(monkeypatch):
    fake = MagicMock()
    fake.initialize.return_value = True
    monkeypatch.setattr(init_mod, "get_initializer", lambda: fake)
    assert init_mod.initialize_neuro_bus() is True
    fake.initialize.assert_called_once()


def test_shutdown_neuro_bus_delegates(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(init_mod, "get_initializer", lambda: fake)
    init_mod.shutdown_neuro_bus()
    fake.shutdown.assert_called_once()
