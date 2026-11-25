"""One account must not start two Codex runtimes at the same time."""

import asyncio
import threading

import pytest

from app.application.agent_runtime import chat
from app.application.agent_task_context import scoped_conversation_user_id


@pytest.mark.parametrize("scoped", [False, True], ids=["direct", "service"])
@pytest.mark.parametrize("run_id", [None, "original-s2"], ids=["new", "continuation"])
def test_concurrent_chat_turn_reports_busy_instead_of_racing(monkeypatch, scoped, run_id):
    started = threading.Event()
    release = threading.Event()
    calls = []

    def execute(**kwargs):
        calls.append(kwargs)
        if kwargs["task"] == "a":
            started.set()
            assert release.wait(5)
        return {
            "ok": True,
            "run_id": kwargs.get("run_id") or "parent",
            "exit_status": "reply_completed",
        }

    monkeypatch.setattr("app.application.agent_runtime.gateway.run_runtime_task", execute)

    def invoke(message, context):
        owner = str(context["local_user_id"])
        return chat.run_runtime_chat(
            user_id=scoped_conversation_user_id(owner, context) if scoped else owner,
            message=message,
            context=context,
            file_context={},
        )

    first = {}
    worker = threading.Thread(
        target=lambda: first.update(invoke("a", {"local_user_id": 71, "session_id": "s1"}))
    )
    worker.start()
    context = {"local_user_id": 71, "session_id": "s2", "agent_runtime_run_id": run_id}
    try:
        assert started.wait(5)
        second = invoke("b", context)
        assert second["success"] is False
        assert second["data"]["error_code"] == "runtime_busy"
        assert second["retryable"] is True
        assert second["data"]["run_id"] == run_id
        assert second["runtime_context_update"] == {
            "agent_runtime_run_id": run_id,
            "conversation_id": "s2",
            "status": "waiting_user" if run_id else "blocked",
        }
        assert second["data"]["business_receipts"] == []
        assert invoke("other", {"local_user_id": 72, "session_id": "s3"})["success"] is True
        assert [call["task"] for call in calls] == ["a", "other"]
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert first["success"] is True

    resumed = invoke("b", context)
    assert resumed["success"] is True
    assert calls[-1]["run_id"] == run_id
    assert calls[-1]["answer_to_waiting_input"] is bool(run_id)


@pytest.mark.parametrize("error", [RuntimeError, asyncio.CancelledError])
def test_failed_or_cancelled_turn_releases_account(monkeypatch, error):
    def execute(**_kwargs):
        raise error("interrupted")

    monkeypatch.setattr("app.application.agent_runtime.gateway.run_runtime_task", execute)
    options = {"user_id": "interrupted-owner", "message": "a", "context": {}, "file_context": {}}
    with pytest.raises(error, match="interrupted"):
        chat.run_runtime_chat(**options)
    monkeypatch.setattr(
        "app.application.agent_runtime.gateway.run_runtime_task",
        lambda **_kwargs: {"ok": True, "exit_status": "reply_completed"},
    )
    assert chat.run_runtime_chat(**options)["success"] is True


def test_completed_accounts_do_not_accumulate_in_admission_registry(monkeypatch):
    monkeypatch.setattr(
        "app.application.agent_runtime.gateway.run_runtime_task",
        lambda **_kwargs: {"ok": True, "exit_status": "reply_completed"},
    )
    before = set(chat._ACTIVE_SLOTS)
    for index in range(20):
        result = chat.run_runtime_chat(
            user_id=f"completed-owner-{index}", message="a", context={}, file_context={}
        )
        assert result["success"] is True
    assert set(chat._ACTIVE_SLOTS) == before
