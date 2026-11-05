"""Behavior boundaries for workbench execution, storage and owned uploads."""

from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile


@pytest.mark.asyncio
async def test_fresh_employee_pipeline_enters_generation_without_resume(monkeypatch, tmp_path):
    from modstore_server import workbench_api as api

    sid = "a" * 32
    sessions = {
        sid: {
            "id": sid,
            "status": "running",
            "user_id": 1,
            "steps": api._default_steps("employee"),
        }
    }
    monkeypatch.setattr(api, "WORKBENCH_SESSIONS", sessions)
    monkeypatch.setattr(api, "_workbench_session_store_dir", lambda: tmp_path)
    calls = []

    async def craft(*args, **kwargs):
        return None

    async def plan(*args, **kwargs):
        return {"employee_name": "隔离用例", "employee_brief": "整理内部任务"}

    async def scaffold(*args, **kwargs):
        calls.append(kwargs["brief"])
        return {"ok": False, "error": "controlled-generation-rejection"}

    monkeypatch.setattr(api, "_dispatch_craft_step", craft)
    monkeypatch.setattr(api, "_build_employee_orchestration_plan", plan)
    monkeypatch.setattr(api, "run_employee_ai_scaffold_async", scaffold)
    await api._run_workbench_employee_pipeline(
        sid,
        1,
        {},
        "employee",
        "整理内部任务",
        "local",
        "fixture",
        True,
        SimpleNamespace(),
        SimpleNamespace(id=1),
    )
    assert calls == ["整理内部任务"]
    assert sessions[sid]["status"] == "error"
    assert sessions[sid]["error"] == "controlled-generation-rejection"


@pytest.mark.asyncio
async def test_workbench_uploads_release_all_successful_inputs():
    from modstore_server.workbench_api import _read_workbench_uploads

    uploads = [
        UploadFile(io.BytesIO(b"one"), filename="one.txt"),
        UploadFile(io.BytesIO(b"two"), filename="two.txt"),
    ]
    try:
        result = await _read_workbench_uploads(uploads)
        assert result == [
            {"filename": "one.txt", "content": b"one"},
            {"filename": "two.txt", "content": b"two"},
        ]
        assert all(item.file.closed for item in uploads)
    finally:
        for item in uploads:
            await item.close()


@pytest.mark.asyncio
async def test_workbench_upload_limit_is_bounded_and_closes_remaining_inputs():
    from modstore_server.workbench_api import _read_workbench_uploads

    class TrackedUpload(UploadFile):
        def __init__(self):
            super().__init__(io.BytesIO(b"x" * (30 * 1024 * 1024 + 1)), filename="large.bin")
            self.read_sizes = []

        async def read(self, size=-1):
            self.read_sizes.append(size)
            return await super().read(size)

    first = TrackedUpload()
    second = UploadFile(io.BytesIO(b"untouched"), filename="second.txt")
    try:
        with pytest.raises(HTTPException) as error:
            await _read_workbench_uploads([first, second])
        assert error.value.status_code == 400
        assert all(0 < size <= 1024 * 1024 for size in first.read_sizes)
        assert first.file.closed and second.file.closed
    finally:
        await first.close()
        await second.close()


@pytest.mark.asyncio
async def test_workbench_cancelled_upload_releases_owned_files():
    from modstore_server.workbench_api import _read_workbench_uploads

    class CancelledUpload(UploadFile):
        async def read(self, size=-1):
            raise asyncio.CancelledError

    first = CancelledUpload(io.BytesIO(b"value"), filename="cancelled.txt")
    second = UploadFile(io.BytesIO(b"untouched"), filename="second.txt")
    try:
        with pytest.raises(asyncio.CancelledError):
            await _read_workbench_uploads([first, second])
        assert first.file.closed and second.file.closed
    finally:
        await first.close()
        await second.close()


def test_workbench_sessions_use_configured_external_runtime(monkeypatch, tmp_path):
    from modstore_server.workbench_api import _workbench_session_store_dir

    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path))
    assert _workbench_session_store_dir() == tmp_path / "workbench_sessions"


@pytest.mark.asyncio
async def test_draft_disconnect_cancels_generation_before_closing_database(monkeypatch):
    from modstore_server import employee_ai_pipeline, llm_key_resolver
    from modstore_server import workbench_api as api
    from modstore_server.script_agent import llm_client

    lifecycle = []
    jobs = []

    class Database:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            lifecycle.append("database-closed")

        def query(self, *args):
            return self

        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def limit(self, *args):
            return self

        def all(self):
            return []

    async def resolve(*args):
        return "openai", "fixture", None

    async def pipeline(*args, on_event, **kwargs):
        jobs.append(asyncio.current_task())
        try:
            await on_event({"event": "stage_start", "stage": "generation"})
            await asyncio.Event().wait()
        finally:
            lifecycle.append("generation-stopped")

    monkeypatch.setattr(api, "get_session_factory", lambda: Database)
    monkeypatch.setattr(api, "resolve_llm_provider_model_auto", resolve)
    monkeypatch.setattr(llm_key_resolver, "resolve_api_key", lambda *args: ("fixture-key", "test"))
    monkeypatch.setattr(llm_key_resolver, "resolve_base_url", lambda *args: None)
    monkeypatch.setattr(llm_client, "RealLlmClient", lambda *args, **kwargs: object())
    monkeypatch.setattr(employee_ai_pipeline, "run_pipeline", pipeline)
    response = await api.employee_ai_draft(
        api.EmployeeAiDraftBody(brief="整理内部任务"), SimpleNamespace(id=1)
    )
    try:
        event = await anext(response.body_iterator)
        assert b"stage_start" in event
        await response.body_iterator.aclose()
        assert lifecycle == ["generation-stopped", "database-closed"]
        assert jobs[0].done()
    finally:
        for job in jobs:
            if not job.done():
                job.cancel()
                try:
                    await job
                except asyncio.CancelledError:
                    pass


@pytest.mark.asyncio
@pytest.mark.parametrize("quality_passed", [True, False])
async def test_employee_delivery_requires_critical_quality_evidence(
    monkeypatch, tmp_path, quality_passed
):
    import json

    from modstore_server import workbench_api as api

    sid = "c" * 32
    pack_dir = tmp_path / "employee-pack"
    pack_dir.mkdir()
    manifest = {
        "id": "employee-pack",
        "name": "任务整理员",
        "version": "1.0.0",
        "artifact": "employee_pack",
        "employee": {"id": "employee-pack"},
    }
    (pack_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    sessions = {
        sid: {
            "id": sid,
            "user_id": 1,
            "status": "running",
            "steps": api._default_steps("employee"),
            "artifact": None,
        }
    }
    monkeypatch.setattr(api, "WORKBENCH_SESSIONS", sessions)
    monkeypatch.setattr(api, "_workbench_session_store_dir", lambda: tmp_path)
    seen = []

    async def scaffold(*args, **kwargs):
        return {
            "ok": True,
            "id": "employee-pack",
            "path": str(pack_dir),
            "manifest": manifest,
        }

    async def craft(step, **kwargs):
        seen.append(step)
        if step == "employee_plan":
            return {
                "employee_plan": {
                    "employee_name": "任务整理员",
                    "employee_brief": "整理内部任务",
                }
            }
        if step == "validate":
            return {"validate_warnings": [], "validate_errors": []}
        if step == "mod_sandbox":
            return {
                "emp_mod_sandbox": {"ok": True, "checks": []},
                "mod_sb_msg": "fixture checked",
            }
        if step == "standalone_smoke":
            return {
                "standalone_smoke_ok": True,
                "standalone_smoke_msg": "fixture checked",
            }
        if step == "host_check":
            return {
                "host_probe": {"skipped": True},
                "host_check_msg": "fixture has no host",
            }
        if step == "six_dim_gate":
            return {
                "six_dimension_report": {
                    "passed": quality_passed,
                    "critical_failed": not quality_passed,
                    "overall_score": 100 if quality_passed else 0,
                    "failed_dimensions": [] if quality_passed else ["runtime"],
                }
            }
        return None

    monkeypatch.setattr(api, "run_employee_ai_scaffold_async", scaffold)
    monkeypatch.setattr(api, "_dispatch_craft_step", craft)
    monkeypatch.setattr(
        api, "_refresh_employee_pack_catalog_zip", lambda *args: {"id": "employee-pack"}
    )
    monkeypatch.setattr(api, "_employee_quality_extras", lambda *args, **kwargs: ([], True, False))
    await api._run_workbench_employee_pipeline(
        sid,
        1,
        {"embed_script_workflow": False},
        "employee",
        "整理内部任务",
        "fixture",
        "fixture",
        True,
        SimpleNamespace(),
        SimpleNamespace(id=1),
    )
    assert "six_dim_gate" in seen
    assert sessions[sid]["status"] == ("done" if quality_passed else "error")
    if quality_passed:
        assert sessions[sid]["artifact"]["pack_id"] == "employee-pack"
        assert sessions[sid]["artifact"]["quality_report"]["runnable"] is True
    else:
        assert sessions[sid]["artifact"] is None
        assert "未通过" in sessions[sid]["error"]


def test_retry_reuses_artifacts_but_rechecks_runtime_evidence(tmp_path):
    from modstore_server.workbench.employee_state import EmployeeBuildState

    state = EmployeeBuildState(
        session_id="d" * 32,
        user_id=1,
        payload={},
        brief="整理内部任务",
        provider=None,
        model=None,
        replace=True,
        target="pack_only",
        embed_script_workflow=False,
        workflow_name=None,
        fhd_base=None,
        employee_files=[],
        routing_brief="整理内部任务",
        pipeline_label="generic",
        needs_llm_reasoning=False,
        uploaded_docx=False,
        use_assets=False,
        use_word_extract=False,
    )
    state.restore({"failed_step": "complete", "res": {"ok": True}, "pack_dir": str(tmp_path)})
    assert state.should_skip("generate")
    assert not state.should_skip("register_pack")
    assert not state.should_skip("workflow_sandbox")
    assert not state.should_skip("mod_sandbox")
    assert not state.should_skip("six_dim_gate")


def test_legacy_session_is_read_without_new_writes_to_source(tmp_path):
    import json

    from modstore_server.workbench.sessions import SessionStore

    legacy, runtime = tmp_path / "legacy", tmp_path / "runtime"
    legacy.mkdir()
    runtime.mkdir()
    sid = "b" * 32
    legacy_file = legacy / f"{sid}.json"
    original = {"id": sid, "user_id": 7, "intent": "workflow", "status": "done"}
    original_bytes = json.dumps(original).encode()
    legacy_file.write_bytes(original_bytes)
    store = SessionStore({}, asyncio.Lock(), lambda value: runtime / f"{value}.json", legacy)
    store.hydrate(sid)
    assert store.data[sid]["intent"] == "skill"
    store.data[sid]["status"] = "error"
    store.persist(sid)
    assert json.loads((runtime / f"{sid}.json").read_text())["status"] == "error"
    assert legacy_file.read_bytes() == original_bytes
    assert not list(runtime.glob("*.tmp"))


def test_session_runtime_rejects_source_checkout(monkeypatch, tmp_path):
    from modstore_server.workbench_api import _workbench_session_store_dir

    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    (checkout / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(checkout / "runtime"))
    with pytest.raises(ValueError):
        _workbench_session_store_dir()


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", ["[]", "not-json", '{"brief":""}'])
async def test_script_session_closes_uploads_when_metadata_is_rejected(metadata):
    from modstore_server import workbench_api as api

    upload = UploadFile(io.BytesIO(b"data"), filename="file.txt")
    try:
        with pytest.raises(HTTPException) as exc:
            await api.create_workbench_script_session(metadata, [upload], SimpleNamespace(id=1))
        assert exc.value.status_code == 400
        assert upload.file.closed
    finally:
        await upload.close()
