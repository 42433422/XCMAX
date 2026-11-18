"""Schema-driven clarification reaches the same durable plan without widening input scope."""

from copy import deepcopy
from dataclasses import replace

import pytest

from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
from app.application.agent_orchestrator.clarification import ClarificationAnswerError
from app.application.workflow.clarification_inputs import input_field_schema, missing_tool_fields
from app.application.workflow.clarification_node import (
    build_clarify_node,
    detect_erp_clarification,
    needs_clarification,
)
from app.application.workflow.planning_graph_policy import (
    apply_clarification,
    validate_required_params,
)
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict


def test_idempotent_read_asks_for_required_input_from_execution_contract():
    node = WorkflowNode("read", "excel_toolkit", "view", {}, risk="low", idempotent=True)
    plan = PlanGraph("read-input", "读取附件", nodes=[node])
    item = needs_clarification(plan, {"excel_toolkit": {"actions": {"view": {}}}})[0]
    assert item["missing_fields"] == ["file_path"]
    assert "excel_toolkit.view" not in item["question"]


def test_schema_refs_nested_arrays_and_identity_fields():
    schema = {
        "type": "object",
        "required": ["user_id", "tenant_id", "payload"],
        "properties": {
            "payload": {"type": "array", "items": {"$ref": "#/$defs/row"}},
        },
        "$defs": {
            "row": {
                "type": "object",
                "required": ["user_id"],
                "properties": {"user_id": {"type": "integer", "title": "业务负责人"}},
            }
        },
    }
    meta = {"input_schema": schema}
    assert missing_tool_fields("fixture", "read", {"payload": [{}]}, meta) == ["payload.0.user_id"]
    assert input_field_schema(schema, "payload.0.user_id")["title"] == "业务负责人"
    assert missing_tool_fields("fixture", "read", {"payload": [{"user_id": 0}]}, meta) == []
    assert missing_tool_fields("fixture", "read", {"payload": "{{lookup.data}}"}, meta) == []


def test_unresolved_external_schema_never_fetches_network(monkeypatch):
    import urllib.request

    def unexpected_network(*args, **kwargs):
        pytest.fail("Schema discovery must not fetch remote references")

    monkeypatch.setattr(urllib.request, "urlopen", unexpected_network)
    schema = {"$ref": "https://example.invalid/tool-schema.json"}
    with pytest.raises(ValueError, match="不可解析"):
        missing_tool_fields("fixture", "read", {}, {"input_schema": schema})


def test_dependent_required_fields_are_asked_with_their_schema_path():
    schema = {
        "type": "object",
        "properties": {
            "payload": {
                "type": "object",
                "dependentRequired": {"country": ["city"]},
            }
        },
    }
    assert missing_tool_fields(
        "fixture", "read", {"payload": {"country": "CN"}}, {"input_schema": schema}
    ) == ["payload.city"]


def test_selected_target_still_requires_remaining_fields():
    node = WorkflowNode(
        "update",
        "customers",
        "update",
        {"id": 1, "_candidates": [{"id": 1}, {"id": 2}]},
        risk="high",
    )
    registry = {
        "customers": {
            "actions": {
                "update": {
                    "required_params": ["id", "contact_phone"],
                    "input_schema": {"properties": {"contact_phone": {"title": "联系电话"}}},
                }
            }
        }
    }
    item = needs_clarification(PlanGraph("update", "更新客户", nodes=[node]), registry)[0]
    assert item["missing_fields"] == ["contact_phone"]
    assert "联系电话" in item["question"]


def test_existing_question_is_not_rebound_to_another_kind():
    target = WorkflowNode("update", "customers", "update", {"_candidates": [{"id": 1}, {"id": 2}]})
    question = build_clarify_node(
        "旧问题：请补充邮箱",
        ambient={
            "target_node_id": "update",
            "clarification": {"reason": "missing_required"},
        },
    )
    registry = {
        "customers": {
            "actions": {
                "update": {
                    "required_params": ["id", "contact_phone"],
                    "input_schema": {"properties": {"contact_phone": {"title": "联系电话"}}},
                }
            }
        }
    }
    plan = apply_clarification(
        PlanGraph("refresh-question", "修改客户", nodes=[question, target]), registry
    )
    assert question.params["clarification"]["reason"] == "missing_required"
    assert question.params["clarification"]["missing_fields"] == ["contact_phone"]
    assert "联系电话" in question.params["question"] and "邮箱" not in question.params["question"]
    assert sum(node.tool_id == "clarify" for node in plan.nodes) == 2


@pytest.mark.parametrize(
    "message",
    [
        "出库 250kg，也就是 250 公斤",
        "出库 3 个 Google 型产品",
        "出库 3 箱 green 涂料",
    ],
)
def test_equivalent_units_and_names_do_not_trigger_conversion(message):
    node = WorkflowNode("out", "inventory", "stock_out", {"quantity": 3})
    assert not any(
        item["reason"] == "multi_unit"
        for item in detect_erp_clarification(
            PlanGraph("units", "出库", nodes=[node]),
            user_message=message,
        )
    )


def test_units_are_scoped_to_each_operation_and_item():
    nodes = [
        WorkflowNode("a", "inventory", "stock_out", {"quantity": "250公斤"}),
        WorkflowNode("b", "inventory", "stock_out", {"quantity": "3箱"}),
        WorkflowNode(
            "c",
            "sales",
            "quote",
            {
                "items": [
                    {"quantity": "2件"},
                    {"quantity": "4米"},
                ]
            },
        ),
    ]
    plan = PlanGraph("multi-unit-task", "多任务", nodes=nodes)
    assert not any(
        item["reason"] == "multi_unit"
        for item in detect_erp_clarification(
            plan,
            user_message="A 出库250公斤，B出库3箱，再给C报价2件和4米。",
        )
    )
    nodes[1].params["quantity"] = "3箱或30件"
    items = detect_erp_clarification(plan, user_message="保持其他任务")
    assert [(item["node_id"], item["reason"]) for item in items] == [("b", "multi_unit")]


def test_nested_answer_is_atomic_preserves_plan_and_requires_approval(monkeypatch):
    from app.application.agent_orchestrator import tool_spec
    from app.application.workflow_registry_app import get_workflow_tool_registry

    specs = dict(tool_spec.build_tool_specs_v2())
    original = specs[("customers", "create")]
    schema = deepcopy(original.input_schema)
    schema["properties"]["contacts"] = {
        "type": "array",
        "items": {
            "type": "object",
            "required": ["phone"],
            "properties": {"phone": {"type": "string", "title": "联系电话"}},
        },
    }
    specs[("customers", "create")] = replace(original, input_schema=schema)
    monkeypatch.setattr(tool_spec, "_TOOL_SPECS_CACHE", specs)
    target = WorkflowNode(
        "create", "customers", "create", {"unit_name": "客户甲", "contacts": [{}]}
    )
    plan = apply_clarification(
        PlanGraph("nested-input", "新增客户", nodes=[target]), get_workflow_tool_registry()
    )
    assert validate_required_params(plan, get_workflow_tool_registry()) is None
    orchestrator = AgentOrchestrator(repository=InMemoryAgentRunRepository())
    run = orchestrator.start_run_from_plan(user_id="owner", message="新增客户甲", plan=plan)
    assert run.status == "waiting_user"
    assert run.final_output["clarification"]["fields"] == [
        {"key": "contacts.0.phone", "label": "联系电话", "type": "string"},
    ]
    snapshot = deepcopy(run.metadata["plan"])
    for answer in (
        {"contacts.1.phone": "123"},
        {"contacts.0.phone": 123},
        {"contacts.0.phone": ""},
    ):
        with pytest.raises(ClarificationAnswerError):
            orchestrator.stage_clarification_answer(
                run.run_id, step_id=run.steps[0].step_id, parameters=answer, requested_by="owner"
            )
        assert run.metadata["plan"] == snapshot
        assert target.params["contacts"] == [{}]
    orchestrator.stage_clarification_answer(
        run.run_id,
        step_id=run.steps[0].step_id,
        parameters={"contacts.0.phone": "13800138000"},
        requested_by="owner",
    )
    continued = orchestrator.execute_dispatched_run(run.run_id)
    assert continued.run_id == run.run_id
    assert continued.steps[-1].params["contacts"] == [{"phone": "13800138000"}]
    assert continued.status == "waiting_user" and continued.tool_calls == []
    assert continued.metadata["plan"]["plan_id"] == plan_to_dict(plan)["plan_id"]


def test_ambiguous_target_and_other_missing_input_are_resolved_separately(monkeypatch):
    from app.application.agent_orchestrator import tool_spec
    from app.application.workflow_registry_app import get_workflow_tool_registry

    specs = dict(tool_spec.build_tool_specs_v2())
    original = specs[("customers", "update")]
    schema = deepcopy(original.input_schema)
    schema["required"] = ["id", "contact_phone"]
    schema["properties"]["contact_phone"] = {"type": "string", "title": "联系电话"}
    specs[("customers", "update")] = replace(original, input_schema=schema)
    monkeypatch.setattr(tool_spec, "_TOOL_SPECS_CACHE", specs)
    target = WorkflowNode(
        "update",
        "customers",
        "update",
        {
            "_candidates": [
                {"id": 1, "name": "客户甲"},
                {"id": 2, "name": "客户乙"},
            ]
        },
    )
    plan = apply_clarification(
        PlanGraph("two-questions", "更新客户", nodes=[target]), get_workflow_tool_registry()
    )
    assert len(plan.nodes) == 3
    assert validate_required_params(plan, get_workflow_tool_registry()) is None
    orchestrator = AgentOrchestrator(repository=InMemoryAgentRunRepository())
    run = orchestrator.start_run_from_plan(user_id="owner", message="更新客户电话", plan=plan)
    assert run.final_output["clarification"]["fields"] == [
        {"key": "contact_phone", "label": "联系电话", "type": "string"},
    ]
    orchestrator.stage_clarification_answer(
        run.run_id,
        step_id=run.steps[0].step_id,
        parameters={"contact_phone": "13800138000"},
        requested_by="owner",
    )
    run = orchestrator.execute_dispatched_run(run.run_id)
    assert run.status == "waiting_user" and run.steps[1].status == "waiting_user"
    assert run.tool_calls == [] and "id" not in run.steps[-1].params
    with pytest.raises(ClarificationAnswerError):
        orchestrator.stage_clarification_answer(
            run.run_id, step_id=run.steps[1].step_id, parameters={"id": 99}, requested_by="owner"
        )
    orchestrator.stage_clarification_answer(
        run.run_id, step_id=run.steps[1].step_id, parameters={"id": 2}, requested_by="owner"
    )
    run = orchestrator.execute_dispatched_run(run.run_id)
    assert run.status == "waiting_user" and run.tool_calls == []
    assert run.steps[-1].params == {"id": 2, "contact_phone": "13800138000"}
