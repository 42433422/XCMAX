from __future__ import annotations

from types import SimpleNamespace

from modstore_server import retort_clarification_gate
from modstore_server.api.actor_identity import authenticated_admin_actor
from modstore_server.strategic_layer_api import (
    RetortClarificationAnswerRequest,
    answer_retort_clarification,
)


def test_retort_answer_uses_authenticated_admin_identity(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_answer(
        session_id: str,
        *,
        answers: object,
        answered_by: str,
    ) -> dict[str, object]:
        captured.update(
            session_id=session_id,
            answers=answers,
            answered_by=answered_by,
        )
        return {"ok": True, "session": {"status": "answered"}}

    monkeypatch.setattr(retort_clarification_gate, "answer_clarification", fake_answer)
    body = RetortClarificationAnswerRequest.model_validate(
        {"answers": "范围已确认", "answered_by": "spoofed-admin"}
    )

    result = answer_retort_clarification(
        "clarification-1",
        body,
        admin=SimpleNamespace(id=42, username="founder", is_admin=True),
    )

    assert result["ok"] is True
    assert captured == {
        "session_id": "clarification-1",
        "answers": "范围已确认",
        "answered_by": "admin-user:42:founder",
    }


def test_authenticated_admin_actor_is_bounded() -> None:
    actor = authenticated_admin_actor(SimpleNamespace(id=7, username="x" * 300, is_admin=True))

    assert actor.startswith("admin-user:7:")
    assert len(actor) == 128
