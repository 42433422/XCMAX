"""Exercise the shipped process adapter, including late subprocess side effects."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil

from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import (
    AgentToolExecutor,
    execute_with_tool_deadline,
)
from app.application.tool_execution_deadline import invocation_deadline


class FixtureExecutor(AgentToolExecutor):
    def execute(self, step, *, runtime_context):
        if step.action == "hang":
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    "import time;from pathlib import Path;time.sleep(4);"
                    f"Path({step.params['late']!r}).write_text('late')",
                ]
            )
            Path(step.params["receipt"]).write_text(json.dumps([os.getpid(), child.pid]))
            while True:
                time.sleep(1)
        if step.action == "uncertain":
            with invocation_deadline(float("inf")) as budget:
                budget.uncertain.append({"kind": "http_timeout", "method": "POST"})
        return {"success": True, "tenant": runtime_context.get("tenant_id"), "pid": os.getpid()}


def test_real_adapter_reaps_hung_tool_and_child_then_reuses_executor(tmp_path):
    executor = FixtureExecutor()
    late, receipt = tmp_path / "late", tmp_path / "receipt"
    start = time.monotonic()
    result = execute_with_tool_deadline(
        executor,
        AgentStep(
            node_id="hung",
            tool_id="fixture",
            action="hang",
            params={"late": str(late), "receipt": str(receipt)},
        ),
        runtime_context={"tenant_id": 7},
        timeout_seconds=2,
    )
    assert time.monotonic() - start < 5
    assert result["outcome"] == "unknown" and result["retryable"] is False
    pids = json.loads(receipt.read_text())
    assert all(not psutil.pid_exists(pid) for pid in pids)
    assert not late.exists()
    next_result = execute_with_tool_deadline(
        executor,
        AgentStep(
            node_id="next",
            tool_id="fixture",
            action="read",
        ),
        runtime_context={"tenant_id": 9},
        timeout_seconds=5,
    )
    assert next_result["success"] and next_result["tenant"] == 9
    assert next_result["pid"] != os.getpid()
    # Beyond the child's original write deadline, not just immediately after kill.
    time.sleep(max(0, 4.5 - (time.monotonic() - start)))
    assert not late.exists()


def test_child_unknown_io_cannot_be_hidden_by_successful_tool():
    result = execute_with_tool_deadline(
        FixtureExecutor(),
        AgentStep(
            node_id="unknown",
            tool_id="fixture",
            action="uncertain",
        ),
        runtime_context={},
        timeout_seconds=5,
    )
    assert result["outcome"] == "unknown" and result["reconciliation_required"]
    assert result["io_reconciliation"] == [{"kind": "http_timeout", "method": "POST"}]


def test_default_adapter_refuses_unserializable_context_without_dispatch():
    result = execute_with_tool_deadline(
        AgentToolExecutor(),
        AgentStep(
            node_id="invalid",
            tool_id="fixture",
            action="read",
        ),
        runtime_context={"transaction": object()},
        timeout_seconds=1,
    )
    assert result["error_code"] == "tool_context_not_serializable"
