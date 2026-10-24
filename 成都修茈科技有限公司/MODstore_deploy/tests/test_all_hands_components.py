"""Employee report failures are isolated without leaving async work behind."""

from __future__ import annotations

import asyncio
from contextlib import nullcontext

import pytest

from modstore_server import all_hands_report as reports


def configure_meeting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        reports,
        "_resolve_employee_pairs",
        lambda ids, *, max_employees: [("broken", "Broken"), ("working", "Working")],
    )
    monkeypatch.setattr(reports, "resolve_platform_bench_llm", lambda: ("synthetic", "model"))
    monkeypatch.setenv("MODSTORE_ALL_HANDS_STAGGER_SEC", "0")


@pytest.mark.asyncio
async def test_one_worker_failure_returns_completed_report_for_other_employees(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_meeting(monkeypatch)
    completed = asyncio.Event()
    progress = []

    async def worker(**kwargs):
        if kwargs["pkg_id"] == "broken":
            raise ValueError("synthetic invalid employee metadata")
        await asyncio.sleep(0)
        completed.set()
        return {"employee_id": "working", "name": "Working", "status": "ok"}

    async def callback(value):
        progress.append(value)

    monkeypatch.setattr(reports, "_report_one_employee", worker)
    result = await reports.build_all_hands_report(with_research=False, progress_cb=callback)

    assert completed.is_set()
    assert result["summary"]["total"] == 2
    assert result["summary"]["ok"] == 1
    assert result["summary"]["error"] == 1
    assert [row["employee_id"] for row in result["employees"]] == ["broken", "working"]
    assert "synthetic invalid employee metadata" in result["employees"][0]["cognition_error"]
    assert sum(event["stage"] == "employee_done" for event in progress) == 2


@pytest.mark.asyncio
async def test_timeout_fallback_survives_the_same_unavailable_employee_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_meeting(monkeypatch)

    async def worker(**kwargs):
        if kwargs["pkg_id"] == "broken":
            raise TimeoutError("synthetic provider timeout")
        return {"employee_id": "working", "status": "ok"}

    def unavailable(*args):
        raise OSError("synthetic unavailable metadata store")

    monkeypatch.setattr(reports, "_report_one_employee", worker)
    monkeypatch.setattr(reports, "_manifest_signals", unavailable)
    monkeypatch.setattr(reports, "_recent_failures", unavailable)
    result = await reports.build_all_hands_report(with_research=False)

    assert result["summary"]["error"] == 1
    assert result["summary"]["ok"] == 1
    assert result["employees"][0]["manifest_signals"] == {}
    assert result["employees"][0]["recent_failures"] == []
    assert "超时" in result["employees"][0]["cognition_error"]


@pytest.mark.asyncio
async def test_meeting_cancellation_awaits_each_started_worker_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_meeting(monkeypatch)
    both_started = asyncio.Event()
    started = set()
    stopped = set()

    async def worker(**kwargs):
        employee_id = kwargs["pkg_id"]
        started.add(employee_id)
        if len(started) == 2:
            both_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            stopped.add(employee_id)

    monkeypatch.setattr(reports, "_report_one_employee", worker)
    task = asyncio.create_task(reports.build_all_hands_report(with_research=False))
    await asyncio.wait_for(both_started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped == {"broken", "working"}


@pytest.mark.asyncio
async def test_standby_provider_malformed_response_is_an_error_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def malformed(*args, **kwargs):
        return ["synthetic malformed response"]

    monkeypatch.setattr(reports, "get_session_factory", lambda: lambda: nullcontext(object()))
    monkeypatch.setattr("modstore_server.services.llm.chat_dispatch_via_session", malformed)
    text, error, tokens = await reports._standby_manifest_report_via_bench(
        pkg_id="synthetic-worker",
        display_name="Synthetic",
        task_text="Report",
        inp={},
        user_id=5,
        bench_provider="synthetic",
        bench_model="model",
    )
    assert text == ""
    assert error
    assert tokens == 0
