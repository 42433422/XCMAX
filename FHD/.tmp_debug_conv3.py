from contextlib import contextmanager
from unittest.mock import MagicMock, patch

class Tracker:
    def __init__(self):
        self.__dict__['intent'] = None
        self.__dict__['user_id'] = None
        self.__dict__['session_id'] = None
        self.__dict__['role'] = None
        self.__dict__['content'] = None
        self.__dict__['conversation_metadata'] = None
        self.__dict__['created_at'] = None
        self.__dict__['id'] = 99

    def __setattr__(self, name, value):
        print(f"setattr {name} = {value!r}")
        super().__setattr__(name, value)

with patch("app.services.conversation_service.AIConversation", new=Tracker):
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
            msg_id = svc.save_message("s", "7", "a", "ok", intent="confirm", metadata="{}")
            print("msg_id:", msg_id)
