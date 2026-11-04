"""Deadline truthfulness and lock lifetime under concurrent callers."""

import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from app.application.agent_orchestrator import run_control
from app.application.employee_runtime.agent_loop import run_employee_agent_loop
from app.application.tool_execution_deadline import (
    invocation_deadline,
    remaining_invocation_seconds,
)


def test_operation_locks_reclaim_only_after_all_waiters_and_nested_owners_exit():
    active, peak = 0, 0

    def work(_):
        nonlocal active, peak
        with run_control.run_operation_lock("same"):
            with run_control.run_operation_lock("same"):
                active += 1
                peak = max(peak, active)
                time.sleep(0.001)
                active -= 1

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(work, range(32)))
    for index in range(1000):
        with run_control.run_operation_lock(str(index)):
            pass
    assert peak == 1 and not run_control._OPERATION_LOCKS


def _client(monkeypatch, complete):
    import app.infrastructure.llm.client as clients

    monkeypatch.setattr(clients, "require_api_key", lambda: None)
    monkeypatch.setattr(clients, "resolve_chat_model", lambda: "fake")
    monkeypatch.setattr(
        clients,
        "get_openai_compatible_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete))),
    )
    monkeypatch.setattr("app.application.agent_runtime.pipeline.meter_llm_call", lambda **_: None)


def test_late_model_success_is_not_completed_and_receives_remaining_timeout(monkeypatch):
    observed = []

    def complete(**kwargs):
        observed.append(kwargs["timeout"])
        time.sleep(0.04)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="late", tool_calls=[]))]
        )

    _client(monkeypatch, complete)
    result = run_employee_agent_loop(
        employee_id="e", system_prompt="s", task="t", tools=[], wall_time_limit_sec=0.01
    )
    assert 0 < observed[0] <= 0.01
    assert result["exit_status"] == "wall_time_limit" and not result["ok"]


def test_late_tool_does_not_dispatch_next_tool_or_claim_success(monkeypatch):
    import app.application.tools.workflow as workflow

    tools = [
        SimpleNamespace(id=str(n), function=SimpleNamespace(name="write", arguments="{}"))
        for n in (1, 2)
    ]
    _client(
        monkeypatch,
        lambda **_: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="", tool_calls=tools))]
        ),
    )
    seen = []

    def execute(*_):
        seen.append(remaining_invocation_seconds(100))
        time.sleep(0.04)
        return '{"success": true}'

    monkeypatch.setattr(workflow, "execute_workflow_tool", execute)
    with invocation_deadline(time.monotonic() + 0.02):
        result = run_employee_agent_loop(
            employee_id="e", system_prompt="s", task="t", tools=[{"function": {"name": "write"}}]
        )
    assert len(seen) == 1 and 0 < seen[0] <= 0.02
    assert result["exit_status"] == "wall_time_limit" and not result["ok"]
    assert result["reconciliation_required"] and result["execution_state"] == "unknown"
