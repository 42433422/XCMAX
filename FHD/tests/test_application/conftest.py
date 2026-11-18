"""Real, isolated SQL lifecycle for transcript and subprocess recovery tests."""

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def dialogue_db(monkeypatch, tmp_path_factory):
    from app.application.ai_chat import dialogue_memory
    from app.db.models import AIConversation, AIConversationSession, User

    database_url = f"sqlite:///{tmp_path_factory.mktemp('dialogue-sql') / 'history.sqlite'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    engine = create_engine(database_url, connect_args={"timeout": 10})
    for table in (User.__table__, AIConversationSession.__table__, AIConversation.__table__):
        table.create(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add_all(
            User(id=i, username=f"owner-{i}", password="test") for i in (1, 2, 31, 41, 42, 71)
        )
        db.commit()

    @contextmanager
    def isolated_db():
        with factory() as db:
            yield db

    monkeypatch.setattr("app.application.task_conversation_store.get_db", isolated_db)
    yield factory
    for lease in tuple(dialogue_memory._INFLIGHT.values()):
        lease.release()
    dialogue_memory._INFLIGHT.clear()
    engine.dispose()
