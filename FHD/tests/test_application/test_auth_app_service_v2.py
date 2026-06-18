"""Tests for app.application.auth_app_service_v2."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.application.auth_app_service_v2 import AuthAppServiceV2


@pytest.fixture
def mock_bus():
    bus = MagicMock()
    bus.publish = MagicMock(return_value=True)
    return bus


@pytest.fixture
def service(mock_bus):
    with patch("app.application.auth_app_service_v2.get_neuro_bus", return_value=mock_bus):
        with patch(
            "app.application.auth_app_service_v2.instrument_application_service_class",
            side_effect=lambda cls, **kw: cls,
        ):
            svc = AuthAppServiceV2()
    return svc


class TestAuthAppServiceV2:
    def test_create_correlation_id(self, service):
        cid = service._create_correlation_id()
        assert cid.startswith("auth-")

    @pytest.mark.asyncio
    async def test_execute_command_success(self, service, mock_bus):
        mock_event = MagicMock()
        mock_event.metadata.event_id = "evt-123"
        with patch(
            "app.neuro_bus.events.base.NeuroEvent",
            return_value=mock_event,
        ):
            result = await service.execute_command("login", {"username": "admin"})
            assert result["success"] is True
            assert result["event_id"] == "evt-123"
            mock_bus.publish.assert_called_once_with(mock_event)

    @pytest.mark.asyncio
    async def test_execute_command_error(self, service, mock_bus):
        with patch(
            "app.neuro_bus.events.base.NeuroEvent",
            side_effect=RuntimeError("bus error"),
        ):
            result = await service.execute_command("login", {"username": "admin"})
            assert result["success"] is False

    @pytest.mark.asyncio
    async def test_execute_command_event_type(self, service, mock_bus):
        mock_event = MagicMock()
        mock_event.metadata.event_id = "evt-456"
        with patch(
            "app.neuro_bus.events.base.NeuroEvent",
            return_value=mock_event,
        ) as mock_neuro:
            await service.execute_command("logout", {"user_id": 1})
            call_args = mock_neuro.call_args
            assert call_args[1]["event_type"] == "auth.logout"
