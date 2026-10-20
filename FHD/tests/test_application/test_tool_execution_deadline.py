"""Deadline propagation and fail-closed bounded-executor contracts."""

import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import execute_with_tool_deadline


def _step():
    return AgentStep(node_id="read", tool_id="business_db", action="read")


def test_strict_deadline_mode_refuses_unbounded_executor_before_side_effect(monkeypatch):
    monkeypatch.setenv("XCAGI_AGENT_TOOL_HARD_TIMEOUT_REQUIRED", "true")
    calls = []
    executor = SimpleNamespace(execute=lambda *a, **kw: calls.append(kw))
    result = execute_with_tool_deadline(executor, _step(), runtime_context={}, timeout_seconds=1)
    assert result["error_code"] == "tool_deadline_unsupported"
    assert result["retryable"] is False
    assert calls == []


def test_deadline_is_trusted_and_late_success_is_unknown(monkeypatch):
    from app.application.agent_orchestrator import tool_executor as tools

    monkeypatch.delenv("XCAGI_AGENT_TOOL_HARD_TIMEOUT_REQUIRED", raising=False)
    moments = iter((10.0, 12.0))
    monkeypatch.setattr(tools.time, "monotonic", lambda: next(moments))
    seen = []

    def execute(step, *, runtime_context):
        seen.append(runtime_context)
        return {"success": True}

    result = execute_with_tool_deadline(
        SimpleNamespace(execute=execute),
        _step(),
        runtime_context={"tenant_id": 7, "deadline_monotonic": 999},
        timeout_seconds=1,
    )
    assert seen[0]["deadline_monotonic"] == 11
    assert seen[0]["tenant_id"] == 7
    assert seen[0]["deadline_utc"]
    assert result["outcome"] == "unknown"
    assert result["retryable"] is False and result["reconciliation_required"] is True


def test_supported_process_adapter_releases_slot_and_kills_late_write(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_AGENT_TOOL_HARD_TIMEOUT_REQUIRED", "true")
    target = tmp_path / "late-side-effect"
    children = []

    class BoundedExecutor:
        def execute_with_deadline(self, step, *, runtime_context, deadline_monotonic):
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    f"import time;from pathlib import Path;time.sleep(1);Path({str(target)!r}).write_text('late')",
                ]
            )
            children.append(child)
            try:
                child.wait(timeout=max(0.001, deadline_monotonic - time.monotonic()))
            except subprocess.TimeoutExpired as exc:
                child.kill()
                child.wait(timeout=2)
                raise TimeoutError from exc
            return {"success": True}

    before = time.monotonic()
    result = execute_with_tool_deadline(
        BoundedExecutor(), _step(), runtime_context={}, timeout_seconds=0.1
    )
    assert time.monotonic() - before < 2
    assert result["outcome"] == "unknown" and result["retryable"] is False
    assert children[0].poll() is not None
    assert not target.exists()


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_timeout_never_dispatches(timeout):
    result = execute_with_tool_deadline(
        object(), _step(), runtime_context={}, timeout_seconds=timeout
    )
    assert result["error_code"] == "invalid_tool_timeout"


def test_unknown_outcome_blocks_automatic_repair_without_dispatch():
    from app.application.agent_orchestrator.orchestrator_agentorchestrator_mixin02 import (
        _AgentOrchestratorPart02Mixin,
    )

    runner = _AgentOrchestratorPart02Mixin()
    run = SimpleNamespace(metadata={"non_retryable": True})
    assert runner._prepare_repair_or_retry(run, _step(), runtime_context={}) is False
