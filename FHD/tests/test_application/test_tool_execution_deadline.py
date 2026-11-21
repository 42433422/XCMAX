"""Deadline propagation and fail-closed bounded-executor contracts."""

import time
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
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


@pytest.mark.parametrize("late", [False, True])
def test_deadline_is_trusted_and_late_success_is_unknown(monkeypatch, late):
    from app.application.agent_orchestrator import tool_executor as tools

    monkeypatch.delenv("XCAGI_AGENT_TOOL_HARD_TIMEOUT_REQUIRED", raising=False)
    moments = iter((10.0, 12.0 if late else 10.5))
    monkeypatch.setattr(tools, "time", SimpleNamespace(monotonic=lambda: next(moments)))
    seen = []

    def execute(step, *, runtime_context):
        seen.append(runtime_context)
        return {
            "success": late,
            "outcome": "completed" if late else "unknown",
            "task_id": "existing-task",
            "attempt_id": "attempt-1",
        }

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
    assert result["reconciliation_evidence"]["task_id"] == "existing-task"
    assert result["reconciliation_evidence"]["attempt_id"] == "attempt-1"
    assert result["retryable"] is False and result["reconciliation_required"] is True


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_timeout_never_dispatches(timeout):
    result = execute_with_tool_deadline(
        object(), _step(), runtime_context={}, timeout_seconds=timeout
    )
    assert result["error_code"] == "invalid_tool_timeout"


def test_unknown_outcome_blocks_automatic_repair_without_dispatch():
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository

    runner = AgentOrchestrator(repository=InMemoryAgentRunRepository())
    run = AgentRun(user_id="test-owner", message="original task", metadata={"non_retryable": True})
    assert runner._prepare_repair_or_retry(run, _step(), runtime_context={}) is False


@pytest.mark.parametrize("mode", ["expired", "outer_timeout", "http_timeout", "success"])
def test_employee_http_helpers_use_captured_budget_without_network(monkeypatch, mode):
    import asyncio

    import httpx

    from app.application.employee_runtime import executor as employee
    from app.application.tool_execution_deadline import invocation_deadline

    calls, cancelled = [], []
    monkeypatch.setattr(employee, "get_employee_tools", lambda employee_id: [])

    class Client:
        def __init__(self, **kwargs):
            calls.append("client")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, method, url, **kwargs):
            calls.append((method, kwargs))
            if mode == "http_timeout":
                raise httpx.ReadTimeout("stub request timed out")
            if mode == "outer_timeout":
                try:
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    cancelled.append(True)
                    raise
            return SimpleNamespace(is_success=True, status_code=200, json=lambda: {"id": 7})

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    duration = -1 if mode == "expired" else (0.2 if mode == "outer_timeout" else 10)
    with invocation_deadline(time.monotonic() + duration):
        with invocation_deadline(time.monotonic() + 100):  # Nested call cannot extend budget.
            ctx = employee._build_enriched_ctx("stub", "/tmp")
    # Scope has ended; a new thread/event loop must still use the captured budget.
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(
            asyncio.run, ctx["http_post"]("https://stub.invalid", {"a": 1}, timeout=None)
        ).result(timeout=2)
    if mode == "expired":
        assert result["outcome"] == "not_started" and calls == []
    elif mode in {"outer_timeout", "http_timeout"}:
        assert result["outcome"] == "unknown" and result["retryable"] is False
        assert len(calls) == 2  # Never retry an ambiguous POST.
        assert bool(cancelled) == (mode == "outer_timeout")
    else:
        assert result == {"ok": True, "status": 200, "body": {"id": 7}}
        assert calls[1] == ("POST", {"json": {"a": 1}})
    # Expired invocation context must not leak into the next unrelated call.
    mode = "success"
    fresh = employee._build_enriched_ctx("stub", "/tmp")
    assert asyncio.run(fresh["http_get"]("https://stub.invalid"))["ok"]


@pytest.mark.parametrize("timeout_kind", ["transport", "budget"])
@pytest.mark.parametrize("specialized", [False, True])
@pytest.mark.parametrize("claimed_success", [False, True, "raises"])
def test_employee_cannot_hide_early_http_timeout_from_outer_invocation(
    monkeypatch, claimed_success, specialized, timeout_kind
):
    import asyncio

    import httpx

    from app.application.employee_runtime import executor as employee

    monkeypatch.delenv("XCAGI_AGENT_TOOL_HARD_TIMEOUT_REQUIRED", raising=False)
    monkeypatch.setattr(employee, "get_employee_tools", lambda employee_id: [])
    calls = []

    async def request(self, *args, **kwargs):
        calls.append(args)
        if timeout_kind == "budget":
            await asyncio.sleep(10)
        raise httpx.ReadTimeout("response unknown")

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    Client.request = request
    monkeypatch.setattr(httpx, "AsyncClient", Client)

    def execute(step, *, runtime_context):
        ctx = employee._build_enriched_ctx("stub", "/tmp")
        from app.mod_sdk.employee_specialized_tools import _api_call

        request = (
            _api_call(
                "POST", "/probe", api_base="https://stub.invalid", json={"secret": "not-in-receipt"}
            )
            if specialized
            else ctx["http_post"]("https://stub.invalid", {"secret": "not-in-receipt"})
        )
        output = asyncio.run(request)
        if claimed_success == "raises":
            raise ValueError("employee processing failed after unknown request")
        return {"success": claimed_success, "data": {"output": output}}

    result = execute_with_tool_deadline(
        SimpleNamespace(execute=execute),
        _step(),
        runtime_context={},
        # Exercise a timeout after provider entry, allowing SDK setup under CI
        # load; the mocked request still waits 10 seconds and cannot complete.
        timeout_seconds=0.5 if timeout_kind == "budget" else 30,
    )
    assert len(calls) == 1 and result["outcome"] == "unknown"
    assert result["retryable"] is False and result["reconciliation_required"]
    assert result["io_reconciliation"] == [{"kind": "http_timeout", "method": "POST"}]
    if claimed_success == "raises":
        assert result["reconciliation_evidence"]["exception_type"] == "ValueError"
    else:
        assert result["reconciliation_evidence"]["success"] is claimed_success


@pytest.mark.parametrize("specialized", [False, True])
def test_existing_http_helper_obeys_shorter_current_scope(monkeypatch, specialized):
    import asyncio

    import httpx

    from app.application.tool_execution_deadline import build_http_helpers, invocation_deadline

    calls = []
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: calls.append(kwargs))
    with invocation_deadline(time.monotonic() + 100):
        get, _ = build_http_helpers()
        with invocation_deadline(time.monotonic() - 1):
            from app.mod_sdk.employee_specialized_tools import _api_call

            request = (
                _api_call("DELETE", "/probe", api_base="https://stub.invalid")
                if specialized
                else get("https://stub.invalid")
            )
            assert asyncio.run(request)["outcome"] == "not_started"
    assert calls == []


def test_unrelated_executor_error_keeps_original_exception(monkeypatch):
    monkeypatch.delenv("XCAGI_AGENT_TOOL_HARD_TIMEOUT_REQUIRED", raising=False)

    def execute(*args, **kwargs):
        raise ValueError("no unknown I/O")

    with pytest.raises(ValueError, match="no unknown I/O"):
        execute_with_tool_deadline(
            SimpleNamespace(execute=execute), _step(), runtime_context={}, timeout_seconds=1
        )


@pytest.mark.parametrize("bridge", ["executor", "agent_runner"])
def test_employee_async_bridge_preserves_invocation_budget(bridge):
    import asyncio
    from contextvars import ContextVar

    from app.application.employee_runtime import agent_runner, executor
    from app.application.tool_execution_deadline import _DEADLINE, invocation_deadline

    tenant = ContextVar("bridge_test_tenant", default=None)

    async def observe():
        owner = _DEADLINE.get()
        assert owner is not None
        inherited_tenant = tenant.get()
        with invocation_deadline(owner.deadline + 30) as nested:
            assert nested.deadline == owner.deadline
            tenant.set("child-only")
            nested.uncertain.append({"kind": "bridge_probe"})
        return inherited_tenant, owner.deadline

    async def running_loop():
        return (
            executor._run_maybe_async(observe)
            if bridge == "executor"
            else agent_runner._run_async(observe())
        )

    token = tenant.set("tenant-a")
    try:
        with invocation_deadline(time.monotonic() + 10) as budget:
            assert asyncio.run(running_loop()) == ("tenant-a", budget.deadline)
            assert budget.uncertain == [{"kind": "bridge_probe"}]
            assert tenant.get() == "tenant-a"
        assert _DEADLINE.get() is None
    finally:
        tenant.reset(token)


@pytest.mark.parametrize("failure", ["read_error", "protocol_error", "cancelled", 429, 503])
def test_remote_write_failure_cannot_be_hidden_by_employee_success(monkeypatch, failure):
    import asyncio

    import httpx

    from app.application.tool_execution_deadline import build_http_helpers

    monkeypatch.delenv("XCAGI_AGENT_TOOL_HARD_TIMEOUT_REQUIRED", raising=False)
    calls = []

    async def request(self, method, url, **kwargs):
        calls.append(method)
        if failure == "read_error":
            raise httpx.ReadError("private upstream error")
        if failure == "protocol_error":
            raise httpx.RemoteProtocolError("private upstream error")
        if failure == "cancelled":
            raise asyncio.CancelledError
        return httpx.Response(failure, json={"message": "result unavailable"})

    monkeypatch.setattr(httpx.AsyncClient, "request", request)

    def execute(*args, **kwargs):
        _, post = build_http_helpers()
        try:
            asyncio.run(post("https://fixture.invalid", {"private": "payload"}))
        except asyncio.CancelledError:
            pass  # An employee swallowing cancellation still cannot settle success.
        return {"success": True, "data": {"claimed": "complete"}}

    result = execute_with_tool_deadline(
        SimpleNamespace(execute=execute),
        _step(),
        runtime_context={},
        timeout_seconds=30,
    )
    assert calls == ["POST"]
    assert result["outcome"] == "unknown" and result["retryable"] is False
    assert result["reconciliation_evidence"]["success"] is True
    assert result["io_reconciliation"] == [
        {
            "kind": (
                "http_failure"
                if isinstance(failure, int)
                else "http_cancelled"
                if failure == "cancelled"
                else "http_transport_error"
            ),
            "method": "POST",
        }
    ]


@pytest.mark.parametrize("entry", ["prepare_repair_or_retry", "prepare_llm_repair_or_retry"])
@pytest.mark.parametrize(
    "output",
    [
        {"success": False, "outcome": "unknown", "retryable": True},
        {"success": False, "result": {"outputs": [{"execution_state": "running"}]}},
        {"success": False, "requires_reconciliation": True},
        {"success": False, "result": {"execution_status": "timeout"}},
        {"success": False, "error_code": "tool_timeout_unknown"},
        {"success": False, "error_code": "tool_billing_blocked"},
    ],
)
def test_repair_rechecks_receipt_when_old_run_lacks_non_retryable_flag(entry, output):
    from app.application.agent_orchestrator.run_repair import RunRepair

    # None dependencies intentionally fail if an uncertain receipt reaches repair,
    # billing, LLM generation or persistence rather than being refused at entry.
    repair = RunRepair(None, None, None)
    step = _step()
    step.risk, step.idempotent, step.output = "low", True, output
    run = AgentRun(user_id="test-owner", message="original task", steps=[step])
    assert not getattr(repair, entry)(run, step, runtime_context={})


@pytest.mark.parametrize("entry", ["prepare_repair_or_retry", "prepare_llm_repair_or_retry"])
def test_repair_override_cannot_extend_server_attempt_limit(entry):
    from app.application.agent_orchestrator.run_repair import RunRepair

    dependencies = SimpleNamespace(repair_enabled=lambda *_: True, repair_limit=lambda *_: 99999)
    repair = RunRepair(None, None, dependencies)
    step = _step()
    step.risk, step.idempotent = "low", True
    step.output = {"success": False, "retryable": True}
    step.repair_history = [{"attempt_count": attempt} for attempt in range(1, 5)]
    run = AgentRun(
        user_id="test-owner",
        message="original task",
        steps=[step],
        metadata={
            "plan": {
                "metadata": {
                    "repair_overrides": {step.node_id: {"max_attempts": 99999, "retry": True}},
                }
            }
        }
    )
    assert not getattr(repair, entry)(run, step, runtime_context={})

@pytest.mark.parametrize("claimed_success", [False, True])
@pytest.mark.parametrize("condition", ["timely", "late", "unknown_io"])
def test_reconciliation_receipt_keeps_evidence_only_when_returned_within_budget(
    monkeypatch, claimed_success, condition
):
    from app.application.agent_orchestrator import tool_executor as tools
    from app.application.tool_execution_deadline import invocation_deadline

    monkeypatch.setenv("XCAGI_AGENT_TOOL_HARD_TIMEOUT_REQUIRED", "true")
    moments = iter((10.0, 12.0 if condition == "late" else 10.5))
    monkeypatch.setattr(tools, "time", SimpleNamespace(monotonic=lambda: next(moments)))
    receipt = {
        "success": claimed_success,
        "outcome": "succeeded" if claimed_success else "unknown",
        "execution_outcome": "succeeded",
        "error_code": "tool_delivery_incomplete",
        "message": "The action was verified; one attachment was not delivered.",
        "retryable": True,
        "reconciliation_required": True,
        "run_id": "existing-run",
        "steps": [{"index": 0, "status": "completed"}],
        "verification": [{"status": "passed"}],
        "artifacts": [{"artifact_id": "json_receipt", "artifact_type": "file"}],
    }
    calls = []
    def execute(step, *, runtime_context, deadline_monotonic):
        calls.append(deadline_monotonic)
        if condition == "unknown_io":
            with invocation_deadline(deadline_monotonic) as budget:
                budget.uncertain.append({"kind": "http_timeout", "method": "POST"})
        return receipt
    result = execute_with_tool_deadline(
        SimpleNamespace(execute_with_deadline=execute),
        _step(),
        runtime_context={},
        timeout_seconds=1,
    )
    assert calls == [11.0]
    assert result["success"] is False and result["outcome"] == "unknown"
    assert result["retryable"] is False and result["reconciliation_required"] is True
    assert receipt["success"] is claimed_success and receipt["retryable"] is True
    if condition == "timely":
        assert result["error_code"] == receipt["error_code"]
        assert result["message"] == receipt["message"]
        for key in ("artifacts", "run_id", "execution_outcome", "steps", "verification"):
            assert result[key] == receipt[key]
        assert "reconciliation_evidence" not in result
    else:
        assert result["error_code"] == "tool_timeout_unknown"
        assert result["reconciliation_evidence"] == receipt
        assert "artifacts" not in result
        assert result["io_reconciliation"] == (
            [{"kind": "http_timeout", "method": "POST"}] if condition == "unknown_io" else []
        )
@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
@pytest.mark.parametrize(
    "marker",
    [
        {"requires_reconciliation": True},
        {"outcome_unknown": True},
        {"execution_status": "unknown"},
        {"result": {"outputs": [{"execution_state": "unknown"}]}},
    ],
)
def test_on_time_receipt_cannot_hide_unknown_effect(monkeypatch, marker):
    monkeypatch.delenv("XCAGI_AGENT_TOOL_HARD_TIMEOUT_REQUIRED", raising=False)
    raw = {"success": True, "request_id": "original-request", **marker}
    calls = []

    def execute(*_args, **_kwargs):
        calls.append(True)
        return raw

    result = execute_with_tool_deadline(
        SimpleNamespace(execute=execute),
        _step(),
        runtime_context={},
        timeout_seconds=30,
    )
    assert result["success"] is False and result["outcome"] == "unknown"
    assert result["retryable"] is False and result["reconciliation_required"] is True
    assert result["request_id"] == "original-request" and calls == [True]
    assert raw["success"] is True  # A projection must not rewrite the original evidence.

