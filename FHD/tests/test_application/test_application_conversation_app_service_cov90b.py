"""Real-behavior tests for app.application.conversation_app_service.

Strategy mirrors the ai_circle_service cov90 suite: drive the real
``ConversationApplicationService`` methods against an in-memory SQLite engine
bound to the real ORM models. The function-internal context manager ``get_db``
is patched at the use-site (``conversation_app_service.get_db``) to yield a real
``Session``, so every query / add / commit / delete executes for real.

Notes on the in-memory engine:
* ``app.db`` registers a global ``Engine.connect`` listener that turns
  ``PRAGMA foreign_keys=ON``. We append a per-engine listener that turns it
  back OFF so we don't need to materialize the unrelated ``users`` table that
  ``AIConversationSession.user_id`` references.
* The service never sets ``created_at`` itself, so we seed parent sessions
  directly when a timestamp matters.

Several methods of the service are *broken at runtime* against the current ORM
schema; those are pinned with assertions documenting the real behavior (see
the module-level ``suspected_bugs`` returned by the harness):

* ``save_message`` accepts ``metadata=`` but the column is named
  ``conversation_metadata`` — the value is silently dropped and ``msg.metadata``
  returns the SQLAlchemy ``MetaData`` object, not the saved string.
* ``create_session`` / ``get_or_create_session`` pass ``context={}`` to a model
  that has no ``context`` column -> ``TypeError``.
* ``get_sessions`` reads ``s.updated_at`` which does not exist on
  ``AIConversationSession`` -> ``AttributeError``.

Tests are offline, deterministic and fast.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.orm import sessionmaker

import app.db.models  # noqa: F401  ensure all mappers are registered
from app.application import conversation_app_service as svc_mod
from app.db.base import Base
from app.db.models.ai import AIConversation, AIConversationSession


@pytest.fixture()
def db_factory(monkeypatch):
    """In-memory SQLite + real models; patch ``get_db`` at the service use-site.

    Returns a ``Session`` factory so a test can open its own session to seed /
    assert rows independently of the service's own transactions.
    """
    engine = create_engine("sqlite:///:memory:", future=True)

    @event.listens_for(engine, "connect")
    def _disable_fk(dbapi_conn, _rec):  # pragma: no cover - trivial pragma
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=OFF")
        cur.close()

    Base.metadata.create_all(
        bind=engine,
        tables=[
            AIConversationSession.__table__,
            AIConversation.__table__,
        ],
    )
    SessionLocal = sessionmaker(bind=engine, future=True)

    @contextmanager
    def fake_get_db():
        db = SessionLocal()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    monkeypatch.setattr(svc_mod, "get_db", fake_get_db)
    return SessionLocal


@pytest.fixture()
def service():
    return svc_mod.ConversationApplicationService()


def _seed_session(SessionLocal, session_id="sess-A", user_id=None, created_at=None):
    db = SessionLocal()
    try:
        db.add(
            AIConversationSession(
                session_id=session_id,
                user_id=user_id,
                created_at=created_at,
            )
        )
        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# get_conversation_app_service singleton (lines 145-149)
# --------------------------------------------------------------------------- #
def test_get_conversation_app_service_returns_singleton():
    a = svc_mod.get_conversation_app_service()
    b = svc_mod.get_conversation_app_service()
    assert isinstance(a, svc_mod.ConversationApplicationService)
    assert a is b  # module-level cache reused, not re-instantiated


# --------------------------------------------------------------------------- #
# save_message — success path + neuro notify (lines 31-48, 51)
# --------------------------------------------------------------------------- #
def test_save_message_persists_row_and_notifies(db_factory, service, monkeypatch):
    _seed_session(db_factory, "sess-save")
    notify = MagicMock()
    monkeypatch.setattr(
        "app.neuro_bus.application_neuro_bridge.neuro_notify_conversation_message_saved",
        notify,
    )

    mid = service.save_message(
        "sess-save", "u-9", "user", "hello world", intent="greet", metadata="m"
    )

    assert isinstance(mid, int)
    assert mid > 0

    # The row really landed in the DB with the expected scalar columns.
    db = db_factory()
    try:
        row = db.get(AIConversation, mid)
        assert row is not None
        assert row.session_id == "sess-save"
        assert row.user_id == "u-9"
        assert row.role == "user"
        assert row.content == "hello world"
        assert row.intent == "greet"
        # BUG: metadata= kwarg is silently dropped; the real column stays None.
        assert row.conversation_metadata is None
    finally:
        db.close()

    # neuro bridge invoked with (session_id, user_id, role, intent)
    notify.assert_called_once_with("sess-save", "u-9", "user", "greet")


def test_save_message_metadata_kwarg_is_not_persisted_as_content(db_factory, service, monkeypatch):
    """`msg.metadata` resolves to the SQLAlchemy MetaData object, not our string."""
    _seed_session(db_factory, "sess-md")
    monkeypatch.setattr(
        "app.neuro_bus.application_neuro_bridge.neuro_notify_conversation_message_saved",
        MagicMock(),
    )
    mid = service.save_message("sess-md", "u1", "user", "x", metadata="should-vanish")

    db = db_factory()
    try:
        row = db.get(AIConversation, mid)
        # The reserved declarative attribute shadows any "metadata" column.
        assert isinstance(row.metadata, MetaData)
        assert row.conversation_metadata is None
    finally:
        db.close()


def test_save_message_defaults_intent_and_metadata_empty(db_factory, service, monkeypatch):
    _seed_session(db_factory, "sess-def")
    monkeypatch.setattr(
        "app.neuro_bus.application_neuro_bridge.neuro_notify_conversation_message_saved",
        MagicMock(),
    )
    mid = service.save_message("sess-def", "u1", "assistant", "reply")
    db = db_factory()
    try:
        row = db.get(AIConversation, mid)
        assert row.role == "assistant"
        assert row.content == "reply"
        assert row.intent == ""  # default kwarg
    finally:
        db.close()


def test_save_message_swallows_recoverable_neuro_error(db_factory, service, monkeypatch):
    """except RECOVERABLE_ERRORS branch (lines 49-50): notify failure must not
    abort the save — the message id is still returned and the row persists."""
    _seed_session(db_factory, "sess-err")

    def _boom(*_a, **_k):
        raise RuntimeError("neuro down")  # RuntimeError is in RECOVERABLE_ERRORS

    monkeypatch.setattr(
        "app.neuro_bus.application_neuro_bridge.neuro_notify_conversation_message_saved",
        _boom,
    )

    mid = service.save_message("sess-err", "u1", "user", "still saved", intent="i")
    assert isinstance(mid, int) and mid > 0

    db = db_factory()
    try:
        row = db.get(AIConversation, mid)
        assert row is not None
        assert row.content == "still saved"
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# get_session_messages (lines 53-76)
# --------------------------------------------------------------------------- #
def test_get_session_messages_returns_tuples(db_factory, service, monkeypatch):
    _seed_session(db_factory, "sess-list")
    monkeypatch.setattr(
        "app.neuro_bus.application_neuro_bridge.neuro_notify_conversation_message_saved",
        MagicMock(),
    )
    id1 = service.save_message("sess-list", "u1", "user", "first", intent="a")
    id2 = service.save_message("sess-list", "u1", "assistant", "second", intent="b")

    msgs = service.get_session_messages("sess-list")
    assert isinstance(msgs, list)
    assert len(msgs) == 2

    # Each tuple is (id, role, content, intent, metadata, created_at_iso|None).
    by_id = {row[0]: row for row in msgs}
    assert set(by_id) == {id1, id2}
    assert by_id[id1][1:4] == ("user", "first", "a")
    assert by_id[id2][1:4] == ("assistant", "second", "b")
    # created_at is None (service never sets it) -> last tuple element is None.
    assert by_id[id1][5] is None
    # metadata element resolves to the MetaData object, not a stored string.
    assert isinstance(by_id[id1][4], MetaData)


def test_get_session_messages_respects_limit(db_factory, service, monkeypatch):
    _seed_session(db_factory, "sess-lim")
    monkeypatch.setattr(
        "app.neuro_bus.application_neuro_bridge.neuro_notify_conversation_message_saved",
        MagicMock(),
    )
    for i in range(4):
        service.save_message("sess-lim", "u1", "user", f"m{i}")

    limited = service.get_session_messages("sess-lim", limit=2)
    assert len(limited) == 2


def test_get_session_messages_includes_created_at_iso(db_factory, service):
    """When created_at is present on the message, it is serialized via isoformat."""
    # Seed a message row directly with a concrete created_at.
    db = db_factory()
    try:
        db.add(AIConversationSession(session_id="sess-iso", user_id=None))
        db.add(
            AIConversation(
                session_id="sess-iso",
                user_id="u1",
                role="user",
                content="hi",
                intent="x",
                created_at=datetime(2024, 5, 6, 7, 8, 9),
            )
        )
        db.commit()
    finally:
        db.close()

    msgs = service.get_session_messages("sess-iso")
    assert len(msgs) == 1
    assert msgs[0][5] == "2024-05-06T07:08:09"


def test_get_session_messages_empty_for_unknown_session(db_factory, service):
    assert service.get_session_messages("does-not-exist") == []


# --------------------------------------------------------------------------- #
# create_session — broken: passes context={} (lines 78-84)
# --------------------------------------------------------------------------- #
def test_create_session_raises_typeerror_on_context_kwarg(db_factory, service):
    with pytest.raises(TypeError) as exc:
        service.create_session("u-1")
    assert "context" in str(exc.value)


# --------------------------------------------------------------------------- #
# get_or_create_session (lines 86-102)
# --------------------------------------------------------------------------- #
def test_get_or_create_session_returns_existing(db_factory, service):
    # Seed an existing session for user_id 5 (Integer column).
    _seed_session(db_factory, "existing-sess", user_id=5, created_at=datetime(2024, 1, 1))
    sid = service.get_or_create_session(5)
    assert sid == "existing-sess"


def test_get_or_create_session_creates_when_missing_raises_context_bug(db_factory, service):
    """No existing row for this user -> falls into the create branch which is
    broken by the bogus context={} kwarg, raising TypeError."""
    with pytest.raises(TypeError) as exc:
        service.get_or_create_session(999)
    assert "context" in str(exc.value)


# --------------------------------------------------------------------------- #
# get_sessions — broken: reads s.updated_at (lines 104-122)
# --------------------------------------------------------------------------- #
def test_get_sessions_raises_attributeerror_on_updated_at(db_factory, service):
    _seed_session(db_factory, "sess-gs", user_id=7, created_at=datetime(2024, 2, 3))
    with pytest.raises(AttributeError) as exc:
        service.get_sessions(7)
    assert "updated_at" in str(exc.value)


def test_get_sessions_empty_user_returns_empty_list(db_factory, service):
    """No matching sessions -> the list comprehension never touches updated_at,
    so the broken attribute is not hit and an empty list is returned."""
    assert service.get_sessions(123456) == []


# --------------------------------------------------------------------------- #
# delete_session (lines 124-139)
# --------------------------------------------------------------------------- #
def test_delete_session_removes_session_and_messages(db_factory, service, monkeypatch):
    _seed_session(db_factory, "sess-del")
    monkeypatch.setattr(
        "app.neuro_bus.application_neuro_bridge.neuro_notify_conversation_message_saved",
        MagicMock(),
    )
    service.save_message("sess-del", "u1", "user", "bye")

    assert service.delete_session("sess-del") is True

    db = db_factory()
    try:
        assert (
            db.query(AIConversationSession)
            .filter(AIConversationSession.session_id == "sess-del")
            .first()
            is None
        )
        assert db.query(AIConversation).filter(AIConversation.session_id == "sess-del").count() == 0
    finally:
        db.close()


def test_delete_session_returns_false_when_missing(db_factory, service):
    assert service.delete_session("nope-not-here") is False
