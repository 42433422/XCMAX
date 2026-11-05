"""Deadline propagation and fail-closed bounded-executor contracts."""

import time
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


@pytest.mark.parametrize("late", [False, True])
def test_deadline_is_trusted_and_late_success_is_unknown(monkeypatch, late):
    from app.application.agent_orchestrator import tool_executor as tools

    monkeypatch.delenv("XCAGI_AGENT_TOOL_HARD_TIMEOUT_REQUIRED", raising=False)
    moments = iter((10.0, 12.0 if late else 10.5))
    monkeypatch.setattr(tools.time, "monotonic", lambda: next(moments))
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
    run = SimpleNamespace(metadata={"non_retryable": True})
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
        timeout_seconds=0.05 if timeout_kind == "budget" else 30,
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
