import pytest

from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
from app.application.agent_orchestrator.clarification import apply_clarification_answer
from app.application.workflow.clarification_node import build_clarify_node
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode


def test_named_quote_answer_stops_at_write_approval():
    params = {"items": [{"model_number": "A100", "quantity": 2, "unit_price": 50}]}
    question = build_clarify_node(
        "请提供客户名称",
        ambient={
            "target_node_id": "quote",
            "clarification": {"reason": "missing_required", "missing_fields": ["customer_name"]},
        },
    )
    quote = WorkflowNode(node_id="quote", tool_id="sales", action="quote", params=params)
    orchestrator = AgentOrchestrator(repository=InMemoryAgentRunRepository())
    run = orchestrator.start_run_from_plan(
        user_id="owner",
        message="报价",
        plan=PlanGraph(plan_id="named-quote", intent="sales", nodes=[question, quote]),
    )
    assert run.final_output["clarification"]["fields"] == [
        {"key": "customer_name", "label": "客户名称", "type": "string"}
    ]
    orchestrator.stage_clarification_answer(
        run.run_id,
        step_id=run.steps[0].step_id,
        parameters={"customer_name": "客户甲"},
        requested_by="owner",
    )
    continued = orchestrator.execute_dispatched_run(run.run_id)
    assert continued.status == "waiting_user"
    assert continued.steps[1].status == "waiting_user"
    assert continued.steps[1].params == {**params, "customer_name": "客户甲"}
    assert continued.tool_calls == []


def test_unit_confirmation_keeps_a_complete_sales_order():
    params = {
        "customer_name": "Linux 验收客户",
        "items": [{"model_number": "ACC-A", "quantity": 2, "unit_price": 100, "unit": "件"}],
    }
    question = build_clarify_node(
        "请确认单位",
        ambient={"target_node_id": "order", "clarification": {"reason": "multi_unit"}},
    )
    order = WorkflowNode(node_id="order", tool_id="sales", action="create_order", params=params)
    run = AgentOrchestrator(repository=InMemoryAgentRunRepository()).start_run_from_plan(
        user_id="owner",
        message="销售 2 件",
        plan=PlanGraph(plan_id="unit-order", intent="sales", nodes=[question, order]),
    )
    apply_clarification_answer(run, step_id=run.steps[0].step_id, parameters={}, confirmed=True)
    assert run.steps[0].status == "completed"
    assert run.steps[1].params == params


def test_answer_resolves_duplicate_missing_inputs_but_preserves_other_confirmation():
    nodes = [
        build_clarify_node(
            "请提供客户",
            ambient={
                "target_node_id": "write",
                "clarification": {"reason": reason, "missing_fields": ["unit_name"]},
            },
        )
        for reason in ("missing_required", "missing_required", "credit_limit_exceed")
    ]
    nodes.append(WorkflowNode(node_id="write", tool_id="customers", action="create", params={}))
    run = AgentOrchestrator(repository=InMemoryAgentRunRepository()).start_run_from_plan(
        user_id="u1",
        message="新增产品",
        plan=PlanGraph(plan_id="p", intent="create", nodes=nodes),
    )
    apply_clarification_answer(
        run, step_id=run.steps[0].step_id, parameters={"unit_name": "客户甲"}
    )
    assert [step.status for step in run.steps] == ["completed", "completed", "pending", "pending"]
    assert run.steps[3].params == {"unit_name": "客户甲"}


def test_clarification_metadata_does_not_share_mutable_candidates():
    detail = {"reason": "ambiguous_target", "candidates": [{"id": 1, "name": "客户甲"}]}
    node = build_clarify_node("请选择客户", ambient={"clarification": detail})
    detail["candidates"][0]["id"] = 99
    assert node.params["clarification"]["candidates"][0]["id"] == 1


def test_shipment_nested_answer_requires_approval_and_rejects_other_fields():
    from app.application.agent_orchestrator.clarification import ClarificationAnswerError

    params = {
        "unit_name": "客户甲",
        "products": [{"product_name": "产品甲", "quantity_tins": 2, "unit_price": 50}],
    }
    question = build_clarify_node(
        "请提供规格",
        ambient={
            "target_node_id": "shipment",
            "clarification": {
                "reason": "missing_required",
                "missing_fields": ["products.0.tin_spec"],
            },
        },
    )
    shipment = WorkflowNode(
        node_id="shipment", tool_id="shipment_records", action="create", params=params
    )
    orchestrator = AgentOrchestrator(repository=InMemoryAgentRunRepository())
    run = orchestrator.start_run_from_plan(
        user_id="owner",
        message="发货",
        plan=PlanGraph(plan_id="shipment-clarify", intent="shipment", nodes=[question, shipment]),
    )
    with pytest.raises(ClarificationAnswerError):
        orchestrator.stage_clarification_answer(
            run.run_id,
            step_id=run.steps[0].step_id,
            parameters={"products.1.tin_spec": 20},
            requested_by="owner",
        )
    orchestrator.stage_clarification_answer(
        run.run_id,
        step_id=run.steps[0].step_id,
        parameters={"products.0.tin_spec": 20},
        requested_by="owner",
    )
    continued = orchestrator.execute_dispatched_run(run.run_id)
    assert continued.status == "waiting_user"
    assert continued.steps[1].status == "waiting_user"
    assert continued.steps[1].params["products"][0]["tin_spec"] == 20
    assert continued.tool_calls == []


def _runtime_target_run(tool_id, action, params, source_outputs=None):
    from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
    from app.application.workflow.workflow_types import plan_to_dict

    sources = [
        AgentStep(
            node_id=node_id,
            tool_id="products",
            action="query",
            params={},
            status="completed",
            output=output,
            idempotent=True,
        )
        for node_id, output in (source_outputs or {}).items()
    ]
    step = AgentStep(
        node_id="target",
        tool_id=tool_id,
        action=action,
        params=params,
        risk="high",
        depends_on=[item.node_id for item in sources],
    )
    run = AgentRun(user_id="owner", message="执行", status="running", steps=[*sources, step])
    run.metadata["plan"] = plan_to_dict(
        PlanGraph(
            plan_id="runtime-answers",
            intent="execute",
            nodes=[
                WorkflowNode(
                    node_id=item.node_id,
                    tool_id=item.tool_id,
                    action=item.action,
                    params=item.params,
                    risk=item.risk,
                    depends_on=item.depends_on,
                    idempotent=item.idempotent,
                )
                for item in run.steps
            ],
        )
    )
    return run, step


def test_sales_customer_selection_preserves_complete_quote_inputs():
    from app.application.agent_orchestrator.clarification import pause_for_ambiguous_target
    from app.application.workflow.workflow_types import plan_from_dict

    params = {
        "customer_name": "客户",
        "items": [{"model_number": "A100", "quantity": 2, "unit_price": 50}],
    }
    run, target = _runtime_target_run("sales", "create_order", params)
    assert pause_for_ambiguous_target(
        run, target, [{"id": 7, "name": "客户甲"}, {"id": 8, "name": "客户乙"}], field="customer_id"
    )
    question = run.steps[0]
    apply_clarification_answer(run, step_id=question.step_id, parameters={"id": 8})
    assert question.status == "completed"
    assert target.params == {**params, "customer_id": 8}
    plan = plan_from_dict(run.metadata["plan"])
    assert next(node for node in plan.nodes if node.node_id == "target").params == target.params
    assert target.status == "pending" and run.tool_calls == []


def test_successive_target_selections_have_distinct_durable_nodes():
    from app.application.agent_orchestrator.clarification import pause_for_ambiguous_target
    from app.application.workflow.workflow_types import plan_from_dict, validate_plan_graph

    run, target = _runtime_target_run(
        "inventory", "stock_out", {"product_id": 1, "warehouse_id": 2, "quantity": 3}
    )
    questions = []
    for field, answer in (("product_id", 7), ("warehouse_id", 8)):
        assert pause_for_ambiguous_target(run, target, [{"id": 7}, {"id": 8}], field=field)
        question = next(step for step in run.steps if step.status == "waiting_user")
        questions.append(question)
        apply_clarification_answer(run, step_id=question.step_id, parameters={"id": answer})
    assert questions[0].node_id != questions[1].node_id
    assert all(question.status == "completed" for question in questions)
    assert target.params == {"product_id": 7, "warehouse_id": 8, "quantity": 3}
    plan = plan_from_dict(run.metadata["plan"])
    assert validate_plan_graph(plan) is None
    assert len({node.node_id for node in plan.nodes}) == len(plan.nodes)
    assert next(node for node in plan.nodes if node.node_id == "target").params == target.params
    assert target.status == "pending" and run.tool_calls == []


@pytest.mark.parametrize(
    ("nested", "field", "projection", "expected"),
    [
        (True, "product_id", "id", 8),
        (True, "quantity", "quantity", 40),
        (False, "quantity", "quantity", 40),
    ],
)
def test_runtime_selection_preserves_destination_and_source_projection(
    nested, field, projection, expected
):
    from copy import deepcopy

    from app.application.agent_orchestrator.clarification import ClarificationAnswerError
    from app.application.agent_orchestrator.param_references import refuse_unresolved_step
    from app.application.agent_orchestrator.run_models import agent_run_from_dict
    from app.application.workflow.workflow_types import plan_from_dict

    params = (
        {
            "customer_name": "客户甲",
            "items": [{"product_id": 1, "model_number": "A100", "quantity": 2, "unit_price": 50}],
        }
        if nested
        else {"product_id": 1, "warehouse_id": 2, "quantity": 2}
    )
    destination = params["items"][0] if nested else params
    destination[field] = "{{lookup.data[0]." + projection + "}}"
    outputs = {"lookup": {"data": [{"id": 7, "quantity": 20}, {"id": 8, "quantity": 40}]}}
    tool_id, action = ("sales", "create_order") if nested else ("inventory", "stock_out")
    run, target = _runtime_target_run(tool_id, action, params, outputs)
    assert refuse_unresolved_step(run, target, outputs)
    # Resuming from durable JSON must not depend on the old process's row objects.
    run = agent_run_from_dict(deepcopy(run.to_dict()))
    _, question, target = run.steps
    before = deepcopy(run.to_dict())
    with pytest.raises(ClarificationAnswerError, match="候选"):
        apply_clarification_answer(run, step_id=question.step_id, parameters={"id": 999})
    assert run.to_dict() == before
    apply_clarification_answer(run, step_id=question.step_id, parameters={"id": 8})
    expected_params = deepcopy(params)
    expected_destination = expected_params["items"][0] if nested else expected_params
    expected_destination[field] = expected
    assert target.params == expected_params
    plan = plan_from_dict(run.metadata["plan"])
    assert next(node for node in plan.nodes if node.node_id == "target").params == expected_params
    assert not refuse_unresolved_step(run, target, outputs)
    assert question.status == "completed" and target.status == "pending"
    assert run.tool_calls == []
