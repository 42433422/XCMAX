"""Exercise real orchestration so planned actions cannot masquerade as executed work."""

from __future__ import annotations

import json
import logging
import runpy
from pathlib import Path

import pytest

from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.xiaox_http_runtime import dynamic_chat_runtime as dynamic_chat_runtime
from tests.fixtures.xiaox_http_runtime import runtime_entry as runtime_entry


@pytest.fixture
def execute_plan(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.setenv("XCAGI_AGENT_RUNTIME_HOOKS", "0")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    return runpy.run_path(str(Path(__file__).parents[1] / "benchmarks" / "task_success_runner.py"))[
        "_execute_plan"
    ]


@pytest.mark.parametrize("expected, passes", [("waiting_user", True), ("completed", False)])
def test_clarification_is_waiting_and_never_business_completion(
    execute_plan, monkeypatch, expected, passes
):
    from app.application.facades import tools_facade
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    calls = []
    monkeypatch.setattr(
        tools_facade, "execute_registered_workflow_tool", lambda *args: calls.append(args)
    )
    from app.application.workflow.clarification_node import build_clarify_node

    plan = PlanGraph(
        plan_id="clarify",
        intent="create",
        nodes=[
            build_clarify_node("请提供客户名称", ambient={"target_node_id": "write"}),
            WorkflowNode(
                node_id="write",
                tool_id="customers",
                action="create",
                params={"unit_name": "fixture"},
            ),
        ],
    )
    ok, reason, receipt = execute_plan(
        plan, {"instruction": "新增客户", "expect": {"run_status": expected}}
    )
    assert ok is passes
    assert receipt["status"] == "waiting_user"
    assert receipt["final_output"]["clarification"]["question"] == "请提供客户名称"
    assert not calls and not receipt["tool_calls"]
    assert bool(reason) is (not passes)


def test_benchmark_never_infers_approval_from_expected_success(execute_plan, monkeypatch):
    from app.application.facades import tools_facade
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    calls = []
    monkeypatch.setattr(
        tools_facade, "execute_registered_workflow_tool", lambda *args: calls.append(args)
    )
    plan = PlanGraph(
        plan_id="write",
        intent="create",
        nodes=[
            WorkflowNode(
                node_id="write",
                tool_id="business_db",
                action="write",
                params={
                    "entity": "customers",
                    "operation": "create",
                    "payload": {"unit_name": "fixture"},
                },
            ),
        ],
    )
    ok, reason, receipt = execute_plan(plan, {"instruction": "新增客户"})
    assert not ok and "waiting_user" in reason
    assert not calls and not receipt["tool_calls"]


def test_scripted_approval_requires_exact_pending_parameters(execute_plan, monkeypatch):
    from app.application.facades import tools_facade
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    calls = []
    monkeypatch.setattr(
        tools_facade, "execute_registered_workflow_tool", lambda *args: calls.append(args)
    )
    plan = PlanGraph(
        plan_id="write",
        intent="create",
        nodes=[
            WorkflowNode(
                node_id="write",
                tool_id="business_db",
                action="write",
                params={
                    "entity": "customers",
                    "operation": "create",
                    "payload": {"unit_name": "actual"},
                },
            ),
        ],
    )
    ok, reason, receipt = execute_plan(
        plan,
        {
            "instruction": "新增客户",
            "approvals": [
                {
                    "tool_id": "business_db",
                    "action": "write",
                    "params": {
                        "entity": "customers",
                        "operation": "create",
                        "payload": {"unit_name": "different"},
                    },
                },
            ],
        },
    )
    assert not ok and "does not match" in reason
    assert not calls and not receipt["tool_calls"]


def test_scripted_answer_resumes_but_does_not_approve_business_write(execute_plan):
    from app.application.workflow.clarification_node import build_clarify_node
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    plan = PlanGraph(
        plan_id="answer",
        intent="create",
        nodes=[
            build_clarify_node(
                "请提供客户",
                ambient={
                    "target_node_id": "create",
                    "clarification": {
                        "reason": "missing_required",
                        "missing_fields": ["unit_name"],
                    },
                },
            ),
            WorkflowNode(
                node_id="create",
                tool_id="customers",
                action="create",
                params={},
            ),
        ],
    )
    ok, reason, receipt = execute_plan(
        plan,
        {
            "instruction": "新增产品",
            "answers": [
                {"tool_id": "customers", "action": "create", "parameters": {"unit_name": "客户甲"}},
            ],
            "expect": {"run_status": "waiting_user"},
        },
    )
    assert ok and not reason
    assert receipt["steps"][0]["status"] == "completed"
    assert receipt["steps"][1]["status"] == "waiting_user"
    assert receipt["steps"][1]["params"]["unit_name"] == "客户甲"
    assert not receipt["tool_calls"]


@pytest.fixture
def execute_native_goal(dynamic_chat_runtime, monkeypatch):
    """Keep SQL, native input and approval boundaries real; replace only model I/O."""
    from app.db.bootstrap.seeding import seed_rbac
    from app.db.models.permission import Role

    state = dynamic_chat_runtime
    # The shared fixture's role is test-owned. Give this isolated benchmark DB
    # the same system role and grants that its production bootstrap requires.
    with state.actor.factory.begin() as db:
        db.query(Role).filter_by(name="admin").one().is_system = True
    seed_rbac(state.actor.factory.kw["bind"], logger=logging.getLogger(__name__))
    execute = runpy.run_path(
        str(Path(__file__).parents[1] / "benchmarks" / "task_success_runner.py")
    )["_execute_goal"]
    monkeypatch.setitem(execute.__globals__, "_trial_session_factory", lambda: state.actor.factory)
    return state, execute


@pytest.mark.parametrize("protocol", ["reply", "parameters"])
def test_native_scripted_answer_uses_the_original_parent_and_keeps_write_approval(
    execute_native_goal, protocol
):
    from app.db.models.purchase_unit import PurchaseUnit
    from app.domain.task_lifecycle.agent_runtime_contract import goal_answers

    state, execute = execute_native_goal
    answer = (
        {"reply": "客户甲"}
        if protocol == "reply"
        else {
            "tool_id": "customers",
            "action": "create",
            "parameters": {"unit_name": "客户甲"},
        }
    )
    turns = []

    def script(binding, _text):
        turns.append((binding.run.run_id, binding.run.user_id, binding.context))
        supplied = goal_answers(binding.run)
        if not supplied:
            return state.bridge.invoke(
                state.token, "request_input", {"question": "请提供客户名称"}
            )["question"]
        delivered = supplied[0]["answer"]
        if protocol == "reply":
            assert delivered == answer["reply"]
        else:
            assert json.loads(delivered.removeprefix("补充参数：")) == answer
        receipt = state.execute("customers", "create", {"unit_name": "客户甲"}, "create")
        assert receipt["pending_approval"] is True
        return "等待审批"

    state.script = script
    ok, reason, receipt, nodes = execute({"instruction": "新增客户", "answers": [answer]})
    assert not ok and "waiting_user" in reason
    assert len(turns) == len(state.transports) == 2
    assert turns[0][:2] == turns[1][:2] == (receipt["run_id"], receipt["user_id"])
    for key in ("tenant_id", "actor_id", "_actor_authorization"):
        assert turns[0][2][key] == turns[1][2][key]
    assert receipt["message"] == "新增客户"
    assert receipt["steps"][-1]["status"] == "waiting_user"
    assert receipt["steps"][-1]["params"] == {"unit_name": "客户甲"}
    assert [(node.tool_id, node.action) for node in nodes] == [("customers", "create")]
    assert not receipt["tool_calls"]
    with state.actor.factory() as db:
        assert db.query(PurchaseUnit).filter_by(unit_name="客户甲").count() == 0


@pytest.mark.parametrize("supplied_answers", [0, 1])
def test_native_wait_never_resumes_without_a_remaining_scenario_answer(
    execute_native_goal, supplied_answers
):
    from app.domain.task_lifecycle.agent_runtime_contract import goal_answers

    state, execute = execute_native_goal
    state.script = lambda _binding, _text: state.bridge.invoke(
        state.token, "request_input", {"question": "请提供仓库名称"}
    )["question"]
    answer = {
        "tool_id": "inventory",
        "action": "stock_in",
        "parameters": {"warehouse_name": "测试仓库"},
    }
    ok, reason, receipt, nodes = execute(
        {"instruction": "产品 C300 入库 12 件", "answers": [answer] * supplied_answers}
    )
    assert not ok and "waiting_user" in reason
    assert len(state.transports) == supplied_answers + 1
    parent = state.repository.get(receipt["run_id"])
    assert len(goal_answers(parent)) == supplied_answers
    assert parent.metadata["xiaox_runtime"]["waiting_input"]["question"] == "请提供仓库名称"
    assert nodes == receipt["steps"] == receipt["tool_calls"] == []


def test_native_answer_cannot_resume_while_a_child_write_needs_approval(execute_native_goal):
    from app.domain.task_lifecycle.agent_runtime_contract import goal_answers

    state, execute = execute_native_goal

    def script(_binding, _text):
        pending = state.execute("customers", "create", {"unit_name": "客户甲"}, "create")
        assert pending["pending_approval"] is True
        return state.bridge.invoke(state.token, "request_input", {"question": "请提供客户电话"})[
            "question"
        ]

    state.script = script
    ok, reason, receipt, _nodes = execute(
        {
            "instruction": "新增客户甲",
            "answers": [
                {
                    "tool_id": "customers",
                    "action": "create",
                    "parameters": {"contact_phone": "13900000003"},
                }
            ],
        }
    )
    assert not ok and "waiting_user" in reason
    assert len(state.transports) == 1
    assert goal_answers(state.repository.get(receipt["run_id"])) == []
    assert receipt["steps"][-1]["status"] == "waiting_user"
    assert receipt["steps"][-1]["params"] == {"unit_name": "客户甲"}
    assert not receipt["tool_calls"]
