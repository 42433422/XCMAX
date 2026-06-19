"""IM 消息漫游 + xcmax sync 协议扩展。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.application.im_app_service import (
    ENTERPRISE_DEDICATED_CS_DISPLAY_NAME,
    ENTERPRISE_DEDICATED_CS_USERNAME,
    ImApplicationService,
)
from app.db.models.im import ImConversation, ImConversationMember, ImMessage
from app.db.models.user import User
from app.services.xcmax_sync_service import (
    _apply_im_message,
    _apply_im_read_state,
    apply_inbox,
    record_change,
    utc_now_ms,
)


@pytest.fixture()
def im_db(tmp_path, monkeypatch: pytest.MonkeyPatch):
    sync_db = tmp_path / "xcmax_sync.db"
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.db.xcmax_sync._db_path", None)

    db_file = tmp_path / "im_sync_test.db"
    engine = create_engine(f"sqlite:///{db_file}")
    User.__table__.create(engine, checkfirst=True)
    ImConversation.__table__.create(engine, checkfirst=True)
    ImConversationMember.__table__.create(engine, checkfirst=True)
    ImMessage.__table__.create(engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    session = Session()
    for uid, name in ((1, "alice"), (2, "bob")):
        session.add(
            User(
                id=uid,
                username=name,
                password="test",
                display_name=name,
                is_active=True,
            )
        )
    session.commit()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _reset_sync_path(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.db.xcmax_sync._db_path", None)


def test_record_change_on_send_message(im_db, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.db.get_db", lambda: _session_ctx(im_db))
    svc = ImApplicationService(im_db)
    conv = svc.get_or_create_direct(1, 2)
    result = svc.send_message(conv["id"], 1, "sync hello")
    from app.db.xcmax_sync import SyncDb

    changes = SyncDb().get_changes(since_cursor=0, limit=10)
    im_rows = [c for c in changes if c.get("entity_type") == "im_message"]
    assert im_rows, "send_message 应写入 im_message 变更"
    payload = im_rows[-1]["payload"]
    assert payload.get("conversation_id") == conv["id"]
    assert payload.get("body") == "sync hello"
    assert int((payload.get("meta") or {}).get("updated_at_ms") or 0) > 0
    assert result.get("updated_at_ms") == int((payload.get("meta") or {}).get("updated_at_ms") or 0)


def test_record_change_on_mark_read(im_db, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.db.get_db", lambda: _session_ctx(im_db))
    svc = ImApplicationService(im_db)
    conv = svc.get_or_create_direct(1, 2)
    sent = svc.send_message(conv["id"], 1, "read me")
    msg_id = sent["message"]["id"]
    result = svc.mark_read(conv["id"], 2, msg_id)
    from app.db.xcmax_sync import SyncDb

    changes = SyncDb().get_changes(since_cursor=0, limit=20)
    read_rows = [c for c in changes if c.get("entity_type") == "im_read_state"]
    assert read_rows
    payload = read_rows[-1]["payload"]
    assert payload.get("conversation_id") == conv["id"]
    assert payload.get("user_id") == 2
    assert payload.get("last_read_message_id") == msg_id
    assert int((payload.get("meta") or {}).get("updated_at_ms") or 0) > 0
    assert result["last_read_message_id"] == msg_id


def test_list_contacts_includes_enterprise_dedicated_cs(im_db):
    svc = ImApplicationService(im_db)
    contacts = svc.list_contacts(1)

    cs = next((c for c in contacts if c.get("is_enterprise_dedicated_cs")), None)
    assert cs is not None
    assert cs["display_name"] == ENTERPRISE_DEDICATED_CS_DISPLAY_NAME
    assert cs["username"] == ENTERPRISE_DEDICATED_CS_USERNAME

    row = im_db.execute(
        select(User).where(User.username == ENTERPRISE_DEDICATED_CS_USERNAME)
    ).scalar_one()
    assert row.is_active is True
    assert row.role == "support"


def test_list_contacts_can_exclude_enterprise_dedicated_cs_for_admin_side(im_db):
    svc = ImApplicationService(im_db)
    svc.list_contacts(1)

    contacts = svc.list_contacts(1, include_enterprise_dedicated_cs=False)

    assert not any(c.get("is_enterprise_dedicated_cs") for c in contacts)
    assert not any(c.get("username") == ENTERPRISE_DEDICATED_CS_USERNAME for c in contacts)


def test_direct_conversation_with_enterprise_cs_is_pinned(im_db):
    svc = ImApplicationService(im_db)
    cs = next(c for c in svc.list_contacts(1) if c.get("is_enterprise_dedicated_cs"))
    conv = svc.get_or_create_direct(1, int(cs["id"]))

    conversations = svc.list_conversations(1)
    pinned = next(c for c in conversations if c["id"] == conv["id"])
    assert pinned["title"] == ENTERPRISE_DEDICATED_CS_DISPLAY_NAME
    assert pinned["is_enterprise_dedicated_cs"] is True


def test_list_conversations_can_exclude_enterprise_dedicated_cs_for_admin_side(im_db):
    svc = ImApplicationService(im_db)
    cs = next(c for c in svc.list_contacts(1) if c.get("is_enterprise_dedicated_cs"))
    conv = svc.get_or_create_direct(1, int(cs["id"]))

    conversations = svc.list_conversations(1, include_enterprise_dedicated_cs=False)

    assert not any(c["id"] == conv["id"] for c in conversations)
    assert not any(c.get("is_enterprise_dedicated_cs") for c in conversations)


def test_apply_im_message_insert(im_db, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.db.get_db", lambda: _session_ctx(im_db))
    conv = ImApplicationService(im_db).get_or_create_direct(1, 2)
    updated_at_ms = utc_now_ms()
    _apply_im_message(
        {
            "entity_type": "im_message",
            "entity_id": "9001",
            "operation": "insert",
            "payload": {
                "id": 9001,
                "conversation_id": conv["id"],
                "sender_user_id": 1,
                "body": "from remote",
                "meta": {"updated_at_ms": updated_at_ms},
            },
        }
    )
    row = im_db.execute(select(ImMessage).where(ImMessage.id == 9001)).scalar_one_or_none()
    assert row is not None
    assert row.body == "from remote"


def test_apply_im_read_state_lww(im_db, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.db.get_db", lambda: _session_ctx(im_db))
    svc = ImApplicationService(im_db)
    conv = svc.get_or_create_direct(1, 2)
    sent = svc.send_message(conv["id"], 1, "lww")
    msg_id = sent["message"]["id"]
    member = im_db.execute(
        select(ImConversationMember).where(
            ImConversationMember.conversation_id == conv["id"],
            ImConversationMember.user_id == 2,
        )
    ).scalar_one()
    member.last_read_message_id = 0
    im_db.commit()

    older_ms = utc_now_ms() - 10_000
    _apply_im_read_state(
        {
            "entity_type": "im_read_state",
            "entity_id": f"{conv['id']}:2",
            "operation": "update",
            "payload": {
                "conversation_id": conv["id"],
                "user_id": 2,
                "last_read_message_id": msg_id,
                "meta": {"updated_at_ms": older_ms},
            },
        }
    )
    im_db.expire_all()
    member = im_db.execute(
        select(ImConversationMember).where(
            ImConversationMember.conversation_id == conv["id"],
            ImConversationMember.user_id == 2,
        )
    ).scalar_one()
    assert int(member.last_read_message_id or 0) == msg_id

    newer_ms = utc_now_ms()
    _apply_im_read_state(
        {
            "entity_type": "im_read_state",
            "entity_id": f"{conv['id']}:2",
            "operation": "update",
            "payload": {
                "conversation_id": conv["id"],
                "user_id": 2,
                "last_read_message_id": max(0, msg_id - 1),
                "meta": {"updated_at_ms": newer_ms},
            },
        }
    )
    im_db.expire_all()
    member = im_db.execute(
        select(ImConversationMember).where(
            ImConversationMember.conversation_id == conv["id"],
            ImConversationMember.user_id == 2,
        )
    ).scalar_one()
    assert int(member.last_read_message_id or 0) == msg_id


def test_apply_inbox_registers_im_appliers(im_db, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.db.get_db", lambda: _session_ctx(im_db))
    conv = ImApplicationService(im_db).get_or_create_direct(1, 2)
    from app.db.xcmax_sync import SyncDb

    sync_db = SyncDb()
    change_id = record_change(
        "im_message",
        "9100",
        "insert",
        {
            "id": 9100,
            "conversation_id": conv["id"],
            "sender_user_id": 1,
            "body": "inbox path",
            "meta": {"updated_at_ms": utc_now_ms()},
        },
    )
    assert change_id > 0
    sync_db.enqueue_inbox(
        [
            {
                "entity_type": "im_message",
                "entity_id": "9100",
                "operation": "insert",
                "payload": {
                    "id": 9100,
                    "conversation_id": conv["id"],
                    "sender_user_id": 1,
                    "body": "inbox path",
                    "meta": {"updated_at_ms": utc_now_ms()},
                },
            }
        ]
    )
    result = apply_inbox(limit=10)
    assert result.get("applied", 0) >= 1
    row = im_db.execute(select(ImMessage).where(ImMessage.id == 9100)).scalar_one_or_none()
    assert row is not None
    assert row.body == "inbox path"


class _session_ctx:
    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *args):
        return False
