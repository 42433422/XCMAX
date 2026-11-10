from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request

from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.planner_compat_service import execute_compat_chat, execute_compat_chat_batch
from app.fastapi_routes import xcagi_compat_chat_helpers as stream_helpers
from app.fastapi_routes.xcagi_compat_chat_helpers import (
    XcagiCompatChatBatchBody,
    XcagiCompatChatBody,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _sse_payloads(chunks: list[bytes]) -> list[dict]:
    payloads: list[dict] = []
    for item in b"".join(chunks).decode("utf-8").split("\n\n"):
        if not item.startswith("data: "):
            continue
        payloads.append(json.loads(item[len("data: ") :]))
    return payloads


def _make_request() -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/compat/chat",
            "raw_path": b"/api/compat/chat",
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 80),
            "client": ("testclient", 12345),
            "root_path": "",
        }
    )


@pytest.fixture
def durable_compat_history(tmp_path, monkeypatch, trusted_actor):

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.db.models import AIConversation, AIConversationSession, User
    from app.domain.shared_services.conversation_service import ConversationService

    engine = create_engine(f"sqlite:///{tmp_path / 'history.db'}")
    User.__table__.create(engine)
    AIConversationSession.__table__.create(engine)
    AIConversation.__table__.create(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as session:
        session.add(User(id=2, username="compat-test", password="disabled-fixture", tenant_id=1))
        session.commit()

    @contextmanager
    def db():
        with sessions() as session:
            yield session

    conversation = ConversationService()
    service = AIChatApplicationService.__new__(AIChatApplicationService)
    service._pending_workflows = {}
    monkeypatch.setattr("app.application.get_ai_chat_app_service", lambda: service)
    monkeypatch.setattr("app.services.get_conversation_service", lambda: conversation)
    monkeypatch.setattr("app.domain.shared_services.conversation_service.get_db", db)
    monkeypatch.setattr(
        "app.domain.shared_services.conversation_service.notify_user", lambda **kwargs: None
    )
    actor = trusted_actor(user_id=2, tenant_id=1)
    yield conversation, service, actor
    engine.dispose()


@pytest.mark.asyncio
async def test_compat_history_rejects_body_owner_without_authenticated_actor(
    durable_compat_history, monkeypatch
):
    from app.application import planner_compat_service as compat

    conversation, _, _ = durable_compat_history
    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies.resolve_session_user", lambda req: None
    )
    monkeypatch.setattr(
        compat,
        "_execute_compat_chat_impl",
        AsyncMock(return_value={"success": True, "response": "reply"}),
    )
    await compat.execute_compat_chat(
        _make_request(),
        XcagiCompatChatBody(
            message="查询",
            user_id="2",
            context={"session_id": "history-session", "local_user_id": 2},
        ),
    )
    assert conversation.get_session_messages("history-session") == []


@pytest.mark.asyncio
async def test_anonymous_mainline_cannot_persist_under_body_owner(
    durable_compat_history, monkeypatch
):
    from app.application import planner_compat_service as compat

    conversation, service, _ = durable_compat_history
    reply = {"success": True, "response": "anonymous reply"}

    async def mainline(request, body):
        # Use the same persistence operation as the real mainline finalizer.
        service._persist_chat_turn(body.user_id, body.message, body.context, reply)
        return reply

    monkeypatch.setattr(compat, "_execute_compat_chat_impl", mainline)
    result = await compat.execute_compat_chat(
        _make_request(),
        XcagiCompatChatBody(
            message="hello",
            user_id="2",
            context={
                "session_id": "history-session",
                "local_user_id": 2,
                "actor_id": 2,
                "tenant_id": 1,
            },
        ),
    )
    assert result == reply
    assert conversation.get_session_messages("history-session") == []


@pytest.mark.parametrize(
    "identity", [{}, {"local_user_id": "bad"}, {"actor_id": 0}, {"local_user_id": 2, "actor_id": 3}]
)
def test_history_rejects_missing_or_inconsistent_owner(identity, durable_compat_history):
    conversation, service, _ = durable_compat_history
    service._persist_chat_turn(
        "2",
        "hello",
        {"session_id": "history-session", **identity},
        {"success": True, "response": "reply"},
    )
    assert conversation.get_session_messages("history-session") == []
