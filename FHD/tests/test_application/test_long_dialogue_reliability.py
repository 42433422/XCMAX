"""A long conversation keeps confirmed facts and the same active id."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.application.ai_chat.active_conversation import (
    _key,
    active_conversation_for,
    remember_active_conversation,
)
from app.application.ai_chat.dialogue_memory import enrich_model_messages
from app.application.group_chat.storage import GroupChatRepository


@pytest.fixture
def memory_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dialogue_db) -> Path:
    monkeypatch.setenv("XCAGI_DIALOGUE_MEMORY_DIR", str(tmp_path))
    return tmp_path


def _ctx(conversation_id: str, turn: str, **extra: object) -> dict[str, object]:
    return {
        "local_user_id": 1,
        "tenant_id": 1,
        "conversation_id": conversation_id,
        "turn_id": turn,
        **extra,
    }


def test_restart_state_points_at_the_previous_conversation(memory_dir: Path) -> None:
    from app.application.task_conversation_store import task_conversation_store

    for session_id in ("conv-kept", "other"):
        task_conversation_store.prepare_revision(session_id=session_id, user_id=1)
    remember_active_conversation(_ctx("conv-kept", "9"), conversation_id="conv-kept")
    assert active_conversation_for(1, tenant_id="1") == "conv-kept"
    remember_active_conversation(_ctx("other", "1", tenant_id=2), conversation_id="other")
    assert active_conversation_for(1, tenant_id="1") == "conv-kept"
    assert active_conversation_for(1, tenant_id="2") == "other"
    assert active_conversation_for(1, tenant_id="") == ""


@pytest.mark.parametrize("configured_key", [False, True])
def test_active_pointer_is_encrypted_and_reopens_in_a_fresh_process(
    memory_dir, monkeypatch, configured_key
):
    from app.application.task_conversation_store import task_conversation_store

    monkeypatch.delenv("XCAGI_SECRET_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    if configured_key:
        monkeypatch.setenv("SECRET_KEY", "test-persistent-server-key")
    task_conversation_store.prepare_revision(session_id="private-conversation", user_id=1)
    remember_active_conversation(_ctx("private-conversation", "first"))
    pointer = memory_dir / f"{_key(1, '1', '')}-active.json"
    stored = pointer.read_text(encoding="utf-8")
    assert stored.startswith("enc:v1:") and "private-conversation" not in stored
    key_path = memory_dir / GroupChatRepository._SECRET_FILE_NAME
    assert key_path.exists() is not configured_key
    if not configured_key and os.name != "nt":
        assert key_path.stat().st_mode & 0o777 == 0o600
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json; from app.application.ai_chat.active_conversation import "
            "active_conversation_for as read; "
            "print(json.dumps([read(1, tenant_id='1'), read(2, tenant_id='1'), "
            "read(1, tenant_id='2')]))",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert json.loads(result.stdout) == ["private-conversation", "", ""]
    assert pointer.read_text(encoding="utf-8") == stored


@pytest.mark.parametrize("damage", ["missing_key", "empty_key", "invalid_ciphertext", "wrong_key"])
def test_encrypted_pointer_read_never_creates_a_key_or_falls_back_to_plaintext(
    memory_dir, monkeypatch, damage
):
    from app.application.task_conversation_store import task_conversation_store

    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("XCAGI_SECRET_KEY", raising=False)
    task_conversation_store.prepare_revision(session_id="protected", user_id=1)
    task_conversation_store.prepare_revision(session_id="replacement", user_id=1)
    task_conversation_store.prepare_revision(session_id="other-owner", user_id=2)
    remember_active_conversation(_ctx("protected", "first"))
    pointer = memory_dir / f"{_key(1, '1', '')}-active.json"
    key_path = memory_dir / GroupChatRepository._SECRET_FILE_NAME
    if damage == "missing_key":
        key_path.unlink()
    elif damage == "empty_key":
        key_path.write_text("", encoding="utf-8")
    elif damage == "wrong_key":
        key_path.write_text("incorrect-key", encoding="utf-8")
    else:
        pointer.write_text(
            'enc:v1:{"owner":"1","tenant_id":"1","conversation_id":"protected"}',
            encoding="utf-8",
        )
    before = pointer.read_bytes()
    assert active_conversation_for(1, tenant_id="1") == ""
    remember_active_conversation(_ctx("replacement", "second"))
    assert pointer.read_bytes() == before
    if damage in {"missing_key", "empty_key"}:
        from app.application.ai_chat.dialogue_memory import _input_fingerprint

        other = _ctx("other-owner", "second", local_user_id=2)
        remember_active_conversation(other)
        assert not (memory_dir / f"{_key(2, '1', '')}-active.json").exists()
        with pytest.raises(RuntimeError):
            _input_fingerprint("new turn", other)
        assert pointer.read_bytes() == before
    if damage == "missing_key":
        assert not key_path.exists()
    elif damage == "empty_key":
        assert key_path.read_bytes() == b""


def test_pointer_and_dialogue_serialize_first_key_creation(memory_dir, monkeypatch):
    from app.application.ai_chat.active_conversation import _pointer_cipher
    from app.application.ai_chat.dialogue_memory import _cipher

    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("XCAGI_SECRET_KEY", raising=False)
    entered, attempted, release, concurrent = (threading.Event() for _ in range(4))
    provider = GroupChatRepository.desktop_data_dir_secret
    calls = []

    def blocked_provider(*args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        else:
            concurrent.set()
        return provider(*args, **kwargs)

    def pointer_cipher():
        attempted.set()
        return _pointer_cipher(create=True)

    monkeypatch.setattr(GroupChatRepository, "desktop_data_dir_secret", blocked_provider)
    with ThreadPoolExecutor(max_workers=2) as pool:
        dialogue = pool.submit(_cipher)
        assert entered.wait(5)
        pointer = pool.submit(pointer_cipher)
        try:
            assert attempted.wait(5)
            assert not concurrent.wait(0.2)
        finally:
            release.set()
        first, second = dialogue.result(timeout=5), pointer.result(timeout=5)
    assert second.decrypt(first.encrypt(b"original dialogue")) == b"original dialogue"
    assert first.decrypt(second.encrypt(b"active pointer")) == b"active pointer"
    assert len(calls) == 2


def test_legacy_pointer_survives_persistent_key_failure_without_process_fallback(
    memory_dir, monkeypatch
):
    from app.application.group_chat import storage
    from app.application.task_conversation_store import task_conversation_store

    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("XCAGI_SECRET_KEY", raising=False)
    for session_id in ("legacy", "replacement"):
        task_conversation_store.prepare_revision(session_id=session_id, user_id=1)
    pointer = memory_dir / f"{_key(1, '1', '')}-active.json"
    legacy = json.dumps({"owner": "1", "tenant_id": "1", "mod_id": "", "conversation_id": "legacy"})
    pointer.write_text(legacy, encoding="utf-8")

    def unavailable(*_args, **_kwargs):
        raise OSError("key storage is unavailable")

    def ephemeral_key():
        raise AssertionError("active pointers must never use an ephemeral key")

    make_temporary = storage.tempfile.mkstemp
    monkeypatch.setattr(storage.tempfile, "mkstemp", unavailable)
    monkeypatch.setattr(GroupChatRepository, "process_local_secret", ephemeral_key)
    remember_active_conversation(_ctx("replacement", "second"))
    assert pointer.read_text(encoding="utf-8") == legacy
    assert not (memory_dir / GroupChatRepository._SECRET_FILE_NAME).exists()
    assert active_conversation_for(1, tenant_id="1") == "legacy"
    assert active_conversation_for(2, tenant_id="1") == ""
    assert active_conversation_for(1, tenant_id="2") == ""
    assert pointer.read_text(encoding="utf-8") == legacy
    monkeypatch.setattr(storage.tempfile, "mkstemp", make_temporary)
    remember_active_conversation(_ctx("replacement", "second"))
    assert pointer.read_text(encoding="utf-8").startswith("enc:v1:")
    assert active_conversation_for(1, tenant_id="1") == "replacement"


@pytest.mark.parametrize("strict", [False, True])
def test_message_cipher_keeps_legacy_fallback_optional(monkeypatch, tmp_path, strict):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("XCAGI_SECRET_KEY", raising=False)
    data_dir = tmp_path / "unavailable"
    mkdir = Path.mkdir
    fallback = []

    def unavailable(path, *args, **kwargs):
        if path == data_dir:
            raise OSError("key storage is unavailable")
        return mkdir(path, *args, **kwargs)

    def ephemeral_key():
        fallback.append(True)
        return "test-process-key"

    monkeypatch.setattr(Path, "mkdir", unavailable)
    monkeypatch.setattr(GroupChatRepository, "process_local_secret", ephemeral_key)
    if strict:
        with pytest.raises(OSError):
            GroupChatRepository.message_cipher(data_dir=str(data_dir), require_persistent=True)
        assert fallback == []
    else:
        cipher = GroupChatRepository.message_cipher(data_dir=str(data_dir))
        assert cipher.decrypt(cipher.encrypt(b"message")) == b"message"
        assert fallback == [True]


def test_active_route_is_registered_before_the_session_path() -> None:
    from app.fastapi_routes.domains.conversation.conversation_routes import router
    from app.legacy.routes.conversation.compat_extra import router as live_router

    paths = [getattr(route, "path", "") for route in router.routes]
    assert paths.index("/api/conversations/active") < paths.index("/api/conversations/{session_id}")
    live_paths = [getattr(route, "path", "") for route in live_router.routes]
    assert live_paths.index("/conversations/active") < live_paths.index(
        "/conversations/{conversation_id}"
    )
