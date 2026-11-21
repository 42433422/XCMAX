"""Audited reads retry through the original repair owner and durable identity."""

from __future__ import annotations

import copy
import sqlite3
import time
from dataclasses import replace

import pytest
from sqlalchemy import event

from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.run_repair import RunRepair
from app.application.agent_orchestrator.run_usage import RunUsageLedger
from app.application.agent_orchestrator.runtime_dependencies import RuntimeDependencies
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.tool_permission import clear_idempotent_replay_for_tests
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec, validate_tool_call
from app.application.tool_execution_deadline import invocation_deadline
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


class _InProcessExecutor(AgentToolExecutor):
    """Keep SQL fault injection in-process; use the real permission/receipt executor."""

    def execute_with_deadline(self, step, *, runtime_context, deadline_monotonic):
        return self.execute(step, runtime_context=runtime_context)


@pytest.fixture(autouse=True)
def isolated_receipts(tmp_path, monkeypatch):
    path = tmp_path / "claims.sqlite"
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(path))
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    clear_idempotent_replay_for_tests()
    yield path
    clear_idempotent_replay_for_tests()


@pytest.mark.parametrize(
    "tool_id,action,table",
    [
        ("sales", "query", "sales_orders"),
        ("reports", "sales_summary", "sales_order_items"),
        ("reports", "inventory_summary", "inventory_ledger"),
        ("reports", "purchase_summary", "purchase_orders"),
        ("reports", "dashboard", "products"),
    ],
)
def test_real_database_reads_retry_once_and_accept_empty_results(
    tool_id, action, table, trusted_actor, monkeypatch, isolated_receipts
):
    from app.application.facades import tools_facade

    spec = get_tool_action_spec(tool_id, action)
    assert spec is not None and spec.read_only and spec.idempotent
    actor = trusted_actor(user_id=771, role="read-retry", permissions=[spec.permission])
    engine = actor.factory.kw["bind"]
    faults, mutations, keys = [], [], []

    def intercept(_conn, _cursor, statement, _parameters, _context, _many):
        sql = statement.lower().lstrip()
        if table not in sql:
            return
        if sql.startswith(("insert", "update", "delete")):
            mutations.append(sql)
        if sql.startswith("select") and not faults:
            faults.append(sql)
            raise ConnectionError("read transport interrupted")

    dispatch = tools_facade.execute_registered_workflow_tool

    def record_identity(tool, verb, params):
        keys.append(params["_runtime_context"]["idempotency_key"])
        return dispatch(tool, verb, params)

    monkeypatch.setattr(tools_facade, "execute_registered_workflow_tool", record_identity)
    event.listen(engine, "before_cursor_execute", intercept)
    try:
        run = AgentOrchestrator(
            repository=InMemoryAgentRunRepository(), tool_executor=_InProcessExecutor()
        ).start_run_from_plan(
            user_id=str(actor.user_id),
            message="查询只读业务数据",
            plan=PlanGraph(
                plan_id=f"read-{tool_id}-{action}",
                intent="query",
                nodes=[WorkflowNode(node_id="read", tool_id=tool_id, action=action, params={})],
                metadata={"repair_overrides": {"read": {"retry": True, "max_attempts": 1}}},
            ),
            runtime_context=actor.context,
        )
    finally:
        event.remove(engine, "before_cursor_execute", intercept)
    assert run.status == "completed", (run.error, run.steps[0].output)
    assert run.steps[0].attempt_count == 2
    assert len(run.steps[0].repair_history) == 1
    assert len(keys) == 2 and keys[0] == keys[1]
    assert run.tool_calls[0].output["retryable"] is True
    assert run.tool_calls[0].output.get("outcome") != "unknown"
    assert run.tool_calls[1].output["success"] is True
    if action != "dashboard":
        assert run.tool_calls[1].output["data"] == []
    assert len(faults) == 1 and mutations == []
    with sqlite3.connect(isolated_receipts) as db:
        assert db.execute("select count(*) from tool_idempotency").fetchone()[0] == 1


def test_employee_listing_reads_directory_without_executing_employees(trusted_actor, monkeypatch):
    from app.application.employee_runtime import executor as employee_executor
    from app.mod_sdk import employee_directory

    spec = get_tool_action_spec("employee", "list")
    assert spec is not None and spec.read_only
    actor = trusted_actor(user_id=772, role="directory-reader", permissions=[spec.permission])
    called = []
    original = employee_directory.build_employee_directory

    def flaky_directory(**kwargs):
        called.append(kwargs)
        if len(called) == 1:
            raise ConnectionError("directory read interrupted")
        return original(**kwargs)

    def cannot_execute(*args, **kwargs):
        raise AssertionError("a directory read must not execute an employee")

    monkeypatch.setattr(employee_directory, "build_employee_directory", flaky_directory)
    monkeypatch.setattr(employee_executor, "execute_employee_task_local", cannot_execute)
    executor = AgentToolExecutor()
    step = AgentStep(node_id="read", tool_id="employee", action="list")
    context = {**actor.context, "idempotency_key": "directory-read"}
    first = executor.execute(step, runtime_context=context)
    second = executor.execute(step, runtime_context=context)
    assert first["success"] is False and first["retryable"] is True
    assert second["success"] is True and isinstance(second["data"], list)
    assert len(called) == 2


@pytest.mark.parametrize("uncertain_read", [False, True])
def test_read_metadata_never_overrides_a_write_or_trusted_uncertainty(
    uncertain_read, trusted_actor, monkeypatch, tmp_path
):
    tool_id, action = ("reports", "sales_summary" if uncertain_read else "export")
    spec = get_tool_action_spec(tool_id, action)
    assert spec is not None and spec.read_only is uncertain_read
    actor = trusted_actor(user_id=773, role="receipt-checker", permissions=[spec.permission])
    context = {**actor.context, "idempotency_key": "ambiguous-effect"}
    step = AgentStep(node_id="effect", tool_id=tool_id, action=action, risk="low", idempotent=True)
    effect = tmp_path / "effect.txt"
    with invocation_deadline(time.monotonic() + 30) as budget:

        def dispatch(*args, **kwargs):
            effect.write_text(effect.read_text() + "x" if effect.exists() else "x")
            if uncertain_read:
                budget.uncertain.append({"kind": "http_transport_error", "method": "POST"})
            raise ConnectionError("response lost after effect")

        monkeypatch.setattr(
            "app.application.facades.tools_facade.execute_registered_workflow_tool", dispatch
        )
        executor = AgentToolExecutor()
        first = executor.execute(step, runtime_context=context)
    step.output = first
    repair, run, _requests = _repair_owner(step, {"max_attempts": 99999})
    assert first["outcome"] == "unknown" and first["retryable"] is False
    assert not repair.prepare_repair_or_retry(
        run, step, runtime_context={"repair_overrides": {"effect": {"retry": True}}}
    )
    assert executor.execute(step, runtime_context=context)["outcome"] == "unknown"
    assert effect.read_text() == "x"


def _repair_owner(step, policy, legacy_limit=4):
    spec = get_tool_action_spec(step.tool_id, step.action)
    assert spec is not None
    spec = replace(spec, retry=policy)
    requests = []

    def request_repair(_run, current, _context):
        requests.append(current.attempt_count)
        return {
            "success": True,
            "params_patch": {"start_date": f"2026-01-0{current.attempt_count}"},
        }

    dependencies = RuntimeDependencies(
        action_spec=lambda *_: spec,
        validate=validate_tool_call,
        refresh_budget=lambda _: None,
        repair_enabled=lambda *_: True,
        repair_limit=lambda *_: legacy_limit,
        request_repair=request_repair,
    )
    repository = InMemoryAgentRunRepository()
    run = AgentRun(user_id="retry-policy", message="query", steps=[step])
    return RunRepair(repository, RunUsageLedger(dependencies), dependencies), run, requests


@pytest.mark.parametrize("entry", ["prepare_repair_or_retry", "prepare_llm_repair_or_retry"])
@pytest.mark.parametrize(
    "total,expected_repairs",
    [
        (0, 4),
        (1, 0),
        (3, 2),
        (99999, 4),
        (-1, 0),
        (None, 0),
        (True, 0),
        ("3", 0),
        (1.5, 0),
        ({}, 0),
    ],
)
def test_tool_spec_bounds_existing_repair_owner_without_reinterpreting_legacy_zero(
    entry, total, expected_repairs
):
    step = AgentStep(
        node_id="read",
        tool_id="reports",
        action="sales_summary",
        risk="low",
        idempotent=True,
        attempt_count=1,
        output={"success": False, "retryable": True},
    )
    repair, run, requests = _repair_owner(step, {"max_attempts": total}, legacy_limit=99999)
    context = {"repair_overrides": {"read": {"retry": True, "max_attempts": 99999}}}
    for _ in range(8):
        if not getattr(repair, entry)(run, step, runtime_context=context):
            break
        step.attempt_count += 1
        step.output = {"success": False, "retryable": True}
    assert len(step.repair_history) == expected_repairs
    assert step.attempt_count == expected_repairs + 1
    assert len(requests) == (expected_repairs if entry == "prepare_llm_repair_or_retry" else 0)


@pytest.mark.parametrize("unknown", [False, True])
def test_persisted_attempt_count_and_unknown_receipts_cannot_be_reset_by_large_policy(unknown):
    step = AgentStep(
        node_id="read",
        tool_id="reports",
        action="sales_summary",
        risk="low",
        idempotent=True,
        attempt_count=3,
        output={"success": False, "retryable": True},
    )
    if unknown:
        step.output["outcome"] = "unknown"
    repair, run, requests = _repair_owner(step, {"max_attempts": 99999 if unknown else 3})
    assert not repair.prepare_repair_or_retry(
        run,
        step,
        runtime_context={"repair_overrides": {"read": {"retry": True, "max_attempts": 99999}}},
    )
    assert step.repair_history == requests == []


@pytest.mark.asyncio
async def test_aiopen_catalog_is_read_only_but_requires_its_original_runtime(monkeypatch):
    from fastapi import FastAPI

    from app.application.aiopen import service

    spec = get_tool_action_spec("aiopen", "api_catalog")
    assert spec is not None and spec.read_only
    before = copy.deepcopy(service.AIOPEN_STATE)
    first = await service.invoke_tool("api_catalog", {}, FastAPI())
    second = await service.invoke_tool("api_catalog", {}, FastAPI())
    assert first == second and first["success"] is True
    assert before == service.AIOPEN_STATE
    calls = []
    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        lambda *args: calls.append(args),
    )
    result = AgentToolExecutor().execute(
        AgentStep(node_id="catalog", tool_id="aiopen", action="api_catalog"), runtime_context={}
    )
    assert result["error_code"] == "tool_entry_unsupported"
    assert result["execution_status"] == "not_started" and result["retryable"] is False
    assert calls == []
