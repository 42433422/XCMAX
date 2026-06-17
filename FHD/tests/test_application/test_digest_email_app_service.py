"""Tests for app.application.digest_email_app_service."""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock

from app.application.digest_email_app_service import (
    _digest_timeout,
    trigger_digest_now_with_authorization,
    trigger_digest_now_local,
    list_daily_digests_local,
    get_daily_digest_local,
    get_daily_digest_artifacts_local,
    list_action_items_local,
    action_items_stats_local,
    set_action_item_status_local,
    start_vibe_prep_local,
    start_line_execute_local,
    get_workbench_session_local,
    allow_local_digest,
)


class TestDigestTimeout:
    def test_default_timeout(self, monkeypatch):
        monkeypatch.delenv("MODSTORE_DIGEST_HTTP_TIMEOUT_SEC", raising=False)
        assert _digest_timeout() == 900.0

    def test_custom_timeout(self, monkeypatch):
        monkeypatch.setenv("MODSTORE_DIGEST_HTTP_TIMEOUT_SEC", "30")
        assert _digest_timeout() == 30.0

    def test_invalid_timeout(self, monkeypatch):
        monkeypatch.setenv("MODSTORE_DIGEST_HTTP_TIMEOUT_SEC", "not_a_number")
        assert _digest_timeout() == 900.0


class TestTriggerDigestNowWithAuthorization:
    @pytest.mark.asyncio
    @patch("app.application.digest_email_app_service.modstore_post", new_callable=AsyncMock)
    async def test_calls_with_auth(self, mock_post):
        mock_post.return_value = {"success": True}
        result = await trigger_digest_now_with_authorization("Bearer token")
        assert result["success"] is True


class TestTriggerDigestNowLocal:
    @pytest.mark.asyncio
    @patch("app.application.digest_email_app_service.modstore_post", new_callable=AsyncMock)
    async def test_calls_without_auth(self, mock_post):
        mock_post.return_value = {"success": True}
        result = await trigger_digest_now_local()
        assert result["success"] is True


class TestListDailyDigestsLocal:
    @pytest.mark.asyncio
    @patch("app.application.digest_email_app_service.modstore_get", new_callable=AsyncMock)
    async def test_default_params(self, mock_get):
        mock_get.return_value = {"success": True}
        result = await list_daily_digests_local()
        assert result["success"] is True

    @pytest.mark.asyncio
    @patch("app.application.digest_email_app_service.modstore_get", new_callable=AsyncMock)
    async def test_custom_params(self, mock_get):
        mock_get.return_value = {"success": True}
        result = await list_daily_digests_local(limit=10, offset=5)
        call_kwargs = mock_get.call_args
        assert "limit=10" in call_kwargs[1]["query"]


class TestGetDailyDigestLocal:
    @pytest.mark.asyncio
    @patch("app.application.digest_email_app_service.modstore_get", new_callable=AsyncMock)
    async def test_calls_with_id(self, mock_get):
        mock_get.return_value = {"success": True}
        result = await get_daily_digest_local(42)
        assert result["success"] is True


class TestGetWorkbenchSessionLocal:
    @pytest.mark.asyncio
    @patch("app.application.digest_email_app_service.modstore_get", new_callable=AsyncMock)
    async def test_valid_session(self, mock_get):
        mock_get.return_value = {"success": True}
        result = await get_workbench_session_local("abc123")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_empty_session_raises(self):
        with pytest.raises(ValueError, match="session_id 必填"):
            await get_workbench_session_local("")

    @pytest.mark.asyncio
    async def test_none_session_raises(self):
        with pytest.raises(ValueError, match="session_id 必填"):
            await get_workbench_session_local(None)


class TestAllowLocalDigest:
    @patch("app.application.digest_email_app_service.prefer_local_modstore", return_value=True)
    def test_returns_true(self, mock_pref):
        assert allow_local_digest() is True

    @patch("app.application.digest_email_app_service.prefer_local_modstore", return_value=False)
    def test_returns_false(self, mock_pref):
        assert allow_local_digest() is False
