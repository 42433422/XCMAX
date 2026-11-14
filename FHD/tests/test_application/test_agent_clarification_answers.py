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
    import pytest

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
