"""Durable conversation session clear behavior on an isolated SQLite database."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401
from app.db.base import Base
from app.fastapi_routes.domains.conversation.compat_extra import (
    _conversation_lock,
    _xcagi_user_sessions,
    router,
)
from app.services.conversation_service import ConversationService


def test_delete_sessions_clears_messages_and_session() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)

    @contextmanager
    def _isolated_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    service = ConversationService()
    with patch("app.services.conversation_service.get_db", side_effect=_isolated_db):
        service.save_message("durable-session", "default", "user", "你好")
        service.save_message("durable-session", "default", "assistant", "你好，我在。")
        assert len(service.get_session_messages("durable-session")) == 2
        assert service.get_sessions("default")[0][3] == "你好"

        service.update_session_title("durable-session", "用户自定义标题")
        service.save_message("durable-session", "default", "user", "不要覆盖标题")
        assert service.get_sessions("default")[0][3] == "用户自定义标题"

        deleted = service.delete_sessions("default")

        assert deleted == 1
        assert service.get_session_messages("durable-session") == []
        assert service.get_sessions("default") == []

    engine.dispose()


def test_empty_existing_session_gets_first_user_title() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)

    @contextmanager
    def _isolated_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    service = ConversationService()
    with patch("app.services.conversation_service.get_db", side_effect=_isolated_db):
        service.save_message("assistant-first", "default", "assistant", "主动提示")
        assert service.get_sessions("default")[0][3] is None

        service.save_message(
            "assistant-first",
            "default",
            "user",
            "<div>  查询   今天考勤 </div>\n详情",
        )
        assert service.get_sessions("default")[0][3] == "查询 今天考勤 详情"

    engine.dispose()


def test_user_title_is_bounded() -> None:
    title = ConversationService._title_from_user_content(f"<b>{'问' * 60}</b>")
    assert title == f"{'问' * 48}…"


def test_restart_lists_and_clears_durable_sessions() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)

    @contextmanager
    def _isolated_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    service = ConversationService()
    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)

    with (
        patch("app.services.conversation_service.get_db", side_effect=_isolated_db),
        patch(
            "app.application.facades.conversation_facade.get_conversation_service",
            return_value=service,
        ),
    ):
        service.save_message(
            "restart-session",
            "default",
            "user",
            "<p>  我今天   有没有迟到？ </p>",
        )
        service.save_message("restart-session", "default", "assistant", "你好，我在。")
        with _conversation_lock:
            _xcagi_user_sessions.clear()

        listed = client.get("/api/conversations/sessions")
        loaded = client.get("/api/conversations/restart-session")
        cleared = client.post(
            "/api/conversations/sessions/clear",
            json={"user_id": "default"},
        )
        with _conversation_lock:
            _xcagi_user_sessions.clear()
        listed_after_clear = client.get("/api/conversations/sessions")

    assert [row["session_id"] for row in listed.json()["sessions"]] == ["restart-session"]
    assert listed.json()["sessions"][0]["title"] == "我今天 有没有迟到？"
    assert len(loaded.json()["messages"]) == 2
    assert cleared.json()["deleted"] == 1
    assert listed_after_clear.json()["sessions"] == []
    engine.dispose()
