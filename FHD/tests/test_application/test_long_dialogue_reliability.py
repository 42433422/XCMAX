"""A long conversation keeps confirmed facts and the same active id."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from app.application.ai_chat.active_conversation import (
    active_conversation_for,
    remember_active_conversation,
)
from app.application.ai_chat.dialogue_memory import enrich_model_messages


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
    remember_active_conversation(
        _ctx("conv-kept", "9", session_id="private-auth-session"), conversation_id="conv-kept"
    )
    assert active_conversation_for(1, tenant_id="1") == "conv-kept"
    remember_active_conversation(_ctx("other", "1", tenant_id=2), conversation_id="other")
    assert active_conversation_for(1, tenant_id="1") == "conv-kept"
    assert active_conversation_for(1, tenant_id="2") == "other"
    assert active_conversation_for(1, tenant_id="") == ""
    assert all(
        "private-auth-session" not in path.read_text() for path in memory_dir.glob("*-active.json")
    )


def test_active_pointer_never_uses_an_authentication_session_as_conversation(memory_dir):
    from app.application.task_conversation_store import task_conversation_store

    token = "private-auth-session"
    task_conversation_store.prepare_revision(session_id=token, user_id=1)
    remember_active_conversation({"local_user_id": 1, "tenant_id": 1, "session_id": token})
    assert active_conversation_for(1, tenant_id="1") == ""
    assert list(memory_dir.glob("*-active.json")) == []


@pytest.mark.parametrize("interrupt_write", [False, True])
def test_active_pointer_temporary_file_is_private_before_writing(
    memory_dir, monkeypatch, interrupt_write
):
    from app.application.ai_chat import active_conversation as active
    from app.application.task_conversation_store import task_conversation_store

    task_conversation_store.prepare_revision(session_id="private-pointer", user_id=1)
    create = active.tempfile.NamedTemporaryFile
    observed = []

    def private_file(*args, **kwargs):
        stream = create(*args, **kwargs)
        observed.append(Path(stream.name))
        assert Path(stream.name).read_bytes() == b""
        if os.name != "nt":
            assert stat.S_IMODE(os.fstat(stream.fileno()).st_mode) == 0o600
        if interrupt_write:
            write = stream.write

            def interrupted_write(ciphertext):
                write(ciphertext[:16])
                raise OSError("interrupted write")

            stream.write = interrupted_write
        return stream

    monkeypatch.setattr(active.tempfile, "NamedTemporaryFile", private_file)
    previous_mask = os.umask(0)
    try:
        remember_active_conversation(_ctx("private-pointer", "1"))
    finally:
        os.umask(previous_mask)
    assert len(observed) == 1 and not observed[0].exists()
    if interrupt_write:
        assert active_conversation_for(1, tenant_id="1") == ""
        assert list(memory_dir.glob("*-active.json")) == []
        return
    assert active_conversation_for(1, tenant_id="1") == "private-pointer"
    if os.name != "nt":
        assert stat.S_IMODE(next(memory_dir.glob("*-active.json")).stat().st_mode) == 0o600


def test_active_route_is_registered_before_the_session_path() -> None:
    from app.fastapi_routes.domains.conversation.conversation_routes import router
    from app.legacy.routes.conversation.compat_extra import router as live_router

    paths = [getattr(route, "path", "") for route in router.routes]
    assert paths.index("/api/conversations/active") < paths.index("/api/conversations/{session_id}")
    live_paths = [getattr(route, "path", "") for route in live_router.routes]
    assert live_paths.index("/conversations/active") < live_paths.index(
        "/conversations/{conversation_id}"
    )
