"""The fixed executor dispatches one frozen graph and verifies durable graph receipts."""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.workflow.workflow_types import Branch, PlanGraph, WorkflowNode, plan_to_dict
from app.domain.task_lifecycle.agent_runtime_contract import frozen_workflow_operation
from app.infrastructure.codex.binding import CodexBindingError, CodexBindingStore, canonical_digest
from app.infrastructure.codex.tools import CodexToolBridge
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def graph_runtime(trusted_actor, monkeypatch, tmp_path):
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    actor = trusted_actor(permissions=["product.view", "customer.view", "tool.customers.create"])
    calls = []

    def dispatch(tool, action, params):
        calls.append((tool, action, params.get("keyword")))
        return {
            "success": True,
            "selected": True,
            "data": [{"id": 7, "model_number": "fixture", "price": 12}],
        }

    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", dispatch
    )

    def prepare(nodes):
        repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
        parent = AgentRun(user_id=str(actor.user_id), message="执行完整业务图", status="running")
        plan = plan_to_dict(PlanGraph(plan_id=f"plan_{parent.run_id}", intent="test", nodes=nodes))
        parent.metadata.update(
            runtime_context=actor.context,
            runtime_frozen_plan=plan,
            runtime_expected_operations=[frozen_workflow_operation(plan)],
        )
        repository.save(parent)
        store = CodexBindingStore(repository)
        grant = store.create(parent.run_id)
        orchestrator = AgentOrchestrator(
            repository=repository,
            tool_executor=SimpleNamespace(execute=AgentToolExecutor().execute),
        )
        bridge = CodexToolBridge(store, orchestrator)
        return SimpleNamespace(
            actor=actor,
            parent=parent,
            plan=plan,
            store=store,
            grant=grant,
            bridge=bridge,
            args={"call_id": "whole-plan", "plan_digest": canonical_digest(plan)},
            calls=calls,
        )

    return prepare


def read_node(name, **kwargs):
    return WorkflowNode(
        node_id=name, tool_id="products", action="query", params={"keyword": name}, **kwargs
    )


def test_multiple_goals_share_one_frozen_workflow_and_reopen_without_reexecution(graph_runtime):
    setup = graph_runtime([read_node("first"), read_node("second", depends_on=["first"])])
    receipt = setup.bridge.invoke(setup.grant.mcp_token, "execute_plan", setup.args)
    assert receipt["verified"] is True, receipt
    assert setup.calls == [("products", "query", "first"), ("products", "query", "second")]
    reopened = CodexToolBridge(
        CodexBindingStore(SQLAlchemyAgentRunRepository(session_factory=setup.actor.factory))
    )
    repeated = reopened.invoke(
        setup.grant.mcp_token, "execute_plan", {**setup.args, "call_id": "new-model-id"}
    )
    assert repeated["run_id"] == receipt["run_id"]
    assert repeated["verified"] is True
    assert len(setup.calls) == 2


def test_conditional_skips_are_checked_against_original_graph(graph_runtime):
    setup = graph_runtime(
        [
            read_node(
                "choose",
                branches=[Branch(condition={"key": "selected", "equals": True}, target="yes")],
                next="no",
            ),
            read_node("yes", depends_on=["choose"]),
            read_node("no", depends_on=["choose"]),
        ]
    )
    receipt = setup.bridge.invoke(setup.grant.mcp_token, "execute_plan", setup.args)
    assert receipt["verified"] is True, receipt
    assert [row[2] for row in setup.calls] == ["choose", "yes"]
    child = setup.store.repository.get(receipt["run_id"])
    selected = next(step for step in child.steps if step.node_id == "yes")
    selected.status = "skipped"
    from app.infrastructure.codex.workflow import validate_workflow_receipt

    binding = setup.store.get(setup.parent.run_id)
    call = binding.metadata["calls"][setup.args["call_id"]]
    assert validate_workflow_receipt(binding, call, child) is False
    assert len(setup.calls) == 2


def test_model_cannot_replace_or_split_frozen_graph(graph_runtime):
    setup = graph_runtime([read_node("read")])
    with pytest.raises(CodexBindingError, match="冻结目标"):
        setup.bridge.invoke(
            setup.grant.mcp_token, "execute_plan", {**setup.args, "plan_digest": "changed"}
        )
    with pytest.raises(CodexBindingError) as error:
        setup.bridge.invoke(
            setup.grant.mcp_token,
            "execute_action",
            {
                "call_id": "split",
                "tool_id": "products",
                "action": "query",
                "params": {"keyword": "read"},
            },
        )
    assert error.value.code == "goal_mismatch"
    assert setup.calls == []


def test_frozen_write_waits_on_original_child_approval(graph_runtime):
    setup = graph_runtime(
        [
            WorkflowNode(
                node_id="create",
                tool_id="customers",
                action="create",
                params={"unit_name": "fixture"},
                risk="high",
            )
        ]
    )
    receipt = setup.bridge.invoke(setup.grant.mcp_token, "execute_plan", setup.args)
    assert receipt["pending_approval"] is True
    assert receipt["verified"] is False
    assert receipt["approval_card"]["run_id"] == receipt["run_id"]
    assert setup.calls == []
    assert (
        setup.bridge.invoke(
            setup.grant.mcp_token, "execute_plan", {**setup.args, "call_id": "another"}
        )["run_id"]
        == receipt["run_id"]
    )


def test_mutated_child_params_fail_independent_receipt_validation(graph_runtime):
    setup = graph_runtime([read_node("read")])
    receipt = setup.bridge.invoke(setup.grant.mcp_token, "execute_plan", setup.args)
    assert receipt["verified"] is True
    child = setup.store.repository.get(receipt["run_id"])
    child.steps[0].params["keyword"] = "another target"
    child.metadata["plan"]["nodes"][0]["params"] = dict(child.steps[0].params)
    child.tool_calls[-1].params = dict(child.steps[0].params)
    setup.store.repository.save(child)
    with pytest.raises(CodexBindingError) as error:
        setup.bridge.invoke(
            setup.grant.mcp_token, "task_evidence", {"call_id": setup.args["call_id"]}
        )
    assert error.value.code == "evidence_mismatch"
    assert len(setup.calls) == 1


def ambiguous_reference(graph_runtime, monkeypatch):
    from app.application.customer_app_service import CustomerApplicationService

    setup = graph_runtime(
        [
            read_node("lookup"),
            WorkflowNode(
                node_id="create",
                tool_id="customers",
                action="create",
                params={"unit_name": "{{lookup.data[0].model_number}}"},
                depends_on=["lookup"],
                risk="high",
            ),
        ]
    )

    def dispatch(tool, action, params):
        setup.calls.append((tool, action, copy.deepcopy(params)))
        if action == "query":
            return {
                "success": True,
                "data": [
                    {"id": 7, "model_number": "first"},
                    {"id": 8, "model_number": "second"},
                ],
            }
        return CustomerApplicationService().create({"customer_name": params["unit_name"]})

    monkeypatch.setattr(
        "app.application.customer_app_service.get_customers_session", setup.actor.factory
    )
    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", dispatch
    )
    setup.receipt = setup.bridge.invoke(setup.grant.mcp_token, "execute_plan", setup.args)
    setup.child = setup.store.repository.get(setup.receipt["run_id"])
    setup.question = next(step for step in setup.child.steps if step.tool_id == "clarify")
    return setup


def answer_reference(setup):
    staged = setup.bridge.orchestrator.stage_clarification_answer(
        setup.child.run_id,
        step_id=setup.question.step_id,
        parameters={"id": 8},
        requested_by=str(setup.actor.user_id),
    )
    assert staged is not None and staged.run_id == setup.child.run_id
    return setup.bridge.orchestrator.execute_dispatched_run(staged.run_id)


def test_reference_selection_resumes_original_graph_then_waits_for_original_approval(
    graph_runtime, monkeypatch
):
    from app.application.agent_runtime.chat import runtime_chat_payload
    from app.domain.task_lifecycle.agent_runtime_results import classify_runtime_result

    setup = ambiguous_reference(graph_runtime, monkeypatch)
    receipt = setup.receipt
    assert receipt["status"] == "waiting_user"
    assert receipt["needs_user_input"] is True
    assert receipt["pending_approval"] is False and receipt["approval_card"] is None
    assert receipt["clarification"]["step_id"] == setup.question.step_id
    assert receipt["clarification"]["run_id"] == setup.child.run_id
    rows = list(setup.store.get(setup.parent.run_id).metadata["calls"].values())
    result = {"run_id": setup.parent.run_id, "output": "model says done"}
    assert classify_runtime_result(result, rows, {}, "business", "completed") == "waiting_user"
    payload = runtime_chat_payload(result)
    assert payload["data"]["needs_user_input"] is True
    assert payload["data"]["clarification"]["step_id"] == setup.question.step_id
    assert payload["data"]["clarification"]["run_id"] == setup.child.run_id
    assert "approval_card" not in payload["data"].get("data", {})

    child = answer_reference(setup)
    write = next(step for step in child.steps if step.node_id == "create")
    assert child.status == write.status == "waiting_user"
    assert write.params == {"unit_name": "second"}
    assert len(setup.calls) == 1
    waiting = setup.bridge.invoke(
        setup.grant.mcp_token, "task_evidence", {"call_id": setup.args["call_id"]}
    )
    assert waiting["pending_approval"] is True and waiting["needs_user_input"] is False
    assert waiting["approval_card"]["run_id"] == child.run_id
    completed = setup.bridge.orchestrator.continue_run(
        child.run_id,
        approved_by=str(setup.actor.user_id),
        approved_step_id=write.step_id,
        runtime_context=setup.actor.context,
    )
    assert completed.status == "completed", (completed.error, completed.final_output)
    reopened = CodexToolBridge(
        CodexBindingStore(SQLAlchemyAgentRunRepository(session_factory=setup.actor.factory))
    )
    final = reopened.invoke(setup.grant.mcp_token, "execute_plan", setup.args)
    assert final["verified"] is True, final
    assert final["run_id"] == setup.child.run_id
    assert [call[:2] for call in setup.calls] == [("products", "query"), ("customers", "create")]
    assert setup.calls[1][2]["unit_name"] == "second"
    assert setup.store.get(setup.parent.run_id).run.metadata["runtime_frozen_plan"] == setup.plan


def test_reference_selection_rejects_foreign_or_out_of_scope_answers(graph_runtime, monkeypatch):
    from app.application.agent_orchestrator.clarification import ClarificationAnswerError

    setup = ambiguous_reference(graph_runtime, monkeypatch)
    before = setup.child.to_dict()
    assert (
        setup.bridge.orchestrator.stage_clarification_answer(
            setup.child.run_id,
            step_id=setup.question.step_id,
            parameters={"id": 8},
            requested_by="another-owner",
        )
        is None
    )
    for parameters in ({"id": 999}, {"id": 8, "unit_name": "another target"}):
        with pytest.raises(ClarificationAnswerError):
            setup.bridge.orchestrator.stage_clarification_answer(
                setup.child.run_id,
                step_id=setup.question.step_id,
                parameters=parameters,
                requested_by=str(setup.actor.user_id),
            )
    assert setup.store.repository.get(setup.child.run_id).to_dict() == before
    assert len(setup.calls) == 1


@pytest.mark.parametrize(
    "tamper", ["missing_proof", "candidate", "selection", "author", "parameters", "new_node"]
)
def test_reference_amendment_cannot_replace_original_goal(graph_runtime, monkeypatch, tamper):
    from app.application.agent_orchestrator.run_models import AgentStep

    setup = ambiguous_reference(graph_runtime, monkeypatch)
    child = answer_reference(setup)
    proof = child.metadata["reference_clarifications"][setup.question.step_id]
    if tamper == "missing_proof":
        child.metadata["reference_clarifications"] = {}
    elif tamper == "candidate":
        proof["question_params"]["clarification"]["candidates"][1]["source_value"] = "new target"
    elif tamper == "selection":
        proof["answer"]["parameters"]["id"] = 7
    elif tamper == "author":
        proof["answer"]["answered_by"] = "another-owner"
    elif tamper == "parameters":
        write = next(step for step in child.steps if step.node_id == "create")
        write.params["contact_person"] = "unfrozen parameter"
        proof["answer"]["result_params"] = copy.deepcopy(write.params)
        for node in child.metadata["plan"]["nodes"]:
            if node["node_id"] == write.node_id:
                node["params"] = copy.deepcopy(write.params)
    else:
        child.steps.append(
            AgentStep(node_id="extra", tool_id="products", action="query", params={})
        )
        child.metadata["plan"]["nodes"].append(
            {"node_id": "extra", "tool_id": "products", "action": "query", "params": {}}
        )
    setup.store.repository.save(child)
    with pytest.raises(CodexBindingError) as error:
        setup.bridge.invoke(
            setup.grant.mcp_token, "task_evidence", {"call_id": setup.args["call_id"]}
        )
    assert error.value.code == "evidence_mismatch"
    assert len(setup.calls) == 1


def test_unknown_call_receipt_precedes_graph_amendment_checks_and_never_replays(
    graph_runtime, monkeypatch
):
    setup = ambiguous_reference(graph_runtime, monkeypatch)
    child = setup.child
    child.metadata["reference_clarifications"] = {}
    child.tool_calls[0].output = {
        "success": False,
        "outcome": "unknown",
        "reconciliation_required": True,
        "retryable": False,
    }
    setup.store.repository.save(child)
    receipt = setup.bridge.invoke(setup.grant.mcp_token, "execute_plan", setup.args)
    assert receipt["status"] == "unknown" and receipt["verified"] is False
    assert receipt["reconciliation_required"] is True and receipt["retryable"] is False
    assert receipt["run_id"] == child.run_id
    with pytest.raises(CodexBindingError) as error:
        setup.bridge.invoke(
            setup.grant.mcp_token, "execute_plan", {**setup.args, "call_id": "another-model-id"}
        )
    assert error.value.code == "reconciliation_required"
    assert len(setup.calls) == 1
