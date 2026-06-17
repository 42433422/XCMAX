from contextlib import contextmanager
from unittest.mock import MagicMock, patch

conv = MagicMock()
conv.id = 11

with patch("app.services.conversation_service.AIConversation", return_value=conv):
    from app.services.conversation_service import ConversationService

    svc = ConversationService()
    mock_db = MagicMock()
    mock_query = MagicMock()
    existing_session = MagicMock()
    existing_session.message_count = 0
    mock_query.filter.return_value.first.return_value = existing_session
    mock_db.query.return_value = mock_query

    @contextmanager
    def ctx():
        yield mock_db

    with patch("app.services.conversation_service.get_db", return_value=ctx()):
        with patch.object(svc, "_normalize_user_id", return_value=7):
            svc.save_message("s", "7", "a", "ok", intent="confirm", metadata="{}")

print("conv.intent:", repr(conv.intent))
print("type conv.intent:", type(conv.intent))
print("conv.user_id:", repr(conv.user_id))
