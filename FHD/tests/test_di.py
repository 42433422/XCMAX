"""DI 模块测试：registry 和 fastapi_deps。"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from app.di.registry import (
    ServiceContainer,
    get_service_registry,
    reset_service_registry,
    set_service_registry,
)

# ══════════════════════════════════════════════════════════════════════════════
# ServiceContainer
# ══════════════════════════════════════════════════════════════════════════════


class TestServiceContainer:
    def test_init_all_none(self):
        container = ServiceContainer()
        assert container._session_service is None
        assert container._auth_service is None
        assert container._user_service is None

    def test_invalidate_customer_application_service(self):
        container = ServiceContainer()
        container._customer_application_service = MagicMock()
        container.invalidate_customer_application_service()
        assert container._customer_application_service is None

    def test_invalidate_wechat_contact_application_service(self):
        container = ServiceContainer()
        container._wechat_contact_application_service = MagicMock()
        container._wechat_contact_store = MagicMock()
        container.invalidate_wechat_contact_application_service()
        assert container._wechat_contact_application_service is None
        assert container._wechat_contact_store is None

    def test_invalidate_shipment_wiring(self):
        container = ServiceContainer()
        container._shipment_application_service_core = MagicMock()
        container._shipment_event_primary_facade = MagicMock()
        container.invalidate_shipment_wiring()
        assert container._shipment_application_service_core is None
        assert container._shipment_event_primary_facade is None


# ══════════════════════════════════════════════════════════════════════════════
# Registry globals
# ══════════════════════════════════════════════════════════════════════════════


class TestGetServiceRegistry:
    def test_creates_singleton(self, monkeypatch):
        import app.di.registry as reg

        monkeypatch.setattr(reg, "_registry", None)
        registry = get_service_registry()
        assert isinstance(registry, ServiceContainer)

    def test_returns_same(self, monkeypatch):
        import app.di.registry as reg

        monkeypatch.setattr(reg, "_registry", None)
        r1 = get_service_registry()
        r2 = get_service_registry()
        assert r1 is r2


class TestSetServiceRegistry:
    def test_set_custom(self, monkeypatch):
        import app.di.registry as reg

        custom = ServiceContainer()
        set_service_registry(custom)
        assert get_service_registry() is custom
        set_service_registry(None)

    def test_set_none(self, monkeypatch):
        import app.di.registry as reg

        set_service_registry(None)
        assert reg._registry is None


class TestResetServiceRegistry:
    def test_reset(self, monkeypatch):
        import app.di.registry as reg

        get_service_registry()  # create one
        reset_service_registry()
        assert reg._registry is None


class TestFastapiDeps:
    def test_get_service_container_from_app_state(self):
        from app.di.fastapi_deps import get_service_container

        mock_request = MagicMock()
        mock_container = MagicMock()
        mock_request.app.state.services = mock_container
        result = get_service_container(mock_request)
        assert result is mock_container

    def test_get_service_container_fallback(self, monkeypatch):
        import app.di.registry as reg
        from app.di.fastapi_deps import get_service_container

        monkeypatch.setattr(reg, "_registry", None)
        mock_request = MagicMock()
        mock_request.app.state.services = None
        result = get_service_container(mock_request)
        assert isinstance(result, ServiceContainer)
