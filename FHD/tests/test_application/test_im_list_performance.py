"""The conversation list stays complete while explicit pages have constant SQL cost."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.application.im_app_service import ImApplicationService
from app.db.models.im import ImConversation, ImConversationMember, ImMessage
from app.db.models.user import User


@pytest.fixture
def conversations(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'im.sqlite'}")
    for model in (User, ImConversation, ImConversationMember, ImMessage):
        model.__table__.create(engine)
    with Session(engine) as db:
        db.add(User(id=1, username="me", password="unused"))
        for number in range(1, 134):
            username = "enterprise-cs" if number == 130 else f"emp:worker-{number}"
            db.add(User(id=number + 1, username=username, password="unused", display_name=""))
            db.add(
                ImConversation(
                    id=number,
                    title=f"Group {number}",
                    is_direct=number != 129,
                    last_message_at=datetime(2026, 1, 1) if number > 3 else None,
                )
            )
            db.add(
                ImConversationMember(
                    conversation_id=number,
                    user_id=1 if number <= 131 else 999,
                    last_read_message_id=number * 10,
                )
            )
            db.add(ImConversationMember(conversation_id=number, user_id=number + 1))
            for offset, sender in ((0, number + 1), (1, 1), (2, number + 1)):
                db.add(
                    ImMessage(
                        id=number * 10 + offset,
                        conversation_id=number,
                        sender_user_id=sender,
                        body=f"{number}:" + "正文" * 100,
                    )
                )
        db.commit()
        yield db
    engine.dispose()


def test_explicit_pages_bound_sql_and_traverse_legacy_list(conversations):
    db = conversations
    service = ImApplicationService(db)
    legacy = service.list_conversations(1)
    assert len(legacy) == 131
    assert [item["id"] for item in legacy] == list(range(131, 0, -1))
    assert all(item["unread_count"] == 1 for item in legacy)
    assert all(len(item["last_message_preview"]) == 120 for item in legacy)
    assert next(item for item in legacy if item["id"] == 129)["title"] == "Group 129"
    assert next(item for item in legacy if item["id"] == 128)["employee_id"] == "worker-128"
    queries = []

    def count_sql(_conn, _cursor, statement, _parameters, _context, _many):
        queries.append(statement)

    event.listen(db.bind, "before_cursor_execute", count_sql)
    try:
        accumulated, cursor = [], None
        while True:
            queries.clear()
            page, cursor = service.list_conversations_page(1, limit=50, cursor=cursor)
            assert len(queries) <= 5
            assert 0 < len(page) <= 50
            accumulated.extend(page)
            if cursor is None:
                break
        assert accumulated == legacy
    finally:
        event.remove(db.bind, "before_cursor_execute", count_sql)


def test_cs_filter_applies_before_page_limit_and_null_cursor(conversations):
    service = ImApplicationService(conversations)
    expected = service.list_conversations(1, include_enterprise_dedicated_cs=False)
    assert len(expected) == 130
    assert all(not item.get("is_enterprise_dedicated_cs") for item in expected)
    first, cursor = service.list_conversations_page(
        1,
        include_enterprise_dedicated_cs=False,
        limit=129,
    )
    assert len(first) == 129 and cursor
    last, cursor = service.list_conversations_page(
        1,
        include_enterprise_dedicated_cs=False,
        limit=129,
        cursor=cursor,
    )
    assert first + last == expected and cursor is None
    assert service.list_conversations(4000) == []


@pytest.mark.parametrize("cursor", ["bad", "e30", "WzEsMl0", "W251bGwsMF0", "a" * 257])
def test_invalid_cursor_is_rejected(conversations, cursor):
    with pytest.raises(ValueError, match="游标"):
        ImApplicationService(conversations).list_conversations_page(1, limit=10, cursor=cursor)


def test_http_contract_keeps_legacy_list_and_exposes_next_cursor(conversations, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.fastapi_routes import im_routes
    from app.infrastructure.auth.dependencies import CurrentUser, require_identified_user

    app = FastAPI()
    app.get("/api/im/conversations")(im_routes.im_list_conversations)
    app.dependency_overrides[require_identified_user] = lambda: CurrentUser(1)
    monkeypatch.setattr(im_routes, "_ensure_schema", lambda: None)
    monkeypatch.setattr(im_routes, "HostSessionLocal", lambda: Session(conversations.bind))
    monkeypatch.setattr(im_routes, "_include_enterprise_dedicated_cs", lambda *_args: True)
    with TestClient(app) as client:
        legacy = client.get("/api/im/conversations").json()
        assert len(legacy["conversations"]) == 131 and legacy["next_cursor"] is None
        first = client.get("/api/im/conversations", params={"limit": 50}).json()
        assert len(first["conversations"]) == 50 and first["next_cursor"]
        second = client.get(
            "/api/im/conversations",
            params={
                "limit": 50,
                "cursor": first["next_cursor"],
            },
        ).json()
        assert first["conversations"] + second["conversations"] == legacy["conversations"][:100]
        assert client.get("/api/im/conversations", params={"limit": 0}).status_code == 422
        assert client.get("/api/im/conversations", params={"cursor": "invalid"}).status_code == 400
