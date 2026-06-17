"""Tests for app.application.all_hands_app_service."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.all_hands_app_service import (
    get_all_hands_session_local,
    get_all_hands_session_with_authorization,
    prefer_local_all_hands,
    start_all_hands_session_local,
    start_all_hands_session_with_authorization,
)


class TestPreferLocalAllHands:
    """Tests for prefer_local_all_hands."""

    @patch("app.application.all_hands_app_service.prefer_local_modstore", return_value=True)
    def test_returns_true_when_preferred(self, mock_pref: MagicMock) -> None:
        assert prefer_local_all_hands() is True

    @patch("app.application.all_hands_app_service.prefer_local_modstore", return_value=False)
    def test_returns_false_when_not_preferred(self, mock_pref: MagicMock) -> None:
        assert prefer_local_all_hands() is False


class TestStartAllHandsSessionLocal:
    """Tests for start_all_hands_session_local."""

    @pytest.mark.asyncio
    @patch("app.application.all_hands_app_service.modstore_post", new_callable=AsyncMock, return_value={"success": True})
    async def test_calls_modstore_post(self, mock_post: AsyncMock) -> None:
        result = await start_all_hands_session_local()
        assert result["success"] is True
        mock_post.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.application.all_hands_app_service.modstore_post", new_callable=AsyncMock, return_value={"success": True})
    async def test_passes_body(self, mock_post: AsyncMock) -> None:
        result = await start_all_hands_session_local(body={"key": "val"})
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json_body"] == {"key": "val"}

    @pytest.mark.asyncio
    @patch("app.application.all_hands_app_service.modstore_post", new_callable=AsyncMock, return_value={"success": True})
    async def test_default_empty_body(self, mock_post: AsyncMock) -> None:
        result = await start_all_hands_session_local()
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json_body"] == {}


class TestStartAllHandsSessionWithAuthorization:
    """Tests for start_all_hands_session_with_authorization."""

    @pytest.mark.asyncio
    @patch("app.application.all_hands_app_service.modstore_post", new_callable=AsyncMock, return_value={"success": True})
    async def test_passes_authorization(self, mock_post: AsyncMock) -> None:
        result = await start_all_hands_session_with_authorization("Bearer token")
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["authorization"] == "Bearer token"


class TestGetAllHandsSessionLocal:
    """Tests for get_all_hands_session_local."""

    @pytest.mark.asyncio
    @patch("app.application.all_hands_app_service.modstore_get", new_callable=AsyncMock, return_value={"data": {}})
    async def test_valid_session_id(self, mock_get: AsyncMock) -> None:
        result = await get_all_hands_session_local("sess123")
        call_args = mock_get.call_args
        assert "sess123" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_empty_session_id_raises(self) -> None:
        with pytest.raises(ValueError, match="session_id"):
            await get_all_hands_session_local("")

    @pytest.mark.asyncio
    async def test_none_session_id_raises(self) -> None:
        with pytest.raises(ValueError, match="session_id"):
            await get_all_hands_session_local(None)

    @pytest.mark.asyncio
    @patch("app.application.all_hands_app_service.modstore_get", new_callable=AsyncMock, return_value={"data": {}})
    async def test_sanitizes_session_id(self, mock_get: AsyncMock) -> None:
        result = await get_all_hands_session_local("sess!@#123")
        call_args = mock_get.call_args
        assert "sess123" in call_args[0][0]


class TestGetAllHandsSessionWithAuthorization:
    """Tests for get_all_hands_session_with_authorization."""

    @pytest.mark.asyncio
    @patch("app.application.all_hands_app_service.modstore_get", new_callable=AsyncMock, return_value={"data": {}})
    async def test_passes_authorization(self, mock_get: AsyncMock) -> None:
        result = await get_all_hands_session_with_authorization("Bearer token", "sess123")
        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["authorization"] == "Bearer token"

    @pytest.mark.asyncio
    async def test_empty_session_id_raises(self) -> None:
        with pytest.raises(ValueError, match="session_id"):
            await get_all_hands_session_with_authorization("Bearer token", "")
