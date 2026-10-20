"""Exercise the shipped process adapter, including late subprocess side effects."""

import json
import multiprocessing
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import (
    AgentToolExecutor,
    execute_with_tool_deadline,
)
from app.application.tool_execution_deadline import invocation_deadline


def _step(action="read", **params):
    return AgentStep(node_id=action, tool_id="fixture", action=action, params=params)


class FixtureExecutor(AgentToolExecutor):
    def execute(self, step, *, runtime_context):
        if step.action == "hang":
            script = (
                "import os,time,json;from pathlib import Path;"
                f"deadline=time.monotonic()+{step.params['late_after']};"
                f"Path({step.params['receipt']!r}).write_text(json.dumps([{os.getpid()},os.getpid(),deadline]));"
                "time.sleep(max(0,deadline-time.monotonic()));"
                f"Path({step.params['late']!r}).write_text('late')"
            )
            subprocess.Popen([sys.executable, "-c", script])
            while True:
                time.sleep(1)
        if step.action == "uncertain":
            with invocation_deadline(float("inf")) as budget:
                budget.uncertain.append({"kind": "http_timeout", "method": "POST"})
        return {"success": True, "tenant": runtime_context.get("tenant_id"), "pid": os.getpid()}


@pytest.mark.parametrize("budget", [2, 8])
def test_real_adapter_reaps_hung_tool_and_child_then_reuses_executor(tmp_path, budget):
    executor = FixtureExecutor()
    children = {child.pid for child in multiprocessing.active_children()}
    late, receipt = tmp_path / "late", tmp_path / "receipt"
    start = time.monotonic()
    result = execute_with_tool_deadline(
        executor,
        _step("hang", late=str(late), receipt=str(receipt), late_after=budget + 3),
        runtime_context={"tenant_id": 7},
        timeout_seconds=budget,
    )
    print({"budget": budget, "result": result, "child_receipt": receipt.exists()})
    assert time.monotonic() - start < budget + 3
    if budget == 2 and not receipt.exists():
        code = result.get("reconciliation_evidence", result).get("error_code")
        assert code == "tool_worker_not_started" and result["retryable"] is False, result
        write_deadline = time.monotonic()
    else:
        assert result.get("outcome") == "unknown" and result["retryable"] is False, result
        worker_pid, child_pid, write_deadline = json.loads(receipt.read_text())
        assert all(not psutil.pid_exists(pid) for pid in (worker_pid, child_pid))
    assert {child.pid for child in multiprocessing.active_children()} <= children
    assert not late.exists()
    next_result = execute_with_tool_deadline(
        executor,
        _step(),
        runtime_context={"tenant_id": 9},
        timeout_seconds=5,
    )
    assert next_result["success"] and next_result["tenant"] == 9
    assert next_result["pid"] != os.getpid()
    time.sleep(max(0, write_deadline + 0.5 - time.monotonic()))
    assert not late.exists()


def test_child_unknown_io_cannot_be_hidden_by_successful_tool():
    result = execute_with_tool_deadline(
        FixtureExecutor(),
        _step("uncertain"),
        runtime_context={},
        timeout_seconds=5,
    )
    assert result["outcome"] == "unknown" and result["reconciliation_required"]
    assert result["io_reconciliation"] == [{"kind": "http_timeout", "method": "POST"}]


def test_default_adapter_refuses_unserializable_or_expired_start_without_dispatch():
    children = {child.pid for child in multiprocessing.active_children()}
    for context, budget, codes in (
        ({"transaction": object()}, 1, {"tool_context_not_serializable"}),
        ({}, 0.001, {"tool_worker_not_started", "tool_timeout_unknown"}),
    ):
        result = execute_with_tool_deadline(
            AgentToolExecutor(),
            _step(),
            runtime_context=context,
            timeout_seconds=budget,
        )
        assert result["error_code"] in codes and result["success"] is False, result
        assert {child.pid for child in multiprocessing.active_children()} <= children
