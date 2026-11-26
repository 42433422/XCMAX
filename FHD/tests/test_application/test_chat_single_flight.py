"""One account must not start two Codex runtimes at the same time."""

import asyncio
import threading

import pytest

from app.application.agent_runtime import chat
from app.application.agent_task_context import scoped_conversation_user_id


@pytest.fixture(autouse=True)
def private_chat_state(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.utils.path_io.path_utils.get_desktop_state_dir", lambda **_kwargs: str(tmp_path)
    )


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


def test_cross_process_lock_busy_even_without_active_thread(monkeypatch, tmp_path):
    from filelock import FileLock

    path = tmp_path / "owner.lock"
    seen_owners = []

    def lock_path(owner):
        seen_owners.append(owner)
        return path

    monkeypatch.setattr(chat, "_chat_file_lock_path", lock_path)

    def forbidden(**_kwargs):
        raise AssertionError("must not execute while another process holds the lock")

    monkeypatch.setattr("app.application.agent_runtime.gateway.run_runtime_task", forbidden)
    # A distinct FileLock handle holds the same on-disk admission lock.
    context = {"local_user_id": 71, "session_id": "s2"}
    with FileLock(path, timeout=0):
        second = chat.run_runtime_chat(
            user_id=scoped_conversation_user_id("71", context),
            message="不能并发",
            context=context,
            file_context={},
        )
    assert seen_owners == ["71"]
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


def test_busy_continuation_keeps_original_parent_pointer(monkeypatch, tmp_path):
    from filelock import FileLock

    path = tmp_path / "account.lock"
    monkeypatch.setattr(chat, "_chat_file_lock_path", lambda _owner: path)
    with FileLock(path, timeout=0):
        busy = chat.run_runtime_chat(
            user_id="owner",
            message="原任务下一步",
            context={"agent_runtime_run_id": "original-parent", "session_id": "same-session"},
            file_context={},
        )
    assert busy["success"] is False
    assert busy["data"]["error_code"] == "runtime_busy"
    assert busy["runtime_context_update"]["agent_runtime_run_id"] == "original-parent"
    assert busy["retryable"] is True


@pytest.mark.parametrize("termination", [False, True], ids=["completed", "process-lost"])
def test_real_process_lock_released_after_termination_or_completion(
    monkeypatch, tmp_path, termination
):
    """Two OS processes share the account lock; a lost worker cannot strand it."""
    import os
    import subprocess
    import sys
    import textwrap
    import time
    from pathlib import Path

    from app.utils.path_io import path_utils

    root = Path(__file__).resolve().parents[2]
    state_dir = tmp_path / "shared-state"
    entered, release = tmp_path / "entered", tmp_path / "release"
    monkeypatch.setattr(
        path_utils, "get_desktop_state_dir", lambda **_kwargs: str(state_dir)
    )
    calls = []

    def execute(**kwargs):
        calls.append(kwargs)
        return {"success": True, "run_id": kwargs["context"]["agent_runtime_run_id"]}

    monkeypatch.setattr(chat, "_run_runtime_chat", execute)
    script = textwrap.dedent(
        """
        import sys
        import time
        from pathlib import Path
        from app.application.agent_runtime import chat
        from app.utils.path_io import path_utils

        state, entered, release = map(Path, sys.argv[1:])
        path_utils.get_desktop_state_dir = lambda **_kwargs: str(state)

        def execute(**_kwargs):
            entered.write_text("locked", encoding="utf-8")
            deadline = time.monotonic() + 15
            while not release.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            return {"success": True}

        chat._run_runtime_chat = execute
        result = chat.run_runtime_chat(
            user_id="71", message="first",
            context={"local_user_id": 71, "session_id": "first"},
            file_context={},
        )
        if not result["success"]:
            raise SystemExit("worker failed")
        """
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(root) + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(state_dir), str(entered), str(release)],
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    context = {
        "local_user_id": 71,
        "session_id": "continuation",
        "agent_runtime_run_id": "original-run",
    }
    try:
        deadline = time.monotonic() + 10
        while not entered.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert entered.exists(), "separate process never reached the acquired lock"
        busy = chat.run_runtime_chat(
            user_id=scoped_conversation_user_id("71", context),
            message="continue",
            context=context,
            file_context={},
        )
        assert busy["data"]["error_code"] == "runtime_busy"
        assert busy["runtime_context_update"]["agent_runtime_run_id"] == "original-run"
        assert not calls, "busy path must never start a second runtime"
        if termination:
            process.kill()  # A crash cannot execute graceful lock-release handlers.
        else:
            release.write_text("finish", encoding="utf-8")
        _, stderr = process.communicate(timeout=10)
        assert (process.returncode != 0) if termination else (process.returncode == 0), stderr

        resumed = chat.run_runtime_chat(
            user_id=scoped_conversation_user_id("71", context),
            message="continue",
            context=context,
            file_context={},
        )
        assert resumed["success"] is True
        assert len(calls) == 1
        assert calls[0]["context"]["agent_runtime_run_id"] == "original-run"
    finally:
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=10)
