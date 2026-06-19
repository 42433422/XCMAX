"""测试 ConversationService.save_message 在 assistant 消息时触发推送。"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def svc():
    from app.services.conversation_service import ConversationService

    return ConversationService()


def _mock_db_with_session(user_id=42, conversation_id=99):
    """构造 mock db，db.refresh 会把 id 写入传入的 conversation 对象。"""
    mock_db = MagicMock()
    mock_session = MagicMock()
    mock_session.user_id = user_id
    mock_db.query.return_value.filter.return_value.first.return_value = mock_session
    mock_db.flush.return_value = None
    mock_db.commit.return_value = None

    def _refresh(obj):
        obj.id = conversation_id

    mock_db.refresh.side_effect = _refresh
    return mock_db


class TestSaveMessagePush:
    def test_assistant_message_triggers_notify_user(self, svc):
        """assistant 消息保存后应触发 notify_user 推送。"""
        mock_db = _mock_db_with_session(user_id=42, conversation_id=99)
        with (
            patch("app.services.conversation_service.get_db") as mock_get_db,
            patch("app.services.conversation_service.notify_user") as mock_notify,
        ):
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_get_db.return_value.__exit__.return_value = False

            svc.save_message(
                session_id="sess-123",
                user_id="42",
                role="assistant",
                content="您好，订单已处理",
            )

        mock_notify.assert_called_once()
        call_kwargs = mock_notify.call_args
        assert call_kwargs.kwargs["user_id"] == 42
        assert "订单已处理" in call_kwargs.kwargs["body"]
        assert call_kwargs.kwargs["data"]["source"] == "ai"
        assert call_kwargs.kwargs["data"]["session_id"] == "sess-123"
        assert call_kwargs.kwargs["data"]["message_id"] == "99"

    def test_user_message_does_not_trigger_notify_user(self, svc):
        """user 消息保存后不应触发推送。"""
        mock_db = _mock_db_with_session(user_id=42, conversation_id=100)
        with (
            patch("app.services.conversation_service.get_db") as mock_get_db,
            patch("app.services.conversation_service.notify_user") as mock_notify,
        ):
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_get_db.return_value.__exit__.return_value = False

            svc.save_message(
                session_id="sess-123",
                user_id="42",
                role="user",
                content="帮我查订单",
            )

        mock_notify.assert_not_called()

    def test_notify_user_failure_does_not_break_save(self, svc):
        """notify_user 失败不应中断消息保存。"""
        mock_db = _mock_db_with_session(user_id=42, conversation_id=101)
        with (
            patch("app.services.conversation_service.get_db") as mock_get_db,
            patch(
                "app.services.conversation_service.notify_user", side_effect=Exception("push fail")
            ),
        ):
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_get_db.return_value.__exit__.return_value = False

            # 不应抛异常
            result = svc.save_message(
                session_id="sess-123",
                user_id="42",
                role="assistant",
                content="测试推送失败不影响保存",
            )
            assert result == 101
