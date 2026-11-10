"""A long conversation keeps confirmed facts and the same active id."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.application.ai_chat.active_conversation import (
    active_conversation_for,
    remember_active_conversation,
)
from app.application.ai_chat.dialogue_memory import enrich_model_messages


@pytest.fixture
def memory_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
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
    remember_active_conversation(_ctx("conv-kept", "9"), conversation_id="conv-kept")
    assert active_conversation_for(1, tenant_id="1") == "conv-kept"
    remember_active_conversation(_ctx("other", "1", tenant_id=2), conversation_id="other")
    assert active_conversation_for(1, tenant_id="1") == "conv-kept"
    assert active_conversation_for(1, tenant_id="2") == "other"
    assert active_conversation_for(1, tenant_id="") == ""


def test_active_route_is_registered_before_the_session_path() -> None:
    from app.fastapi_routes.domains.conversation.conversation_routes import router
    from app.legacy.routes.conversation.compat_extra import router as live_router

    paths = [getattr(route, "path", "") for route in router.routes]
    assert paths.index("/api/conversations/active") < paths.index("/api/conversations/{session_id}")
    live_paths = [getattr(route, "path", "") for route in live_router.routes]
    assert live_paths.index("/conversations/active") < live_paths.index(
        "/conversations/{conversation_id}"
    )
