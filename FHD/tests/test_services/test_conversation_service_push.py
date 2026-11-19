"""Real SQLite receipts: atomic turns, replay dedupe, revision fences and push."""

import json
from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db.models import AIConversation, AIConversationSession, User
from app.domain.shared_services.conversation_service import ConversationService


@pytest.fixture
def storage(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'conversation.db'}")
    for model in (User, AIConversationSession, AIConversation):
        model.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as db:
        db.add(User(id=42, username="receipt-owner", password="test"))

    @contextmanager
    def isolated_db():
        with factory() as db:
            yield db

    monkeypatch.setattr("app.domain.shared_services.conversation_service.get_db", isolated_db)
    monkeypatch.setattr("app.application.task_conversation_store.get_db", isolated_db)
    push = Mock()
    monkeypatch.setattr("app.domain.shared_services.conversation_service.notify_user", push)
    yield ConversationService(), factory, push
    engine.dispose()


def test_idempotency_replay_after_more_than_100_messages_does_not_push_twice(storage):
    svc, factory, push = storage
    original = svc.save_message(
        "session", "42", "assistant", "confirmed", idempotency_key="receipt"
    )
    svc.save_turn(
        session_id="session",
        user_id="42",
        messages=[{"role": "assistant", "content": f"later-{i}"} for i in range(105)],
    )
    push.reset_mock()
    assert (
        svc.save_message("session", "42", "assistant", "confirmed", idempotency_key="receipt")
        == original
    )
    push.assert_not_called()
    with pytest.raises(ValueError, match="original content"):
        svc.save_message("session", "42", "assistant", "changed", idempotency_key="receipt")
    with factory() as db:
        assert db.query(AIConversation).count() == 106
        assert db.query(AIConversationSession).one().message_count == 106


def test_commit_then_push_and_push_failure_does_not_undo_receipt(storage):
    svc, factory, push = storage
    svc.save_message("session", "42", "user", "hello")
    push.assert_not_called()
    push.side_effect = OSError("push offline")
    message_id = svc.save_message("session", "42", "assistant", "saved")
    assert push.call_args.kwargs["data"]["message_id"] == str(message_id)
    with factory() as db:
        assert db.get(AIConversation, message_id).content == "saved"


def test_second_insert_failure_rolls_back_whole_turn_and_session_count(storage):
    svc, factory, push = storage

    def fail_assistant(_mapper, _connection, target):
        if target.role == "assistant":
            raise RuntimeError("injected second insert failure")

    event.listen(AIConversation, "before_insert", fail_assistant)
    try:
        with pytest.raises(RuntimeError, match="second insert"):
            svc.save_turn(
                session_id="atomic",
                user_id="42",
                messages=[
                    {"role": "user", "content": "request"},
                    {"role": "assistant", "content": "result"},
                ],
            )
    finally:
        event.remove(AIConversation, "before_insert", fail_assistant)
    with factory() as db:
        assert db.query(AIConversation).count() == 0
        assert db.query(AIConversationSession).count() == 0
    push.assert_not_called()


def test_long_receipt_preserves_valid_metadata_and_full_transcript(storage, monkeypatch):
    from app.application.ai_chat.conversation_history import persist_chat_turn

    svc, factory, _ = storage
    monkeypatch.setattr(
        "app.application.ai_chat.active_conversation.remember_active_conversation",
        lambda *a, **k: None,
    )
    message, reply = "长输入" * 4000, "长回复" * 4000
    ack = persist_chat_turn(
        "42",
        message,
        {"session_id": "long", "local_user_id": 42, "turn_id": "turn-long"},
        {
            "success": True,
            "response": reply,
            "run_id": "run-long",
            "data": {
                "data": {"thinking_steps": "证据" * 3500, "todo": ["步骤" * 100 for _ in range(50)]}
            },
        },
        store=svc,
    )
    assert ack["status"] == "saved"
    with factory() as db:
        rows = db.query(AIConversation).order_by(AIConversation.id).all()
        assert [row.content for row in rows] == [message, reply]
        metadata = json.loads(rows[1].conversation_metadata)
        assert metadata["business_harness"]["turn_id"] == "turn-long"
        assert metadata["summary"]["run_id"] == "run-long"
        assert len(metadata["ui"]["todoSteps"]) == 50
        assert len(rows[1].conversation_metadata) > 12000


@pytest.mark.parametrize(
    "content, expected",
    [
        ("<p>  查询&nbsp;订单 </p>\n <strong>状态</strong>", "查询 订单 状态"),
        ("<" * 100_000, "<" * 48 + "…"),
        ("<p>" + "长" * 60 + "</p>", "长" * 48 + "…"),
    ],
)
def test_user_message_title_keeps_plain_text_and_preserves_message(storage, content, expected):
    svc, factory, _ = storage
    message_id = svc.save_message("title", "42", "user", content)
    with factory() as db:
        assert db.query(AIConversationSession).one().title == expected
        assert db.get(AIConversation, message_id).content == content


def test_cursor_pages_are_complete_owner_scoped_and_revision_fenced(storage):
    from app.application.task_conversation_store import TaskConversationStore
    from app.domain.shared_services.conversation_service import ConversationRevisionError

    svc, _, _ = storage
    ids = svc.save_turn(
        session_id="pages",
        user_id="42",
        messages=[
            {
                "role": "user" if i % 2 == 0 else "assistant",
                "content": str(i),
                "metadata": json.dumps({"summary": {"turn_id": f"turn-{i // 2}"}}),
            }
            for i in range(205)
        ],
    )
    store = TaskConversationStore()
    latest = store.get_history(session_id="pages", user_id=42, limit=50)
    assert [row["id"] for row in latest["messages"]] == ids[-50:]
    assert latest["has_more"]
    assert latest["revision"] == 0
    before = store.get_history(
        session_id="pages", user_id=42, limit=50, before_id=latest["next_before_id"]
    )
    assert [row["id"] for row in before["messages"]] == ids[-100:-50]
    assert [
        row["id"]
        for row in store.iter_conversation_messages(session_id="pages", user_id=42, batch_size=30)
    ] == ids
    assert store.get_history(session_id="pages", user_id=43)["messages"] == []
    assert [
        row["id"]
        for row in store.get_history(session_id="pages", user_id=42, turn_id="turn-2")["messages"]
    ] == ids[4:6]
    assert svc.delete_session("pages", user_id="42")
    with pytest.raises(ConversationRevisionError):
        svc.save_message("pages", "42", "assistant", "late completion", expected_revision=0)
    assert store.get_history(session_id="pages", user_id=42)["messages"] == []


def test_save_only_repair_preserves_original_full_turn_and_rejects_withdrawal(
    storage, monkeypatch, tmp_path
):
    from app.application.ai_chat.conversation_history import retry_stored_chat_turn
    from app.application.ai_chat.dialogue_memory import prepare_chat_turn, settle_chat_turn
    from app.application.task_conversation_store import TaskConversationStore
    from app.domain.shared_services.conversation_service import ConversationRevisionError

    svc, factory, _ = storage
    monkeypatch.setenv("XCAGI_DIALOGUE_MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setattr("app.services.get_conversation_service", lambda: svc)
    context = {
        "local_user_id": 42,
        "tenant_id": 1,
        "conversation_id": "repair",
        "turn_id": "original",
    }
    user, reply = "input" * 2500, "output" * 2500
    prepare_chat_turn(user, context)
    settle_chat_turn(
        user,
        context,
        {
            "success": True,
            "response": reply,
            "run_id": "same-run",
            "history_persistence": {"status": "failed", "revision": 0},
        },
        "completed",
    )
    first = retry_stored_chat_turn(context, "original", 0)
    second = retry_stored_chat_turn(context, "original", 0)
    assert first["saved"] and first["durable"] and second["message_ids"] == first["message_ids"]
    with factory() as db:
        assert [row.content for row in db.query(AIConversation).order_by(AIConversation.id)] == [
            user,
            reply,
        ]
    TaskConversationStore().delete_messages_from(
        session_id="repair", user_id=42, message_id=first["message_ids"][0]
    )
    with pytest.raises((ConversationRevisionError, LookupError)):
        retry_stored_chat_turn(context, "original", 0)
    with factory() as db:
        assert db.query(AIConversation).count() == 0


def test_withdrawal_exposes_new_revision_in_history_and_every_cursor_page(storage):
    from app.application.task_conversation_store import TaskConversationStore

    svc, _, _ = storage
    ids = svc.save_turn(
        session_id="revision",
        user_id="42",
        messages=[
            {"role": "user", "content": "retained"},
            {"role": "user", "content": "withdrawn"},
        ],
    )
    store = TaskConversationStore()
    store.delete_messages_from(session_id="revision", user_id=42, message_id=ids[1])
    page = store.get_history(session_id="revision", user_id=42)
    assert page["revision"] == 1
    assert [row["content"] for row in page["messages"]] == ["retained"]
    assert (
        store.get_conversation(session_id="revision", user_id=42, after_id=0)["session"]["revision"]
        == 1
    )
