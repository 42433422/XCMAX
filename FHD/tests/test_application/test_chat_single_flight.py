"""One account must not start two Codex runtimes at the same time."""

import threading

from app.application.agent_runtime import chat


def test_concurrent_chat_turn_reports_busy_instead_of_racing(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def execute(**_kwargs):
        started.set()
        release.wait(5)
        return {"ok": True, "run_id": "parent", "exit_status": "reply_completed"}

    monkeypatch.setattr("app.application.agent_runtime.gateway.run_runtime_task", execute)

    first = {}
    worker = threading.Thread(
        target=lambda: first.update(
            chat.run_runtime_chat(
                user_id="owner", message="a", context={"session_id": "s1"}, file_context={}
            )
        )
    )
    worker.start()
    assert started.wait(5)

    second = chat.run_runtime_chat(
        user_id="owner", message="b", context={"session_id": "s2"}, file_context={}
    )
    assert second["success"] is False
    assert second["data"]["error_code"] == "runtime_busy"
    assert second["retryable"] is True
    assert second["data"]["run_id"] is None

    release.set()
    worker.join(5)
    assert first["success"] is True
