"""Read original child results and keep incomplete parent deliveries unresolved."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from app.application.employee_runtime.task_continuity import ledger_path, load_employee_task_ledger
from tests.test_application.test_employee_handoff_e25 import (
    _card,
)
from tests.test_application.test_employee_handoff_e25 import (
    customers_db as customers_db,
)
from tests.test_application.test_employee_handoff_e25 import (
    signed_handoff_actor as signed_handoff_actor,
)
from tests.test_application.test_task_continuity_acceptance import _effects, _install, _run


@pytest.mark.parametrize(
    "change",
    ["missing", "tenant_id", "user_id", "parent_task_id", "root_task_id", "task_id", "duplicate"],
)
def test_original_child_set_cannot_shrink_or_change_owner_after_restart(tmp_path, change):
    _install(tmp_path, "child_work")
    scope = {"tenant_id": "t1", "user_id": "u1"}
    parent = _run(
        tmp_path,
        "lead",
        continuity_action="start",
        completion_condition="all_children_success",
        **scope,
    )
    split = _run(
        tmp_path,
        "lead",
        continuity_action="split",
        task_id=parent["task_id"],
        children=[
            {"employee_id": f"e{i}", "tool": "child_work", "params": {"token": f"t{i}"}}
            for i in range(3)
        ],
        **scope,
    )
    child_ids = split["task"]["child_task_ids"]
    for index, child_id in enumerate(child_ids):
        assert _run(
            tmp_path, f"e{index}", continuity_action="child_return", task_id=child_id, **scope
        )["business_success"]
    original = load_employee_task_ledger(tmp_path)
    assert original["tasks"][parent["task_id"]]["status"] == "completed"
    changed = copy.deepcopy(original)
    if change == "missing":
        del changed["tasks"][child_ids[-1]]
    elif change == "duplicate":
        changed["tasks"][parent["task_id"]]["child_task_ids"].append(child_ids[-1])
    else:
        changed["tasks"][child_ids[-1]][change] = "another-original"
    ledger_path(tmp_path).write_text(json.dumps(changed))
    # A fresh production runtime reads the ledger and reuses the original first
    # child's result. Neither this readback nor restoration reruns its tool.
    _run(tmp_path, "e0", continuity_action="child_return", task_id=child_ids[0], **scope)
    stopped = load_employee_task_ledger(tmp_path)["tasks"][parent["task_id"]]
    assert stopped["status"] == "recovering"
    assert stopped["error_code"] == "child_result_unavailable"
    assert stopped["aggregate"]["incomplete"] >= 1
    assert stopped["result_payload"] == {}
    assert len(_effects(tmp_path, "child_work")) == 3
    ledger_path(tmp_path).write_text(json.dumps(original))
    _run(tmp_path, "e0", continuity_action="child_return", task_id=child_ids[0], **scope)
    restored = load_employee_task_ledger(tmp_path)["tasks"][parent["task_id"]]
    assert restored["status"] == "completed"
    assert {row["task_id"] for row in restored["result_payload"]["children"]} == set(child_ids)
    assert len(_effects(tmp_path, "child_work")) == 3


@pytest.fixture
def actual_children(tmp_path, monkeypatch, customers_db, signed_handoff_actor):
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
    from app.application.employee_runtime import handoff_commit
    from app.application.employee_runtime.executor import execute_employee_task_local

    workspace = tmp_path / "owned-ledger"
    workspace.mkdir()
    monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.setattr(
        AgentToolExecutor,
        "execute_with_deadline",
        lambda self, step, *, runtime_context, deadline_monotonic: self.execute(
            step, runtime_context=runtime_context
        ),
    )
    employees = ["clerk", "employee-b", "employee-c", "employee-d"]
    for employee in employees:
        _card(workspace, employee)

    def original(action, **payload):
        return execute_employee_task_local(
            "clerk",
            "Read the original customer records",
            {"continuity_action": action, **payload},
            user_id=11,
            workspace_root=str(workspace),
            runtime_context=signed_handoff_actor,
        )

    return SimpleNamespace(
        workspace=workspace,
        actor=SimpleNamespace(user_id=11, context=signed_handoff_actor),
        employees=employees,
        original=original,
        repository=handoff_commit.get_agent_run_repository,
    )


def _host_case(env, task_id, operation, **payload):
    from app.application.agent_orchestrator.result_verification import freeze_verification_contract
    from app.application.agent_orchestrator.task_context import apply_task_context
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
    from tests.test_application.test_verification_readback import invocation

    case = invocation(
        env.actor,
        tool="employee",
        action="execute",
        params={
            "employee_id": env.employees[0],
            "task": "Read the original customer records",
            "continuity_action": operation,
            "task_id": task_id,
            "input": payload,
        },
    )
    case.context.update(
        task_id=task_id,
        employee_id=env.employees[0],
        node_id=case.step.node_id,
        workspace_root=str(env.workspace),
        workspace_path=str(env.workspace),
    )
    case.run.metadata["runtime_context"] = copy.deepcopy(case.context)
    apply_task_context(case.run, case.context)
    freeze_verification_contract(
        case.run, case.step, case.call, get_tool_action_spec("employee", "execute"), case.context
    )
    env.repository().save(case.run)
    return case


def _native_request(target="employee-b", key="original-delegated-read"):
    return {
        "target": target,
        "permissions": ["customers.query"],
        "delegated_tool": "customers",
        "delegated_action": "query",
        "delegated_params": {"keyword": "交接客户甲"},
        "idempotency_key": key,
    }


def _execute_case(case):
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor

    output = AgentToolExecutor().execute(case.step, runtime_context=case.context)
    assert output["success"] and output["data"]["business_success"], output
    return output


@pytest.mark.parametrize("operation", ["run_tools", "child_return", "chain"])
def test_original_host_employee_results_verify_from_child_runs_without_replay(
    actual_children, monkeypatch, operation
):
    from app.application.agent_orchestrator.result_verification import verify_step_result
    from tests.test_application.test_sales_verification_readback import verify

    env = actual_children
    start = env.original(
        "start",
        completion_condition=(
            "all_children_success" if operation == "child_return" else "all_steps_success"
        ),
        steps=[
            {
                "tool": "handoff_commit",
                "params": _native_request(),
            }
        ]
        if operation == "run_tools"
        else [],
    )
    task_id = start["task_id"]
    arguments = {}
    early = []
    if operation == "chain":
        arguments = {
            "employees": env.employees,
            "permissions": ["customers.query"],
            "steps": [
                {
                    "step_id": f"customer-{index}",
                    "tool": "customers",
                    "action": "query",
                    "params": {"keyword": "交接客户甲"},
                }
                for index in range(4)
            ],
        }
    elif operation == "child_return":
        # Parent completion is determined by the original split's complete child set.
        split = env.original(
            "split",
            task_id=task_id,
            children=[
                {
                    "employee_id": "clerk",
                    "tool": "handoff_commit",
                    "params": _native_request(target, f"split-child-{index}"),
                }
                for index, target in enumerate(env.employees[1:])
            ],
        )
        for child_id in split["task"]["child_task_ids"][:-1]:
            previous = _host_case(env, child_id, operation)
            returned = _execute_case(previous)
            assert verify(previous, returned)["accepted"] is False
            early.append((previous, returned))
        task_id = split["task"]["child_task_ids"][-1]
    case = _host_case(env, task_id, operation, **arguments)
    output = _execute_case(case)
    original_ledger = ledger_path(env.workspace).read_bytes()
    runs = {
        row.run_id: row.to_dict() for row in env.repository().list_recent(user_id="11", limit=100)
    }

    def no_execution(*_args, **_kwargs):
        pytest.fail("independent employee verification replayed the producing action")

    monkeypatch.setattr(
        "app.application.employee_runtime.handoff_commit.commit_registered_handoff", no_execution
    )
    monkeypatch.setattr(
        "app.application.employee_runtime.task_continuity.TaskContinuityRuntime.dispatch",
        no_execution,
    )
    report = verify(case, output)
    assert report["accepted"], report
    evidence = report["checks"][0]["evidence"]
    assert evidence["scope"] == "task_completion" and evidence["business_effect_verified"]
    assert (
        len(evidence["child_run_ids"]) == {"run_tools": 1, "child_return": 3, "chain": 4}[operation]
    )
    assert verify_step_result(run=case.run, step=case.step, call=case.call, context=case.context)[
        "accepted"
    ]
    for previous, returned in early:
        assert verify(previous, returned)["accepted"]
    assert ledger_path(env.workspace).read_bytes() == original_ledger
    assert {
        row.run_id: row.to_dict() for row in env.repository().list_recent(user_id="11", limit=100)
    } == runs


@pytest.mark.parametrize(
    "fault",
    [
        "child_missing",
        "child_unknown",
        "child_tenant",
        "child_parent",
        "child_verification",
        "receipt_digest",
        "ledger_only",
        "missing_child",
        "current_permission",
    ],
)
def test_ledger_success_cannot_replace_original_child_or_current_authority(actual_children, fault):
    from app.application.employee_runtime.task_continuity import _public_task
    from app.db.models.agent import AgentRunRecord
    from app.db.models.user import Session as UserSession
    from tests.test_application.test_sales_verification_readback import verify

    env = actual_children
    task_id = env.original(
        "start",
        steps=[
            {
                "tool": "handoff_commit",
                "params": _native_request(),
            }
        ],
    )["task_id"]
    case = _host_case(env, task_id, "run_tools")
    output = _execute_case(case)
    assert verify(case, output)["accepted"]
    ledger = load_employee_task_ledger(env.workspace)
    task = ledger["tasks"][task_id]
    child_id = task["steps"][0]["result_payload"]["child_run_id"]
    if fault in {"ledger_only", "missing_child"}:
        if fault == "ledger_only":
            task["steps"][0]["tool"] = "model_claimed_ok"
        else:
            task["child_task_ids"].append("required-child-not-recorded")
        ledger_path(env.workspace).write_text(json.dumps(ledger))
        output["data"]["task"] = _public_task(task)
    else:
        with env.repository().transaction() as db:
            row = db.get(AgentRunRecord, child_id)
            if fault == "child_missing":
                db.delete(row)
            elif fault == "current_permission":
                db.query(UserSession).filter_by(user_id=11).delete()
            else:
                payload = json.loads(row.payload_json)
                if fault == "child_unknown":
                    payload["status"] = row.status = "running"
                elif fault == "child_tenant":
                    payload["metadata"]["runtime_context"]["tenant_id"] = "foreign"
                elif fault == "child_parent":
                    payload["metadata"]["runtime_context"]["parent_run_id"] = "unrelated-run"
                elif fault == "child_verification":
                    payload["tool_calls"][0]["metadata"].pop("verification", None)
                else:
                    payload["tool_calls"][0]["metadata"]["verification_output_sha256"] = "changed"
                row.payload_json = json.dumps(payload)
    original = ledger_path(env.workspace).read_bytes()
    report = verify(case, output)
    assert report["accepted"] is False, report
    assert ledger_path(env.workspace).read_bytes() == original


@pytest.mark.parametrize("fault", ["missing", "user_id", "tenant_id", "root_task_id", "child_list"])
def test_child_return_cannot_write_a_foreign_or_unbound_parent(tmp_path, fault):
    _install(tmp_path, "child_work")
    scope = {"tenant_id": "t1", "user_id": "u1"}
    parent_id = _run(
        tmp_path,
        "lead",
        continuity_action="start",
        completion_condition="all_children_success",
        **scope,
    )["task_id"]
    split = _run(
        tmp_path,
        "lead",
        continuity_action="split",
        task_id=parent_id,
        children=[
            {"employee_id": f"e{index}", "tool": "child_work", "params": {"token": str(index)}}
            for index in range(3)
        ],
        **scope,
    )
    child_id = split["task"]["child_task_ids"][0]
    ledger = load_employee_task_ledger(tmp_path)
    if fault == "missing":
        del ledger["tasks"][parent_id]
    elif fault == "child_list":
        ledger["tasks"][parent_id]["child_task_ids"].remove(child_id)
    else:
        ledger["tasks"][parent_id][fault] = "foreign"
    ledger_path(tmp_path).write_text(json.dumps(ledger))
    before = ledger_path(tmp_path).read_bytes()
    denied = _run(tmp_path, "e0", continuity_action="child_return", task_id=child_id, **scope)
    assert denied["success"] is False and denied["error_code"] == "parent_binding_changed"
    assert ledger_path(tmp_path).read_bytes() == before
    assert _effects(tmp_path, "child_work") == []


@pytest.mark.parametrize(
    "fault",
    [
        "parent_run_id",
        "tenant_id",
        "user_id",
        "_mod_authorization",
        "_actor_authorization",
        "employee_id",
        "idempotency_key",
        "step_id",
        "params",
        "original_parent",
        "original_task",
        "original_tenant",
        "original_handoff",
        "cycle",
        "expired_lease",
        "generation",
    ],
)
def test_child_read_requires_original_ancestry_and_live_parent_fence(
    actual_children, monkeypatch, fault
):
    from app.application.agent_orchestrator.business_write_guard import worker_claim_scope
    from app.application.agent_orchestrator.task_execution_sql_repository import (
        SQLAlchemyTaskExecutionRepository,
    )
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
    from app.application.agent_orchestrator.tool_permission import begin_idempotent_replay
    from app.application.agent_orchestrator.worker_repository import WorkerLeaseLost
    from app.db.models.agent import AgentRunRecord, AgentTaskExecutionRecord

    env = actual_children
    task_id = env.original(
        "start", steps=[{"tool": "handoff_commit", "params": _native_request()}]
    )["task_id"]
    case = _host_case(env, task_id, "run_tools")
    repository, queue = env.repository(), SQLAlchemyTaskExecutionRepository()
    queue.enqueue(case.run)
    claim = queue.claim("original-parent", lease_seconds=60, run_id=case.run.run_id)
    assert claim is not None
    execute, checked = AgentToolExecutor.execute, []

    def fenced(self, step, *, runtime_context):
        if (step.tool_id, step.action) != ("customers", "query"):
            return execute(self, step, runtime_context=runtime_context)
        context, params = copy.deepcopy(runtime_context), copy.deepcopy(step.params)
        if fault.startswith("original_") or fault == "cycle":
            with repository.transaction() as db:
                row = db.get(AgentRunRecord, context["run_id"])
                payload = json.loads(row.payload_json)
                saved = payload["metadata"]["runtime_context"]
                if fault == "original_handoff":
                    payload["metadata"]["plan"]["metadata"].pop("handoff_request")
                elif fault == "original_task":
                    payload["metadata"]["task_context"]["task_id"] = "another-original"
                else:
                    key = "tenant_id" if fault == "original_tenant" else "parent_run_id"
                    saved[key] = context[key] = (
                        context["run_id"] if fault == "cycle" else "another-original"
                    )
                row.payload_json = json.dumps(payload)
        elif fault in {"expired_lease", "generation"}:
            with repository.transaction() as db:
                row = db.get(AgentTaskExecutionRecord, case.run.run_id)
                if fault == "generation":
                    row.execution_count += 1
                else:
                    row.lease_expires_at = "2000-01-01T00:00:00+00:00"
        elif fault == "params":
            params["keyword"] = "different query"
        else:
            context[fault] = {} if fault.startswith("_") else "another-original"
        with pytest.raises(WorkerLeaseLost):
            begin_idempotent_replay(context, step.tool_id, step.action, params)
        checked.append(context["run_id"])
        return {
            "success": False,
            "error_code": "tested_original_fence_rejection",
            "retryable": False,
        }

    monkeypatch.setattr(AgentToolExecutor, "execute", fenced)
    with worker_claim_scope(repository, claim, claim.lease_owner):
        output = AgentToolExecutor().execute(case.step, runtime_context=case.context)
    assert checked and output["data"]["business_success"] is False


def test_host_four_employee_sales_file_is_read_back_and_changed_bytes_fail(tmp_path, monkeypatch):
    from pathlib import Path

    from app.application.agent_orchestrator.approval_grant import issue_approval_grant
    from app.application.agent_orchestrator.approval_transaction import approve_and_enqueue
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.result_verification import (
        latest_step_call,
        verify_step_result,
    )
    from app.application.agent_orchestrator.task_background import task_execution_context
    from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher
    from app.application.agent_orchestrator.task_execution_sql_repository import (
        SQLAlchemyTaskExecutionRepository,
    )
    from app.application.employee_runtime import handoff_commit
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
    from tests.fixtures.employee_business_chain import (
        _ACTOR,
        EMPLOYEES,
        _artifacts,
        business_plan,
        business_workspace,
        invoke,
    )

    workspace = tmp_path / "actual-sales-chain"
    monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))
    with business_workspace(workspace):
        task_id = invoke(workspace, "start")["task_id"]
        context = {
            **_ACTOR.get(),
            "task_id": task_id,
            "employee_id": EMPLOYEES[0],
            "workspace_root": str(workspace),
            "workspace_path": str(workspace),
        }
        plan = PlanGraph(
            plan_id="original-sales-chain",
            intent="Generate the approved sales file",
            nodes=[
                WorkflowNode(
                    node_id="original-chain",
                    tool_id="employee",
                    action="execute",
                    risk="low",
                    params={
                        "employee_id": EMPLOYEES[0],
                        "task": "Generate the approved sales file",
                        "continuity_action": "chain",
                        "task_id": task_id,
                        "input": business_plan(),
                    },
                )
            ],
        )
        repository = handoff_commit.get_agent_run_repository()
        run = AgentOrchestrator(repository=repository).start_run_from_plan(
            user_id="11",
            message=plan.intent,
            plan=plan,
            runtime_context=context,
        )
        assert run.status == "waiting_user" and not run.tool_calls
        queue = SQLAlchemyTaskExecutionRepository()
        grant = issue_approval_grant(run, principal_id="11")
        queued = approve_and_enqueue(
            repository,
            queue,
            run_id=run.run_id,
            token=grant["grant"],
            principal_id="11",
            runtime_context={},
        )
        assert queued.status == "queued" and not queued.tool_calls
        claim = queue.claim("original-chain-worker", lease_seconds=120, run_id=run.run_id)
        assert claim is not None
        AgentTaskDispatcher(execution_repository=queue, run_repository=repository)._execute_claim(
            claim, "original-chain-worker"
        )
        run = repository.get(run.run_id)
        assert run.status == "completed", {
            "error": run.error,
            "recovery": run.metadata.get("recovery"),
            "verification": [item.metadata.get("verification") for item in run.tool_calls],
        }
        assert queue.get(run.run_id).state == "succeeded"
        step = run.steps[0]
        call = latest_step_call(run, step)
        context = {
            **run.metadata["runtime_context"],
            **task_execution_context(run, step),
            "run_id": run.run_id,
            "step_id": step.step_id,
            "node_id": step.node_id,
        }
        artifacts = _artifacts(workspace, task_id)
        assert len(artifacts) == 1
        before = ledger_path(workspace).read_bytes()
        report = verify_step_result(run=run, step=step, call=call, context=context)
        assert report["accepted"], report
        assert any(check["source"] == "run_artifact" for check in report["checks"])
        assert ledger_path(workspace).read_bytes() == before
        Path(artifacts[0]["path"]).write_bytes(b"changed original sales workbook")
        assert (
            verify_step_result(run=run, step=step, call=call, context=context)["accepted"] is False
        )
        assert ledger_path(workspace).read_bytes() == before
