# -*- coding: utf-8 -*-
"""Neuro 迁移栈：路由 + Domain 注册 + Application 桥接冒烟（不依赖真实 LLM）。"""

import os

import pytest


def test_migration_smoke_route():
    os.environ.setdefault("XCAGI_NEURO_INTENT", "1")
    from fastapi.testclient import TestClient

    from app.fastapi_app import get_fastapi_app

    client = TestClient(get_fastapi_app())
    r = client.get("/api/neuro/migration-smoke")
    assert r.status_code == 200
    data = r.json()
    assert "registered_domain_count" in data
    assert data.get("neuro_stack_enabled") is True


def test_health_includes_neuro():
    os.environ.setdefault("XCAGI_NEURO_INTENT", "1")
    from fastapi.testclient import TestClient

    from app.fastapi_app import get_fastapi_app

    client = TestClient(get_fastapi_app())
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert "neuro" in body


def test_neurobus_health_route():
    os.environ.setdefault("XCAGI_NEURO_INTENT", "1")
    from fastapi.testclient import TestClient

    from app.fastapi_app import get_fastapi_app

    client = TestClient(get_fastapi_app())
    r = client.get("/api/neurobus/health")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


def test_http_trace_increments_bus_published(monkeypatch):
    """XCAGI_NEURO_HTTP_TRACE=1 且采样 1.0 时，单次请求至少发布 started + completed。"""
    monkeypatch.setenv("XCAGI_NEURO_INTENT", "1")
    monkeypatch.setenv("XCAGI_NEURO_HTTP_TRACE", "1")
    monkeypatch.setenv("XCAGI_NEURO_HTTP_SAMPLE", "1.0")
    from app.neuro_bus.neuro_trace_config import clear_neuro_trace_config_cache

    clear_neuro_trace_config_cache()

    from fastapi.testclient import TestClient

    from app.fastapi_app import get_fastapi_app
    from app.neuro_bus.bus import get_neuro_bus

    with TestClient(get_fastapi_app()) as client:
        bus = get_neuro_bus()
        if not bus.is_running:
            pytest.skip("NeuroBus not running in this app instance")

        before = int(bus.get_stats().get("published", 0))
        r = client.get("/api/health")
        assert r.status_code == 200
        after = int(bus.get_stats().get("published", 0))
        assert after >= before + 2


def test_http_trace_skipped_when_neuro_stack_off(monkeypatch):
    """总线关闭时 HTTP 中间件不发布事件。"""
    monkeypatch.setenv("XCAGI_NEURO_INTENT", "0")
    monkeypatch.setenv("XCAGI_NEURO_HTTP_TRACE", "1")
    monkeypatch.setenv("XCAGI_NEURO_HTTP_SAMPLE", "1.0")
    from app.neuro_bus.neuro_trace_config import clear_neuro_trace_config_cache

    clear_neuro_trace_config_cache()

    from fastapi.testclient import TestClient

    from app.fastapi_app import get_fastapi_app
    from app.neuro_bus.bus import get_neuro_bus

    with TestClient(get_fastapi_app()) as client:
        bus = get_neuro_bus()
        before = int(bus.get_stats().get("published", 0)) if bus.is_running else 0
        assert client.get("/api/health").status_code == 200
        after = int(bus.get_stats().get("published", 0)) if bus.is_running else 0
        assert after == before
