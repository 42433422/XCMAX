"""app/di/registry 与 fastapi_deps 单测（Phase 4 长尾）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.di.fastapi_deps import get_service_container
from app.di.registry import (
    ServiceContainer,
    get_service_registry,
    reset_service_registry,
    set_service_registry,
)


@pytest.fixture(autouse=True)
def _isolate_registry():
    reset_service_registry()
    yield
    reset_service_registry()


class TestServiceRegistry:
    def test_get_creates_singleton(self):
        a = get_service_registry()
        b = get_service_registry()
        assert a is b
        assert isinstance(a, ServiceContainer)

    def test_set_replaces_registry(self):
        custom = ServiceContainer()
        set_service_registry(custom)
        assert get_service_registry() is custom

    def test_reset_drops_then_rebuilds(self):
        first = get_service_registry()
        reset_service_registry()
        second = get_service_registry()
        assert first is not second

    def test_invalidate_shipment_wiring_clears_lazy_attrs(self):
        container = get_service_registry()
        container._shipment_application_service_core = object()  # noqa: SLF001
        container._shipment_event_primary_facade = object()  # noqa: SLF001
        container.invalidate_shipment_wiring()
        assert container._shipment_application_service_core is None  # noqa: SLF001
        assert container._shipment_event_primary_facade is None  # noqa: SLF001


class TestFastapiDeps:
    def test_uses_app_state_services_when_present(self):
        container = ServiceContainer()
        app = SimpleNamespace(state=SimpleNamespace(services=container))
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "app": app,
        }
        req = Request(scope)
        assert get_service_container(req) is container

    def test_falls_back_to_global_registry_when_services_missing(self):
        container = get_service_registry()
        app = SimpleNamespace(state=SimpleNamespace())
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "app": app,
        }
        req = Request(scope)
        assert get_service_container(req) is container
