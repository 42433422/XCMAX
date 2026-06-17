"""Tests for app.application.all_hands_app_service."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.application.all_hands_app_service import (
    get_all_hands_session_local,
    get_all_hands_session_with_authorization,
    prefer_local_all_hands,
    start_all_hands_session_local,
    start_all_hands_session_with_authorization,
)


class TestPreferLocalAllHands:
    @patch("app.application.all_hands_app_service.prefer_local_modstore", return_value=True)
    def test_returns_true(self, mock_pref):
        assert prefer_local_all_hands() is True

    @patch("app.application.all_hands_app_service.prefer_local_modstore", return_value=False)
    def test_returns_false(self, mock_pref):
        assert prefer_local_all_hands() is False


class TestStartAllHandsSessionLocal:
    @pytest.mark.asyncio
    @patch("app.application.all_hands_app_service.modstore_post", new_callable=AsyncMock)
    async def test_calls_modstore_post(self, mock_post):
        mock_post.return_value = {"success": True}
        result = await start_all_hands_session_local()
        mock_post.assert_called_once()
        assert result["success"] is True

    @pytest.mark.asyncio
    @patch("app.application.all_hands_app_service.modstore_post", new_callable=AsyncMock)
    async def test_with_body(self, mock_post):
        mock_post.return_value = {"success": True}
        result = await start_all_hands_session_local(body={"key": "val"})
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json_body"] == {"key": "val"}


class TestStartAllHandsSessionWithAuthorization:
    @pytest.mark.asyncio
    @patch("app.application.all_hands_app_service.modstore_post", new_callable=AsyncMock)
    async def test_with_auth(self, mock_post):
        mock_post.return_value = {"success": True}
        result = await start_all_hands_session_with_authorization("Bearer token")
        assert result["success"] is True


class TestGetAllHandsSessionLocal:
    @pytest.mark.asyncio
    @patch("app.application.all_hands_app_service.modstore_get", new_callable=AsyncMock)
    async def test_valid_session_id(self, mock_get):
        mock_get.return_value = {"success": True}
        result = await get_all_hands_session_local("abc123")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_empty_session_id_raises(self):
        with pytest.raises(ValueError, match="session_id 必填"):
            await get_all_hands_session_local("")

    @pytest.mark.asyncio
    async def test_none_session_id_raises(self):
        with pytest.raises(ValueError, match="session_id 必填"):
            await get_all_hands_session_local(None)

    @pytest.mark.asyncio
    @patch("app.application.all_hands_app_service.modstore_get", new_callable=AsyncMock)
    async def test_special_chars_stripped(self, mock_get):
        mock_get.return_value = {"success": True}
        await get_all_hands_session_local("abc-123!@#")
        # Only alphanumeric chars should remain
        call_args = mock_get.call_args[0][0]
        assert "-" not in call_args.split("/")[-1]


class TestGetAllHandsSessionWithAuthorization:
    @pytest.mark.asyncio
    @patch("app.application.all_hands_app_service.modstore_get", new_callable=AsyncMock)
    async def test_with_auth(self, mock_get):
        mock_get.return_value = {"success": True}
        result = await get_all_hands_session_with_authorization("Bearer token", "abc123")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_empty_session_id_raises(self):
        with pytest.raises(ValueError, match="session_id 必填"):
            await get_all_hands_session_with_authorization("Bearer token", "")
