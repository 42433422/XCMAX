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


@pytest.mark.parametrize("holder", ["canonical", "turn"])
def test_turn_lock_uses_shared_canonical_path_across_processes(tmp_path, monkeypatch, holder):
    import hashlib
    import subprocess
    import sys

    from filelock import FileLock

    monkeypatch.setattr(m, "_memory_dir", lambda: tmp_path)
    key, turn = "synthetic", "same-turn"
    digest = hashlib.sha256(turn.encode()).hexdigest()
    path = tmp_path / f"{key}.{digest}.turn.lock"
    turn_lock = m._turn_lock(key, turn)
    canonical = FileLock(
        str(path), timeout=0, thread_local=False, fallback_to_soft=False, preserve_lock_file=True
    )
    assert turn_lock.lock_file == canonical.lock_file
    lease = canonical if holder == "canonical" else turn_lock
    script = """
import sys
from filelock import FileLock, Timeout
options = {'thread_local': False}
if sys.argv[2] == 'canonical':
    options.update(timeout=0, fallback_to_soft=False, preserve_lock_file=True)
try:
    with FileLock(sys.argv[1], **options).acquire(timeout=0):
        pass
except Timeout:
    sys.exit(10)
"""
    contender = "turn" if holder == "canonical" else "canonical"
    with lease.acquire(timeout=0):
        result = subprocess.run(
            [sys.executable, "-c", script, str(path), contender], timeout=10, check=False
        )
        assert result.returncode == 10
    result = subprocess.run(
        [sys.executable, "-c", script, str(path), contender], timeout=10, check=False
    )
    assert result.returncode == 0
