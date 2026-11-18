from contextlib import nullcontext
from unittest.mock import Mock

import pytest

from app.application.ai_chat import dialogue_memory as m


@pytest.fixture
def turn_lock(monkeypatch):
    lease = Mock()
    data = {"turns": []}
    monkeypatch.setattr(m, "conversation_key", lambda context: "synthetic")
    monkeypatch.setattr(m, "_lock", lambda key: nullcontext())
    monkeypatch.setattr(m, "bind_chat_turn_context", lambda text, context: None)
    monkeypatch.setattr(m, "_read", lambda key, context: data)
    monkeypatch.setattr(m, "_user_turn", lambda data, turn: None)
    monkeypatch.setattr(m, "_assistant_for", lambda data, turn: None)
    monkeypatch.setattr(m, "_turn_is_live", lambda key, turn: False)
    monkeypatch.setattr(m, "_close_abandoned", lambda key, data: None)
    monkeypatch.setattr(m, "_turn_lock", lambda key, turn: lease)
    monkeypatch.setattr(m, "_append_user", Mock())
    monkeypatch.setattr(m, "_write", Mock())
    monkeypatch.setattr(m, "_INFLIGHT", {})
    return lease


def context():
    return {"turn_id": "turn", m._INPUT_FINGERPRINT_KEY: "synthetic"}


@pytest.mark.parametrize("error_type", [OSError, ValueError, KeyboardInterrupt, SystemExit])
def test_failed_write_releases_registered_lease_and_preserves_exception(
    turn_lock, monkeypatch, error_type
):
    error = error_type("synthetic failure")
    monkeypatch.setattr(m, "_write", Mock(side_effect=error))
    with pytest.raises(error_type) as raised:
        m.prepare_chat_turn("message", context())
    assert raised.value is error
    turn_lock.acquire.assert_called_once_with(timeout=0)
    turn_lock.release.assert_called_once_with()
    assert m._INFLIGHT == {}


def test_success_retains_registered_lease_until_settlement(turn_lock):
    assert m.prepare_chat_turn("message", context()) is None
    turn_lock.acquire.assert_called_once_with(timeout=0)
    turn_lock.release.assert_not_called()
    assert {("synthetic", "turn"): turn_lock} == m._INFLIGHT
    m._write.assert_called_once()
