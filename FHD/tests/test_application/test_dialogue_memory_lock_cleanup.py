from contextlib import nullcontext
from unittest.mock import Mock

import pytest

from app.application.ai_chat import dialogue_memory as m


@pytest.fixture
def setup_turn(monkeypatch):
    lock = Mock(lock_file="synthetic.turn.lock")
    data = {"turns": []}
    monkeypatch.setattr(m, "conversation_key", lambda context: "synthetic")
    monkeypatch.setattr(m, "_lock", lambda key: nullcontext())
    monkeypatch.setattr(m, "_read", lambda key: data)
    monkeypatch.setattr(m, "_user_turn", lambda data, turn: None)
    monkeypatch.setattr(m, "_assistant_for", lambda data, turn: None)
    monkeypatch.setattr(m, "_turn_running", lambda key, turn: False)
    monkeypatch.setattr(m, "_close_abandoned", lambda key, data: None)
    monkeypatch.setattr(m, "_turn_lock", lambda key, turn: lock)
    monkeypatch.setattr(m, "_append_user", Mock())
    monkeypatch.setattr(m, "_write", Mock())
    monkeypatch.setattr(m, "_INFLIGHT", {})
    return lock


@pytest.mark.parametrize("stage", ["_append_user", "_write"])
@pytest.mark.parametrize("error_type", [OSError, ValueError, KeyboardInterrupt, SystemExit])
def test_failure_releases_lock_and_preserves_exception(setup_turn, monkeypatch, stage, error_type):
    error = error_type("synthetic failure")
    monkeypatch.setattr(m, stage, Mock(side_effect=error))
    with pytest.raises(error_type) as raised:
        m.prepare_chat_turn("message", {"turn_id": "turn"})
    assert raised.value is error
    setup_turn.acquire.assert_called_once_with(timeout=0)
    setup_turn.release.assert_called_once_with()
    assert m._INFLIGHT == {}


def test_success_retains_lock_until_settlement(setup_turn):
    assert m.prepare_chat_turn("message", {"turn_id": "turn"}) is None
    setup_turn.acquire.assert_called_once_with(timeout=0)
    setup_turn.release.assert_not_called()
    assert {"synthetic.turn.lock": setup_turn} == m._INFLIGHT
    m._write.assert_called_once()


def test_without_turn_lock_failure_still_propagates(setup_turn, monkeypatch):
    error = OSError("synthetic failure")
    monkeypatch.setattr(m, "_write", Mock(side_effect=error))
    with pytest.raises(OSError) as raised:
        m.prepare_chat_turn("message", {})
    assert raised.value is error
    setup_turn.acquire.assert_not_called()
    setup_turn.release.assert_not_called()
    assert m._INFLIGHT == {}
