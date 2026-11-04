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
    monkeypatch.setattr("app.domain.shared_services.conversation_service.get_db", isolated_db)
    monkeypatch.setattr(
        "app.domain.shared_services.conversation_service.notify_user", lambda **kwargs: None
    )
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


def test_compat_persistence_cannot_append_to_another_owners_session(store: TaskConversationStore):
    from app.domain.shared_services.conversation_service import ConversationService

    store.save_message(session_id="private-session", user_id=41, role="user", content="本人内容")
    with pytest.raises(PermissionError):
        ConversationService().save_message(
            session_id="private-session",
            user_id="42",
            role="assistant",
            content="越权回复",
        )
    assert len(store.get_conversation(session_id="private-session", user_id=41)["messages"]) == 1


@pytest.mark.parametrize("action", ["read", "rename", "delete", "append"])
def test_legacy_history_routes_cannot_access_other_owners_session(store, monkeypatch, action):
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.fastapi_routes.domains.conversation.conversation_routes import router

    store.save_message(session_id="private-route", user_id=41, role="user", content="本人内容")
    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies.resolve_session_user",
        lambda request: SimpleNamespace(id=42),
    )
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        if action == "read":
            result = client.get("/api/conversations/private-route")
            assert result.json()["messages"] == []
        elif action == "rename":
            assert (
                client.put("/api/conversations/private-route/title", json={"title": "越权"}).json()[
                    "success"
                ]
                is False
            )
        elif action == "delete":
            assert client.delete("/api/conversations/private-route").json()["success"] is False
        else:
            assert (
                client.post(
                    "/api/ai/message/save",
                    json={
                        "session_id": "private-route",
                        "user_id": "41",
                        "role": "user",
                        "content": "越权",
                    },
                ).status_code
                == 403
            )
    original = store.get_conversation(session_id="private-route", user_id=41)
    assert original["session"]["title"] == "本人内容"
    assert [m["content"] for m in original["messages"]] == ["本人内容"]


@pytest.mark.parametrize("actor_context", [{"local_user_id": 41, "actor_id": 41}, {"actor_id": 41}])
def test_normal_chat_and_terminal_feedback_reopen_under_authenticated_owner(
    store: TaskConversationStore, monkeypatch, actor_context
) -> None:
    from types import SimpleNamespace

    from starlette.requests import Request

    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.domain.shared_services.conversation_service import ConversationService
    from app.legacy.routes.conversation.compat_extra import conversations_get

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


@pytest.mark.parametrize("existing_session", [False, True])
def test_client_message_retry_is_atomic_across_connections(tmp_path, monkeypatch, existing_session):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    engine = create_engine(f"sqlite:///{tmp_path / 'retry.sqlite'}", connect_args={"timeout": 10})
    for model in (User, AIConversationSession, AIConversation):
        model.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(User(id=41, username="retry-owner", password="test"))
        db.commit()

    @contextmanager
    def connection():
        with factory() as db:
            yield db

    monkeypatch.setattr("app.application.task_conversation_store.get_db", connection)
    durable = TaskConversationStore()
    if existing_session:
        durable.save_message(
            session_id="retry-session", user_id=41, role="user", content="existing"
        )
    barrier = Barrier(2)

    def save(_):
        barrier.wait(timeout=5)
        return durable.save_message(
            session_id="retry-session",
            user_id=41,
            role="user",
            content="one message",
            client_message_id="message-stable-1",
            metadata='{"ui":{"contextSummary":"summary"}}',
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(save, range(2)))
    assert ids[0] == ids[1]
    history = durable.get_conversation(session_id="retry-session", user_id=41)
    assert history["session"]["message_count"] == (2 if existing_session else 1)
    assert sum(message["content"] == "one message" for message in history["messages"]) == 1
    metadata = json.loads(history["messages"][-1]["metadata"])
    assert metadata["client_message_id"] == "message-stable-1"
    assert metadata["ui"]["contextSummary"] == "summary"
    with pytest.raises(ValueError, match="original content"):
        durable.save_message(
            session_id="retry-session",
            user_id=41,
            role="user",
            content="different",
            client_message_id="message-stable-1",
        )
    engine.dispose()


def test_paged_history_and_retried_save_use_authenticated_owner(store, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    import httpx
    from fastapi import FastAPI

    from app.legacy.routes.conversation.compat_extra import router

    for index in range(25):
        store.save_message(
            session_id=f"owned-{index}", user_id=41, role="user", content=f"row {index}"
        )
    store.save_message(session_id="other-owner", user_id=42, role="user", content="private")
    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies.resolve_session_user",
        lambda _: SimpleNamespace(id=41),
    )
    monkeypatch.setattr(
        "app.neuro_bus.route_event_publisher.publish_simple_event", lambda *args, **kwargs: None
    )
    app = FastAPI()
    app.include_router(router, prefix="/api")

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            first = (
                await client.get(
                    "/api/conversations/sessions",
                    params={"limit": 20, "offset": 0, "user_id": "42"},
                )
            ).json()
            second = (
                await client.get(
                    "/api/conversations/sessions",
                    params={"limit": 20, "offset": first["next_offset"]},
                )
            ).json()
            assert len(first["sessions"]) == 20 and first["has_more"] is True
            assert len(second["sessions"]) == 5 and second["has_more"] is False
            assert len({row["session_id"] for row in first["sessions"] + second["sessions"]}) == 25
            assert all(
                row["session_id"] != "other-owner" for row in first["sessions"] + second["sessions"]
            )
            payload = {
                "session_id": "retry-http",
                "user_id": "42",
                "role": "user",
                "content": "save only",
                "client_message_id": "message-http-1",
            }
            a = await client.post("/api/conversations/message", json=payload)
            b = await client.post("/api/conversations/message", json=payload)
            assert a.status_code == b.status_code == 200
            assert a.json()["message_id"] == b.json()["message_id"]
            assert a.json()["durable"] is True
            rejected = await client.post(
                "/api/conversations/message", json={**payload, "content": "changed"}
            )
            assert rejected.status_code == 409
            foreign = await client.post(
                "/api/conversations/message", json={**payload, "session_id": "other-owner"}
            )
            assert foreign.status_code == 403
            assert (
                await client.get("/api/conversations/sessions", params={"offset": -1})
            ).status_code == 422

    asyncio.run(exercise())
    assert len(store.get_conversation(session_id="retry-http", user_id=41)["messages"]) == 1
    assert store.get_conversation(session_id="retry-http", user_id=42)["messages"] == []
