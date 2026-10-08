# mypy: disable-error-code="attr-defined"
from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import ANY

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.task_conversation_store import TaskConversationStore, durable_user_id
from app.db.models import AIConversation, AIConversationSession, User


@pytest.fixture
def store(monkeypatch) -> TaskConversationStore:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    User.__table__.create(engine)
    AIConversationSession.__table__.create(engine)
    AIConversation.__table__.create(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        db.add_all(
            [
                User(id=41, username="task-owner", password="test"),
                User(id=42, username="other-owner", password="test"),
            ]
        )
        db.commit()

    @contextmanager
    def isolated_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(
        "app.application.task_conversation_store.get_db",
        isolated_db,
    )
    monkeypatch.setattr("app.services.conversation_service.get_db", isolated_db)
    monkeypatch.setattr("app.services.conversation_service.notify_user", lambda **kwargs: None)
    return TaskConversationStore()


def test_durable_user_id_only_accepts_positive_numeric_actors() -> None:
    assert durable_user_id("41") == 41
    assert durable_user_id(42) == 42
    assert durable_user_id("default") is None
    assert durable_user_id("0") is None


def test_task_conversation_survives_store_recreation_and_lists_metadata(
    store: TaskConversationStore,
) -> None:
    store.save_message(
        session_id="task-conversation-1",
        user_id=41,
        role="user",
        content="查询客户列表",
    )
    store.save_message(
        session_id="task-conversation-1",
        user_id=41,
        role="ai",
        content="当前客户库暂无数据。",
    )

    restarted_store = TaskConversationStore()
    restored = restarted_store.get_conversation(
        session_id="task-conversation-1",
        user_id=41,
    )
    assert [row["content"] for row in restored["messages"]] == [
        "查询客户列表",
        "当前客户库暂无数据。",
    ]
    assert restarted_store.list_sessions(user_id=41, limit=20)[0] == {
        "session_id": "task-conversation-1",
        "title": "查询客户列表",
        "summary": "当前客户库暂无数据。",
        "message_count": 2,
        "created_at": ANY,
        "last_message_at": ANY,
    }


def test_task_conversation_is_owner_scoped(store: TaskConversationStore) -> None:
    store.save_message(
        session_id="private-task",
        user_id=41,
        role="user",
        content="仅本人可见",
    )
    assert store.get_conversation(session_id="private-task", user_id=42)["messages"] == []
    assert store.list_sessions(user_id=42, limit=20) == []
    with pytest.raises(PermissionError):
        store.save_message(
            session_id="private-task",
            user_id=42,
            role="user",
            content="越权追加",
        )


def test_clear_removes_only_current_users_sessions(store: TaskConversationStore) -> None:
    store.save_message(session_id="owner-a", user_id=41, role="user", content="A")
    store.save_message(session_id="owner-b", user_id=42, role="user", content="B")
    assert store.clear_sessions(user_id=41) == 1
    assert store.get_conversation(session_id="owner-a", user_id=41)["messages"] == []
    assert store.get_conversation(session_id="owner-b", user_id=42)["messages"][0]["content"] == "B"


@pytest.mark.parametrize("actor_context", [{"local_user_id": 41, "actor_id": 42}, {"actor_id": 41}])
def test_normal_chat_and_terminal_feedback_reopen_under_authenticated_owner(
    store: TaskConversationStore, monkeypatch, actor_context
) -> None:
    from types import SimpleNamespace

    from starlette.requests import Request

    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.legacy.routes.conversation.compat_extra import conversations_get
    from app.services.conversation_service import ConversationService

    conversation = ConversationService()
    monkeypatch.setattr("app.services.get_conversation_service", lambda: conversation)
    service = object.__new__(AIChatApplicationService)
    service._persist_chat_turn(
        "web_normal_approval-session",
        "创建订单",
        {"session_id": "approval-session", **actor_context},
        {"success": True, "response": "等待审批"},
    )
    conversation.save_message(
        session_id="approval-session",
        user_id="41",
        role="assistant",
        content="审批已完成，销售订单已创建。",
        intent="business_harness_result",
        metadata='{"ui":{"businessResult":{"status":"completed"}}}',
        idempotency_key="terminal-run-1",
    )
    reopened = TaskConversationStore().get_conversation(session_id="approval-session", user_id=41)
    assert [message["content"] for message in reopened["messages"]] == [
        "创建订单",
        "等待审批",
        "审批已完成，销售订单已创建。",
    ]
    assert reopened["session"]["message_count"] == 3
    assert (
        json.loads(reopened["messages"][-1]["metadata"])["ui"]["businessResult"]["status"]
        == "completed"
    )
    assert store.get_conversation(session_id="approval-session", user_id=42)["messages"] == []
    request = Request({"type": "http", "headers": []})
    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies.resolve_session_user",
        lambda _: SimpleNamespace(id=41),
    )
    assert (
        conversations_get(request, "approval-session", user_id="42", mod_id="")["messages"]
        == reopened["messages"]
    )
    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies.resolve_session_user",
        lambda _: SimpleNamespace(id=42),
    )
    assert conversations_get(request, "approval-session", user_id="41", mod_id="")["messages"] == []
