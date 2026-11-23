"""The task boundary records a safe failure and preserves checkpoint handoff."""

from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator.elt_checkpoint_recovery import EltCheckpointWorkerExited
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.agent_orchestrator.step_execution import StepExecution


def _failing_call(monkeypatch, error):
    calls = []

    def execute(*_args, **_kwargs):
        calls.append(True)
        raise error

    monkeypatch.setattr(
        "app.application.agent_orchestrator.tool_executor.execute_with_tool_deadline", execute
    )
    step = AgentStep(node_id="read", tool_id="synthetic", action="read", idempotent=True)
    run = AgentRun(user_id="synthetic-owner", message="read a synthetic result", steps=[step])
    call = ToolCall(
        step_id=step.step_id, node_id=step.node_id, tool_id=step.tool_id, action=step.action
    )
    execution = StepExecution(
        InMemoryAgentRunRepository(),
        object(),
        SimpleNamespace(record_tool_usage_entry=lambda *_: True),
        SimpleNamespace(validate=lambda *_: SimpleNamespace(ok=True)),
        attach_artifacts=lambda *_: None,
        observe=lambda *_: {},
    )

    def invoke():
        execution._execute_call(run, step, call, {}, {}, {}, SimpleNamespace(timeout_seconds=1))

    return invoke, step, calls


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError, TypeError])
def test_tool_exception_boundary_preserves_type_without_exception_details(
    monkeypatch, caplog, error_type
):
    secret = "password=synthetic-private-error"
    invoke, step, calls = _failing_call(monkeypatch, error_type(secret))

    invoke()

    assert calls == [True]
    assert step.output == {
        "success": False,
        "error_code": "tool_exception",
        "error_type": error_type.__name__,
        "message": "工具执行失败",
    }
    assert error_type.__name__ in caplog.text
    assert secret not in caplog.text


def test_checkpoint_worker_exit_reaches_the_recovery_owner(monkeypatch):
    error = EltCheckpointWorkerExited("synthetic checkpoint handoff")
    invoke, step, calls = _failing_call(monkeypatch, error)

    with pytest.raises(EltCheckpointWorkerExited) as caught:
        invoke()

    assert caught.value is error
    assert calls == [True]
    assert step.output == {}
