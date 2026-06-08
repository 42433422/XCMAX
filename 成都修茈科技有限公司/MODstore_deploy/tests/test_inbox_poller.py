"""收件解析与审批入口。"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

import pytest

import modstore_server.models as models
from modstore_server.approval_dispatcher import handle_incoming_approval_email


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    models._engine = None
    models._SessionFactory = None
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "inbox.sqlite"))
    models.init_db()
    yield tmp_path
    models._engine = None
    models._SessionFactory = None


def test_handle_incoming_wrong_from(monkeypatch):
    monkeypatch.setenv("MODSTORE_APPROVAL_AUTHORIZED_FROM", "owner@qq.com")
    r = handle_incoming_approval_email(from_addr="other@qq.com", body="ABCDEF", message_id="<x>")
    assert r.get("skip") is True


def test_handle_incoming_no_token(monkeypatch):
    monkeypatch.setenv("MODSTORE_APPROVAL_AUTHORIZED_FROM", "owner@qq.com")
    r = handle_incoming_approval_email(
        from_addr="owner@qq.com", body="please deploy thanks", message_id="<x>"
    )
    assert r.get("skip") is True


def test_handle_incoming_dispatches_on_token_hash(fresh_db, monkeypatch):
    monkeypatch.setenv("MODSTORE_APPROVAL_AUTHORIZED_FROM", "owner@qq.com")
    plain = "A1B2C3"
    th = hashlib.sha256(plain.encode("utf-8")).hexdigest()
    exp = datetime.utcnow() + timedelta(hours=5)
    sf = models.get_session_factory()
    with sf() as s:
        tok = models.OpsApprovalToken(
            token_hash=th,
            kind="reject_all",
            payload_json="{}",
            authorized_email="owner@qq.com",
            expires_at=exp,
        )
        s.add(tok)
        s.commit()
        expected_id = int(tok.id)

    seen: list[int] = []

    def cap(token_id: int, *, message_id: str = "") -> dict:
        seen.append(int(token_id))
        return {"ok": True, "rejected": 0}

    monkeypatch.setattr("modstore_server.approval_dispatcher.handle_token_row", cap)

    r = handle_incoming_approval_email(
        from_addr="owner@qq.com",
        body=f"approve\n{plain}\nthanks",
        message_id="<mid@x>",
    )
    assert r.get("ok") is True
    assert seen == [expected_id]
