"""Tests for app.application.digest_email_app_service."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.digest_email_app_service import (
    _digest_timeout,
    allow_local_digest,
    get_daily_digest_artifacts_local,
    get_daily_digest_local,
    get_workbench_session_local,
    list_action_items_local,
    list_daily_digests_local,
    set_action_item_status_local,
    start_line_execute_local,
    start_vibe_prep_local,
    trigger_digest_now_local,
    trigger_digest_now_with_authorization,
)


class TestDigestTimeout:
    """Tests for _digest_timeout."""

    def test_default_timeout(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            result = _digest_timeout()
            assert result == 900.0

    def test_custom_timeout(self) -> None:
        with patch.dict("os.environ", {"MODSTORE_DIGEST_HTTP_TIMEOUT_SEC": "30"}):
            result = _digest_timeout()
            assert result == 30.0

    def test_invalid_timeout_falls_back(self) -> None:
        with patch.dict("os.environ", {"MODSTORE_DIGEST_HTTP_TIMEOUT_SEC": "not_a_number"}):
            result = _digest_timeout()
            assert result == 900.0


class TestAllowLocalDigest:
    """Tests for allow_local_digest."""

    @patch("app.application.digest_email_app_service.prefer_local_modstore", return_value=True)
    def test_returns_true_when_preferred(self, mock_pref: MagicMock) -> None:
        assert allow_local_digest() is True

    @patch("app.application.digest_email_app_service.prefer_local_modstore", return_value=False)
    def test_returns_false_when_not_preferred(self, mock_pref: MagicMock) -> None:
        assert allow_local_digest() is False


class TestTriggerDigestNowWithAuthorization:
    """Tests for trigger_digest_now_with_authorization."""

    @pytest.mark.asyncio
    @patch("app.application.digest_email_app_service.modstore_post", new_callable=AsyncMock, return_value={"success": True})
    async def test_calls_modstore_post_with_auth(self, mock_post: AsyncMock) -> None:
        result = await trigger_digest_now_with_authorization("Bearer token123")
        assert result["success"] is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["authorization"] == "Bearer token123"


class TestTriggerDigestNowLocal:
    """Tests for trigger_digest_now_local."""

    @pytest.mark.asyncio
    @patch("app.application.digest_email_app_service.modstore_post", new_callable=AsyncMock, return_value={"success": True})
    async def test_calls_modstore_post(self, mock_post: AsyncMock) -> None:
        result = await trigger_digest_now_local()
        assert result["success"] is True


class TestListDailyDigestsLocal:
    """Tests for list_daily_digests_local."""

    @pytest.mark.asyncio
    @patch("app.application.digest_email_app_service.modstore_get", new_callable=AsyncMock, return_value={"data": []})
    async def test_default_pagination(self, mock_get: AsyncMock) -> None:
        result = await list_daily_digests_local()
        assert "data" in result

    @pytest.mark.asyncio
    @patch("app.application.digest_email_app_service.modstore_get", new_callable=AsyncMock, return_value={"data": []})
    async def test_custom_pagination(self, mock_get: AsyncMock) -> None:
        result = await list_daily_digests_local(limit=50, offset=10)
        call_kwargs = mock_get.call_args
        assert "limit=50" in call_kwargs[1]["query"]
        assert "offset=10" in call_kwargs[1]["query"]

    @pytest.mark.asyncio
    @patch("app.application.digest_email_app_service.modstore_get", new_callable=AsyncMock, return_value={"data": []})
    async def test_limit_capped_at_100(self, mock_get: AsyncMock) -> None:
        result = await list_daily_digests_local(limit=200)
        call_kwargs = mock_get.call_args
        assert "limit=100" in call_kwargs[1]["query"]


class TestGetDailyDigestLocal:
    """Tests for get_daily_digest_local."""

    @pytest.mark.asyncio
    @patch("app.application.digest_email_app_service.modstore_get", new_callable=AsyncMock, return_value={"data": {"id": 1}})
    async def test_calls_with_record_id(self, mock_get: AsyncMock) -> None:
        result = await get_daily_digest_local(42)
        call_args = mock_get.call_args
        assert "/42" in call_args[0][0]


class TestGetDailyDigestArtifactsLocal:
    """Tests for get_daily_digest_artifacts_local."""

    @pytest.mark.asyncio
    @patch("app.application.digest_email_app_service.modstore_get", new_callable=AsyncMock, return_value={"data": []})
    async def test_calls_with_artifacts_path(self, mock_get: AsyncMock) -> None:
        result = await get_daily_digest_artifacts_local(5)
        call_args = mock_get.call_args
        assert "/5/artifacts" in call_args[0][0]


class TestListActionItemsLocal:
    """Tests for list_action_items_local."""

    @pytest.mark.asyncio
    @patch("app.application.digest_email_app_service.modstore_get", new_callable=AsyncMock, return_value={"data": []})
    async def test_no_filters(self, mock_get: AsyncMock) -> None:
        result = await list_action_items_local()
        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["query"] == ""

    @pytest.mark.asyncio
    @patch("app.application.digest_email_app_service.modstore_get", new_callable=AsyncMock, return_value={"data": []})
    async def test_with_kind_filter(self, mock_get: AsyncMock) -> None:
        result = await list_action_items_local(kind="urgent")
        call_kwargs = mock_get.call_args
        assert "kind=urgent" in call_kwargs[1]["query"]

    @pytest.mark.asyncio
    @patch("app.application.digest_email_app_service.modstore_get", new_callable=AsyncMock, return_value={"data": []})
    async def test_with_both_filters(self, mock_get: AsyncMock) -> None:
        result = await list_action_items_local(kind="urgent", day="2026-01-01")
        call_kwargs = mock_get.call_args
        assert "kind=urgent" in call_kwargs[1]["query"]
        assert "day=2026-01-01" in call_kwargs[1]["query"]


class TestSetActionItemStatusLocal:
    """Tests for set_action_item_status_local."""

    @pytest.mark.asyncio
    @patch("app.application.digest_email_app_service.modstore_post", new_callable=AsyncMock, return_value={"success": True})
    async def test_calls_with_item_id_and_status(self, mock_post: AsyncMock) -> None:
        result = await set_action_item_status_local(10, "done")
        call_args = mock_post.call_args
        assert "/10/status" in call_args[0][0]
        assert call_args[1]["json_body"] == {"status": "done"}


class TestStartVibePrepLocal:
    """Tests for start_vibe_prep_local."""

    @pytest.mark.asyncio
    @patch("app.application.digest_email_app_service.modstore_post", new_callable=AsyncMock, return_value={"success": True})
    async def test_calls_with_record_id(self, mock_post: AsyncMock) -> None:
        result = await start_vibe_prep_local(3)
        call_args = mock_post.call_args
        assert "/3/vibe-prep/sessions" in call_args[0][0]

    @pytest.mark.asyncio
    @patch("app.application.digest_email_app_service.modstore_post", new_callable=AsyncMock, return_value={"success": True})
    async def test_calls_with_custom_body(self, mock_post: AsyncMock) -> None:
        result = await start_vibe_prep_local(3, body={"key": "val"})
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json_body"] == {"key": "val"}


class TestStartLineExecuteLocal:
    """Tests for start_line_execute_local."""

    @pytest.mark.asyncio
    @patch("app.application.digest_email_app_service.modstore_post", new_callable=AsyncMock, return_value={"success": True})
    async def test_calls_with_record_id(self, mock_post: AsyncMock) -> None:
        result = await start_line_execute_local(7)
        call_args = mock_post.call_args
        assert "/7/line-execute" in call_args[0][0]


class TestGetWorkbenchSessionLocal:
    """Tests for get_workbench_session_local."""

    @pytest.mark.asyncio
    @patch("app.application.digest_email_app_service.modstore_get", new_callable=AsyncMock, return_value={"data": {}})
    async def test_valid_session_id(self, mock_get: AsyncMock) -> None:
        result = await get_workbench_session_local("sess123")
        call_args = mock_get.call_args
        assert "sess123" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_empty_session_id_raises(self) -> None:
        with pytest.raises(ValueError, match="session_id"):
            await get_workbench_session_local("")

    @pytest.mark.asyncio
    async def test_none_session_id_raises(self) -> None:
        with pytest.raises(ValueError, match="session_id"):
            await get_workbench_session_local(None)

    @pytest.mark.asyncio
    @patch("app.application.digest_email_app_service.modstore_get", new_callable=AsyncMock, return_value={"data": {}})
    async def test_sanitizes_session_id(self, mock_get: AsyncMock) -> None:
        result = await get_workbench_session_local("sess!@#123")
        call_args = mock_get.call_args
        # Only alphanumeric chars should remain
        assert "sess123" in call_args[0][0]
