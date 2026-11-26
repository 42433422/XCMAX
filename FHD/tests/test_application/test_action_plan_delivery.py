"""Exercise host-rendered plans without calling tools or a model provider."""

import json

import pytest

from app.application.agent_runtime.goal_verifier import verify_runtime_goal
from app.application.agent_runtime.plan_delivery import (
    plan_delivery_schema,
    render_action_plan,
)
from app.domain.task_lifecycle.agent_runtime_contract import (
    build_goal_contract,
    canonical_digest,
)
from app.infrastructure.xiaox.binding import XiaoxBinding
from app.infrastructure.xiaox.tools import XiaoxToolBridge
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_xiaox_goal_verifier import goal, response, review
from tests.test_application.test_xiaox_goal_verifier import verifier as verifier


@pytest.fixture
def plan(verifier, monkeypatch):
    verifier.run.message = "写出核对清单的方案"
    verifier.run.metadata.update(
        runtime_requested_deliverable="action_plan", plan_delivery_version=1
    )
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(
        verifier.run,
        context_evidence=[
            {
                "source": "desktop_navigation",
                "entries": [
                    {
                        "id": "inventory-checklist",
                        "label": "库存清单",
                        "breadcrumb": ["仓储"],
                        "kind": "page",
                    }
                ],
            }
        ],
    )
    verifier.rows = []
    monkeypatch.setattr(XiaoxToolBridge, "visible_actions", lambda *_: iter(()))
    verifier.binding = XiaoxBinding(verifier.run)
    verifier.verify_plan = lambda rendered: verify_runtime_goal(
        verifier.binding,
        verifier.config,
        rows=[],
        output=verifier.output,
        plan_delivery=rendered,
    )
    return verifier


def test_cannot_promote_reply_to_new_action_plan(plan):
    plan.output = "**方案** 调用 `lookup_tool.check_item`"
    fake = response(
        review(goal(plan.run.message, kind="reply", evidence_ids=["response"]))
    )
    plan.replies = [fake]
    delivery = render_action_plan(plan.binding, plan.output)
    report = plan.verify_plan(delivery)
    assert report["error_code"] == "plan_delivery_invalid"
    assert not report["accepted"] and not plan.requests
    assert plan.classify(report)[0] == "blocked"
    assert "lookup_tool" not in plan.classify(report)[1]["output"]


def test_existing_legacy_plan_keeps_its_original_contract(plan):
    plan.run.metadata.pop("plan_delivery_version")
    plan.run.metadata["runtime_goal_contract"] = build_goal_contract(plan.run)
    plan.output = "逐项确认库区、货架、托盘和标签。"
    plan.replies = [
        response(
            review(goal(plan.run.message, kind="reply", evidence_ids=["response"]))
        )
    ]
    report = plan.verify()
    assert plan.classify(report)[0] == "completed"
    assert "plan_delivery" not in report


@pytest.mark.parametrize("kind", ["steps", "narrative"])
def test_valid_plan_uses_current_navigation_and_has_no_execution_receipt(plan, kind):
    if kind == "steps":
        steps = [
            {"kind": "navigation", "navigation_id": "inventory-checklist", "inputs": {}}
        ]
    else:
        steps = ["按仓位列清单", "逐件核对实存"]
    raw = json.dumps({"plan": {"kind": kind, "steps": steps}}, ensure_ascii=False)
    delivery = render_action_plan(plan.binding, raw)
    plan.output = delivery.output
    assert delivery.proof, delivery.error
    assert delivery.proof["kind"] == kind
    assert delivery.proof["response_digest"] == canonical_digest(delivery.output)
    plan.replies = [
        response(
            review(goal(plan.run.message, kind="reply", evidence_ids=["response"]))
        )
    ]
    plan.replies = [
        response(
            {
                **review(
                    goal(plan.run.message, kind="reply", evidence_ids=["response"])
                ),
                "plan_content": kind,
            }
        )
    ]
    report = plan.verify_plan(delivery)
    assert report["accepted"]
    assert plan.classify(report)[0] == "completed"
    assert plan.classify(report)[1]["business_completed"] is False
    body = json.loads(plan.requests[0].content)
    prompt = json.loads(body["input"][1]["content"])
    assert not prompt["evidence"]
    assert prompt["verified_plan_delivery"]["kind"] == kind
    assert body["tools"] == []
    assert (
        "read"
        not in prompt["output_schema"]["$defs"]["GoalAssessment"]["properties"]["kind"][
            "enum"
        ]
    )
    if kind == "steps":
        assert "仓储 → 库存清单" in delivery.output
        schema = plan_delivery_schema(plan.binding)
        assert schema["$defs"]["NavigationStep"]["properties"]["navigation_id"][
            "enum"
        ] == ["inventory-checklist"]
        assert report["plan_delivery"]["navigation"] == ["inventory-checklist"]
    old = {
        key: value
        for key, value in report.items()
        if key not in {"report_digest", "plan_delivery"}
    }
    old["report_digest"] = canonical_digest(old)
    assert plan.classify(old)[0] == "blocked"


def test_fabricated_navigation_and_unavailable_branch_do_not_start_work(plan):
    raw = '{"plan":{"kind":"steps","steps":[{"kind":"navigation","navigation_id":"foreign","inputs":{}}]}}'
    report = plan.verify_plan(render_action_plan(plan.binding, raw))
    assert report["error_code"] == "plan_delivery_invalid" and not plan.requests

    raw = '{"plan":{"kind":"unavailable","reason":"missing_input"}}'
    delivery = render_action_plan(plan.binding, raw)
    report = plan.verify_plan(delivery)
    assert (
        report["error_code"] == "plan_delivery_unavailable" and not report["accepted"]
    )
    assert delivery.unavailable and not plan.requests


@pytest.mark.parametrize("fault", ["", "unknown", "params", "approval"])
def test_tool_step_uses_real_action_contract_without_running_it(
    plan, trusted_actor, monkeypatch, fault
):
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    actor = trusted_actor(permissions=["customer.view"])
    plan.run.user_id = str(actor.user_id)
    plan.run.metadata["runtime_context"] = actor.context
    plan.run.metadata["runtime_goal_contract"] = build_goal_contract(plan.run)
    raw = json.dumps(
        {
            "plan": {
                "kind": "steps",
                "steps": [
                    {
                        "kind": "tool",
                        "node_id": "lookup",
                        "tool_id": "customers",
                        "action": "unlisted" if fault == "unknown" else "query",
                        "params": {"unexpected_key": 1} if fault == "params" else {},
                        "depends_on": [],
                        "approval_required": fault == "approval",
                    }
                ],
            }
        }
    )
    delivery = render_action_plan(XiaoxBinding(plan.run), raw)
    if fault:
        assert delivery.error and not delivery.proof and not delivery.output
    else:
        assert delivery.proof, delivery.error
        assert "customers.query" in delivery.output
    assert not plan.requests


@pytest.mark.parametrize(
    "step, reported_kind, accepted",
    [
        ("调用 `inventory.imaginary` 生成清单", "narrative", False),
        ("使用 inventory.imaginary 生成清单", "steps", False),
        (
            "检查 `quantity` 字段，打开 `inventory.xlsx`，核对版本 `v1.2.3`。",
            "narrative",
            True,
        ),
    ],
)
def test_prose_cannot_pose_as_a_verified_tool(plan, step, reported_kind, accepted):
    raw = json.dumps(
        {"plan": {"kind": "narrative", "steps": [step]}}, ensure_ascii=False
    )
    delivery = render_action_plan(plan.binding, raw)
    plan.output = delivery.output
    plan.replies = [
        response(
            {
                **review(
                    goal(plan.run.message, kind="reply", evidence_ids=["response"])
                ),
                "plan_content": reported_kind,
            }
        )
    ]
    report = plan.verify_plan(delivery)
    assert report["accepted"] is accepted
    assert plan.classify(report)[0] == ("completed" if accepted else "blocked")
    if "inventory.imaginary" in step and "`" in step:
        assert report["error_code"] == "plan_delivery_invalid" and not plan.requests


def test_mixed_plan_keeps_plain_explanation_and_labels_manual_values(plan):
    raw = json.dumps(
        {
            "plan": {
                "kind": "steps",
                "steps": [
                    {
                        "kind": "navigation",
                        "navigation_id": "inventory-checklist",
                        "inputs": {"搜索词": "本月在库"},
                    }
                ],
                "notes": ["打开后可核对 `quantity` 字段。"],
            }
        },
        ensure_ascii=False,
    )
    delivery = render_action_plan(plan.binding, raw)
    assert "建议手填" in delivery.output and "在页面核对" in delivery.output
    assert "说明：打开后可核对 `quantity` 字段。" in delivery.output
    assert delivery.proof["navigation"] == ["inventory-checklist"]
    assert delivery.proof["tools"] == []


def test_wire_plan_schema_exposes_only_complete_step_variants(plan, monkeypatch):
    from types import SimpleNamespace

    from jsonschema import Draft202012Validator

    from app.infrastructure.xiaox.model_gateway import _prepare_body

    specs = [
        SimpleNamespace(tool_id="fixture_catalog", action="lookup"),
        SimpleNamespace(tool_id="fixture_documents", action="search"),
    ]
    monkeypatch.setattr(XiaoxToolBridge, "visible_actions", lambda *_: iter(specs))
    route = SimpleNamespace(
        model="fixture", max_output_tokens=400, gateway_kind="market", upstream_vendor="fixture"
    )
    schema = plan_delivery_schema(plan.binding)
    envelope = {"type": "json_schema", "name": "plan", "strict": True, "schema": schema}
    wire = _prepare_body({"model": "fixture", "text": {"format": envelope}}, route)
    assert wire["text"]["format"] == envelope
    Draft202012Validator.check_schema(schema)

    variants = schema["$defs"]["ActionSteps"]["properties"]["steps"]["items"]
    assert set(variants) == {"anyOf"}
    assert {entry["$ref"] for entry in variants["anyOf"]} == {
        "#/$defs/ToolStep",
        "#/$defs/NavigationStep",
    }
    tool = schema["$defs"]["ToolStep"]
    assert not {"oneOf", "anyOf", "not"} & tool.keys()
    assert (tool["type"], tool["additionalProperties"]) == ("object", False)
    assert set(tool["required"]) >= {"kind", "tool_id", "action", "node_id", "params"}
    assert tool["properties"]["tool_id"]["enum"] == [
        "fixture_catalog",
        "fixture_documents",
    ]
    assert tool["properties"]["action"]["enum"] == ["lookup", "search"]

    validator = Draft202012Validator(schema)
    incomplete = {"plan": {"kind": "steps", "steps": [{"action": "lookup"}]}}
    assert not validator.is_valid(incomplete)
    assert render_action_plan(plan.binding, json.dumps(incomplete)).proof is None
    complete = {
        "plan": {
            "kind": "steps",
            "steps": [
                {
                    "kind": "navigation",
                    "navigation_id": "inventory-checklist",
                    "inputs": {},
                }
            ],
        }
    }
    assert validator.is_valid(complete)
    assert render_action_plan(plan.binding, json.dumps(complete)).proof
    assert not plan.requests


def test_wire_omits_impossible_step_variants_without_removing_plain_plans(plan):
    from jsonschema import Draft202012Validator

    plan.run.metadata["runtime_goal_contract"] = build_goal_contract(plan.run)
    schema = plan_delivery_schema(plan.binding)
    assert [branch["$ref"] for branch in schema["properties"]["plan"]["anyOf"]] == [
        "#/$defs/NarrativePlan",
        "#/$defs/UnavailablePlan",
    ]
    assert "ToolStep" not in schema["$defs"] and "NavigationStep" not in schema["$defs"]
    assert "ActionSteps" not in schema["$defs"]
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    assert validator.is_valid(
        {"plan": {"kind": "narrative", "steps": ["Write a checklist."]}}
    )
    assert validator.is_valid(
        {"plan": {"kind": "unavailable", "reason": "missing_input"}}
    )
