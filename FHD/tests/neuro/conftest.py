"""Shared fixtures for NeuroBus test files (COVERAGE_RAMP C3.1).

集中提供:
- reset_command_gateway: 清 _pending 字典 + _gateway 全局
- reset_health_monitor: 清 _health_monitor_instance + 内部 deque
- reset_bus_singleton: 重置 app.neuro_bus.bus._bus
- reset_initializer: 重置 _initializer 单例 + 标志位
- reset_user_memory_service: 重置 _user_memory_service 单例
- reset_event_publisher_mixin: 抑制 publish_event 副作用
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def reset_command_gateway(monkeypatch):
    """重置 CommandGateway 单例及其 _pending 字典。"""
    from app.neuro_bus import command_gateway as cg

    if cg._gateway is not None:
        cg._gateway._pending.clear()
    monkeypatch.setattr(cg, "_gateway", None)
    yield
    if cg._gateway is not None:
        cg._gateway._pending.clear()
    monkeypatch.setattr(cg, "_gateway", None)


@pytest.fixture
def reset_health_monitor(monkeypatch):
    """重置 HealthMonitor 单例。"""
    from app.neuro_bus import health_monitor as hm

    monkeypatch.setattr(hm, "_health_monitor_instance", None)
    yield
    monkeypatch.setattr(hm, "_health_monitor_instance", None)


@pytest.fixture
def reset_bus_singleton(monkeypatch):
    """重置 NeuroBus 单例。"""
    from app.neuro_bus import bus as bus_mod

    monkeypatch.setattr(bus_mod, "_bus", None)
    yield
    monkeypatch.setattr(bus_mod, "_bus", None)


@pytest.fixture
def reset_initializer(monkeypatch):
    """重置 NeuroBusInitializer 单例。"""
    from app.neuro_bus import initializer as init_mod

    monkeypatch.setattr(init_mod, "_initializer", None)
    yield
    monkeypatch.setattr(init_mod, "_initializer", None)


@pytest.fixture
def reset_runtime_diagnostics_logger(monkeypatch):
    """截获 logger.info 调试 runtime_diagnostics 输出。"""
    import logging

    captured = []
    real_info = logging.Logger.info

    def fake_info(self, msg, *args, **kwargs):
        captured.append(msg % args if args else msg)
        return real_info(self, msg, *args, **kwargs)

    monkeypatch.setattr(logging.Logger, "info", fake_info)
    return captured


@pytest.fixture
def reset_user_memory_service(monkeypatch):
    """重置 UserMemoryService 单例。"""
    from app.services import user_memory_service

    monkeypatch.setattr(user_memory_service, "_user_memory_service", None)
    monkeypatch.setattr(user_memory_service.UserMemoryStore, "_instance", None)
    yield
    monkeypatch.setattr(user_memory_service, "_user_memory_service", None)
    monkeypatch.setattr(user_memory_service.UserMemoryStore, "_instance", None)


@pytest.fixture
def mock_event_publisher(monkeypatch):
    """抑制 NeuroEventPublisherMixin 副作用。"""
    fake_publisher = MagicMock()
    monkeypatch.setattr(
        "app.neuro_bus.event_publisher_mixin.NeuroEventPublisherMixin.publish_event",
        fake_publisher,
        raising=False,
    )
    return fake_publisher
