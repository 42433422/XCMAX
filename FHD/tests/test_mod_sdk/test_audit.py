"""mod_sdk audit 单测（mock DB）。"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from app.mod_sdk.audit import write_audit_event


@contextmanager
def _fake_db(execute_mock):
    db = MagicMock()
    db.execute = execute_mock
    yield db


def test_write_audit_event_inserts_row():
    execute = MagicMock()

    @contextmanager
    def fake_get_db():
        db = MagicMock()
        db.execute = execute
        yield db

    with patch("app.db.session.get_db", fake_get_db):
        write_audit_event(actor="42", action="mod_test", payload={"k": "v"})
    execute.assert_called_once()
    params = execute.call_args[0][1]
    assert params["actor"] == 42
    assert params["action"] == "mod_test"
    assert '"k"' in params["payload"]


def test_write_audit_event_invalid_actor_still_writes():
    execute = MagicMock()

    @contextmanager
    def fake_get_db():
        db = MagicMock()
        db.execute = execute
        yield db

    with patch("app.db.session.get_db", fake_get_db):
        write_audit_event(actor="not-a-number", action="x", payload=None)
    params = execute.call_args[0][1]
    assert params["actor"] is None


def test_write_audit_event_swallows_db_errors():
    with patch("app.db.session.get_db", side_effect=RuntimeError("no db")):
        write_audit_event(actor=1, action="safe", payload={})
