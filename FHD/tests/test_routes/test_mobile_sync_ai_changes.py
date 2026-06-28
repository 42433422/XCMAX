"""测试 mobile_sync_pull 返回 ai_changes 字段。"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True, scope="module")
def _resolve_circular_import():
    """Resolve circular import between mobile_api and mobile_api_extensions."""
    if "app.fastapi_routes.mobile_api_extensions" not in sys.modules:
        from app.fastapi_routes import mobile_api  # noqa: F401
    yield


@pytest.fixture
def ext_mod():
    return sys.modules["app.fastapi_routes.mobile_api_extensions"]


def _build_db_mock(rows):
    """构造 get_db 上下文管理器 mock，query 链路最终返回 rows。

    实现链路：db.query(...).join(...).filter(...).order_by(...).limit(...).all()
    """
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    (
        mock_db.query.return_value.join.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value
    ) = rows
    return mock_db


class TestSyncPullAiChanges:
    @pytest.mark.asyncio
    async def test_sync_pull_returns_ai_changes_field(self, ext_mod):
        """sync/pull 返回体应包含 ai_changes 字段。"""
        user = SimpleNamespace(id=1, username="admin", role="admin")
        body = ext_mod.SyncPullBody(since_cursor=0)

        mock_sync_db = MagicMock()
        mock_sync_db.get_changes.return_value = []
        mock_sync_db.get_status.return_value = {"local_cursor": 100}

        mock_ai_rows = [
            SimpleNamespace(
                id=1,
                session_id="sess-1",
                user_id="1",
                role="assistant",
                content="您好",
                intent="",
                conversation_metadata=None,
                created_at=None,
            ),
        ]
        mock_db = _build_db_mock(mock_ai_rows)

        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_sync_db),
            patch("app.db.session.get_db", return_value=mock_db),
        ):
            result = await ext_mod.mobile_sync_pull(body=body, user=user)

        payload = result if isinstance(result, dict) else __import__("json").loads(result.body)
        assert payload["success"] is True
        assert "ai_changes" in payload["data"]
        assert len(payload["data"]["ai_changes"]) == 1
        assert payload["data"]["ai_changes"][0]["session_id"] == "sess-1"
        assert payload["data"]["ai_changes"][0]["role"] == "assistant"
        assert payload["data"]["ai_changes"][0]["content"] == "您好"

    @pytest.mark.asyncio
    async def test_sync_pull_returns_circle_posts(self, ext_mod):
        """sync/pull 同步 AI 交流圈，供手机后台拉取后写本地缓存。"""
        user = SimpleNamespace(id=1, username="admin", role="admin")
        body = ext_mod.SyncPullBody(since_cursor=0)

        mock_sync_db = MagicMock()
        mock_sync_db.get_changes.return_value = []
        mock_sync_db.get_status.return_value = {"local_cursor": 100}
        circle_posts = [
            {
                "id": 12,
                "employee_id": "task-router-officer",
                "author_name": "任务派发员",
                "body": "今日行动条目",
                "source_type": "loop_report",
                "created_at": "2026-06-28T09:00:00+00:00",
                "like_count": 0,
                "liked_by_me": False,
                "comments": [],
            }
        ]

        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_sync_db),
            patch("app.db.session.get_db", return_value=_build_db_mock([])),
            patch.object(
                ext_mod,
                "_mobile_sync_circle_posts",
                new=AsyncMock(return_value=circle_posts),
            ),
        ):
            result = await ext_mod.mobile_sync_pull(body=body, user=user)

        payload = result if isinstance(result, dict) else __import__("json").loads(result.body)
        assert payload["success"] is True
        assert payload["data"]["circle_post_count"] == 1
        assert payload["data"]["circle_posts"][0]["employee_id"] == "task-router-officer"

    @pytest.mark.asyncio
    async def test_sync_pull_ai_changes_empty_when_no_messages(self, ext_mod):
        """无 AI 消息时 ai_changes 为空列表。"""
        user = SimpleNamespace(id=1, username="admin", role="admin")
        body = ext_mod.SyncPullBody(since_cursor=0)

        mock_sync_db = MagicMock()
        mock_sync_db.get_changes.return_value = []
        mock_sync_db.get_status.return_value = {"local_cursor": 100}

        mock_db = _build_db_mock([])

        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_sync_db),
            patch("app.db.session.get_db", return_value=mock_db),
        ):
            result = await ext_mod.mobile_sync_pull(body=body, user=user)

        payload = result if isinstance(result, dict) else __import__("json").loads(result.body)
        assert payload["success"] is True
        assert payload["data"]["ai_changes"] == []
