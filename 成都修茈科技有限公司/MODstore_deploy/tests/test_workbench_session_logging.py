"""Operational logs must not expose owned snapshots or their session filenames."""

import asyncio
import json
import logging

import pytest

from modstore_server.workbench.sessions import SessionProgress, SessionStore, session_filename


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["persist", "migration", "task", "finish", "signal"])
async def test_session_failures_log_operation_without_identifiers_or_exception_payload(
    tmp_path, monkeypatch, caplog, operation
):
    sid = "e" * 32
    private = "private-snapshot-payload-and-password"
    step_id = "private-workflow-step"
    runtime, legacy = tmp_path / "runtime", tmp_path / "legacy"
    runtime.mkdir()
    legacy.mkdir()
    session = {"id": sid, "status": "running", "steps": [{"id": step_id, "status": "running"}]}
    store = SessionStore(
        {sid: session}, asyncio.Lock(), lambda value: runtime / session_filename(value), legacy
    )
    progress = SessionProgress(store, lambda *_: None)
    caplog.set_level(logging.DEBUG, logger="modstore_server.workbench_api")

    def failure(*_args, **_kwargs):
        raise OSError(f"{private}: {runtime / session_filename(sid)}")

    if operation in {"persist", "migration"}:
        monkeypatch.setattr(SessionStore, "_write", staticmethod(failure))
        if operation == "persist":
            store.persist(sid)
        else:
            original = json.dumps(session)
            source = legacy / session_filename(sid)
            source.write_text(original)
            assert store.load(sid) == session
            assert source.read_text() == original
        assert not list(runtime.iterdir())
    elif operation == "task":

        async def broken_task():
            raise RuntimeError(private)

        task = asyncio.create_task(broken_task())
        await asyncio.gather(task, return_exceptions=True)
        store.task_failsafe(sid)(task)
        assert session["status"] == "error"
    elif operation == "finish":
        await progress.finish(sid, {})
        assert session["status"] == "done"
        assert session["steps"][0]["status"] == "skipped"
    else:
        from modstore_server import craft_failure_signals

        monkeypatch.setattr(craft_failure_signals, "emit_craft_step_failure", failure)
        await progress.fail(sid, "workflow_sandbox", "public failure")
        assert session["status"] == "error"
    records = [
        record for record in caplog.records if record.name == "modstore_server.workbench_api"
    ]
    assert records
    for record in records:
        assert record.exc_info is None
        for secret in (sid, private, str(runtime), step_id):
            assert secret not in record.getMessage()
