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


def test_cross_process_lock_busy_even_without_active_thread(monkeypatch, tmp_path):
    from filelock import FileLock

    path = tmp_path / "owner.lock"
    monkeypatch.setattr(chat, "_chat_file_lock_path", lambda _owner: path)
    monkeypatch.setattr(
        "app.application.agent_runtime.gateway.run_runtime_task",
        lambda **_kwargs: {"ok": True, "exit_status": "reply_completed"},
    )
    # A distinct FileLock handle holds the same on-disk admission lock.
    with FileLock(path, timeout=0):
        second = chat.run_runtime_chat(
            user_id="owner", message="不能并发", context={}, file_context={}
        )
    assert second["data"]["error_code"] == "runtime_busy"
    assert second["retryable"] is True


def test_unavailable_cross_process_lock_never_runs_task(monkeypatch):
    def unavailable(_owner):
        raise OSError("fixture lock store unavailable")

    monkeypatch.setattr(chat, "_chat_file_lock_path", unavailable)

    def forbidden(**_kwargs):
        raise AssertionError("must not start a runtime without a lock")

    monkeypatch.setattr("app.application.agent_runtime.gateway.run_runtime_task", forbidden)
    failed = chat.run_runtime_chat(user_id="owner", message="执行业务", context={}, file_context={})
    assert failed["data"]["error_code"] == "runtime_storage_invalid"
    assert failed["retryable"] is False


def test_chat_admission_lock_path_is_hashed_private_state(monkeypatch, tmp_path):
    from pathlib import Path

    monkeypatch.setattr(
        "app.utils.path_io.path_utils.get_desktop_state_dir",
        lambda **_kwargs: str(tmp_path),
    )
    path = chat._chat_file_lock_path("customer-account")
    assert path.parent == Path(tmp_path) / "codex-runtime" / "chat-admission"
    assert "customer-account" not in path.name
    assert path.parent.stat().st_mode & 0o777 == 0o700


def test_text_only_runtime_instructions_skip_capability_discovery():
    from app.application.agent_runtime.gateway import _goal_instructions

    prompt = _goal_instructions(chat._INSTRUCTIONS)
    assert "纯解释" in prompt and "直接交付完整正文" in prompt
    assert "不要求目录" in prompt and "只有真实读取受限业务数据" in prompt
    assert "先从当前会话历史找唯一实体" in prompt
    assert "企业动作只能通过受控工具执行" in prompt


def test_unverified_reply_does_not_claim_zero_operations_completed():
    from app.domain.task_lifecycle.agent_runtime_results import (
        base_runtime_result,
        classify_runtime_result,
    )

    result = base_runtime_result("candidate")
    result["output"] = "库存是企业拥有的货物。"
    state = classify_runtime_result(result, [], {}, "auto", "completed")
    assert state == "blocked"
    assert "已核验 0 项操作" not in result["output"]
    assert "尚未核验" in result["output"]
