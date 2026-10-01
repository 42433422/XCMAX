"""Clarification gating, resume routing, expiry and target resolution tests."""

from __future__ import annotations

import pytest

from app.application.workflow.clarification_node import (
    build_clarify_node,
    entry_is_expired,
    insert_clarify_node,
    make_pending_entry,
    needs_clarification,
    resolve_confirmed_target,
    sweep_expired,
)
from app.application.workflow.engine import WorkflowEngine
from app.application.workflow.types import Branch, PlanGraph, WorkflowNode


def _customers_registry() -> dict:
    return {
        "customers": {
            "actions": {
                "query": {"risk": "low", "idempotent": True},
                "delete": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["id"],
                },
            }
        }
    }


def _ambiguous_delete_plan() -> PlanGraph:
    """删除客户：存在多个同名候选，id 未解析。"""
    delete_node = WorkflowNode(
        node_id="delete_customer",
        tool_id="customers",
        action="delete",
        params={
            "_candidates": [
                {"id": "cust_1", "name": "北京智造科技"},
                {"id": "cust_2", "name": "北京智造科技"},
            ]
        },
        risk="high",
        idempotent=False,
        description="删除客户",
    )
    return PlanGraph(
        plan_id="p_delete",
        intent="delete_customer",
        todo_steps=["查询候选", "确认目标", "删除客户"],
        nodes=[delete_node],
        risk_level="high",
    )


def _executed(engine, plan, runtime_context=None):
    result = engine.run(plan, runtime_context=runtime_context or {})
    return result, set(result.final_context["workflow_status"]["executed_nodes"])


class TestNeedsClarification:
    def test_ambiguous_candidates_requires_clarification(self):
        plan = _ambiguous_delete_plan()
        items = needs_clarification(plan, _customers_registry())
        assert len(items) == 1
        item = items[0]
        assert item["node_id"] == "delete_customer"
        assert item["reason"] == "ambiguous_target"
        assert item["field"] == "id"
        assert len(item["candidates"]) == 2
        assert "多个候选目标" in item["question"]

    def test_missing_required_param_requires_clarification(self):
        plan = PlanGraph(
            plan_id="p_missing",
            intent="delete_customer",
            nodes=[
                WorkflowNode(
                    node_id="delete_customer",
                    tool_id="customers",
                    action="delete",
                    params={},  # 缺少必填 id
                    risk="high",
                    idempotent=False,
                )
            ],
        )
        items = needs_clarification(plan, _customers_registry())
        assert len(items) == 1
        assert items[0]["reason"] == "missing_required"
        assert items[0]["missing_fields"] == ["id"]

    def test_read_only_nodes_do_not_require_clarification(self):
        plan = PlanGraph(
            plan_id="p_read",
            intent="query",
            nodes=[
                WorkflowNode(
                    node_id="query_customers",
                    tool_id="customers",
                    action="query",
                    params={},
                    risk="low",
                    idempotent=True,
                )
            ],
        )
        assert needs_clarification(plan, _customers_registry()) == []


class TestEngineClarificationGate:
    def _make_engine(self):
        deleted: list[str] = []

        def dispatch(tool_id, action, params):
            if action == "delete":
                deleted.append(str(params.get("_runtime_context", {}).get("message", "")))
                return {"success": True, "data": {"deleted": params.get("id")}}
            return {"success": True}

        engine = WorkflowEngine(tool_dispatcher=dispatch)
        return engine, deleted

    def test_clarify_node_pauses_without_executing_delete(self):
        engine, deleted = self._make_engine()
        plan = _ambiguous_delete_plan()
        item = needs_clarification(plan, _customers_registry())[0]
        clarify = build_clarify_node(
            item["question"], ambient={"target_node_id": "delete_customer"}
        )
        insert_clarify_node(plan, clarify)

        result = _executed(engine, plan)[0]
        # 反问节点执行成功（暂停），但删除节点被屏蔽，未真正执行业务工具。
        assert result.success is True
        assert deleted == []
        clarify_result = next(r for r in result.node_results if r.tool_id == "clarify")
        assert clarify_result.output.get("requires_confirmation") is True
        assert clarify_result.output.get("question")

    def test_confirmation_routes_back_to_delete_node(self):
        engine, deleted = self._make_engine()
        plan = _ambiguous_delete_plan()
        item = needs_clarification(plan, _customers_registry())[0]
        clarify = build_clarify_node(
            item["question"], ambient={"target_node_id": "delete_customer"}
        )
        insert_clarify_node(plan, clarify)

        target = next(n for n in plan.nodes if n.node_id == "delete_customer")
        confirmed = resolve_confirmed_target("1", item["candidates"])
        assert confirmed == {"id": "cust_1"}
        target.params.update(confirmed)
        target.params.pop("_candidates", None)

        runtime_context = {
            "message": "确认删除 1",
            "_clarify_answers": {clarify.node_id: {"confirmed": True, **confirmed}},
        }
        result = _executed(engine, plan, runtime_context)[0]
        assert result.success is True
        assert "delete_customer" in {r.node_id for r in result.node_results if r.success}
        assert deleted == ["确认删除 1"]
        clarify_output = next(r.output for r in result.node_results if r.tool_id == "clarify")
        assert clarify_output.get("answer_confirmed") is True


class TestBuildClarifyNode:
    def test_builds_clarify_node_with_branch_to_target(self):
        node = build_clarify_node(
            "确定删除哪个客户？",
            ambient={"target_node_id": "delete_customer", "answer_key": "id"},
        )
        assert node.tool_id == "clarify"
        assert node.action == "ask"
        assert node.params["question"] == "确定删除哪个客户？"
        assert node.params["answer_key"] == "id"
        assert node.params["target_node_id"] == "delete_customer"
        assert node.branches == [
            Branch(target="delete_customer", condition={"key": "answer_confirmed", "equals": True})
        ]

    def test_insert_is_idempotent(self):
        plan = PlanGraph(plan_id="p", intent="x", nodes=[])
        node = build_clarify_node("q", ambient={"target_node_id": "delete_customer"})
        insert_clarify_node(plan, node)
        insert_clarify_node(plan, node)
        assert len(plan.nodes) == 1


class TestClarificationTTL:
    def test_expired_clarification_is_swept(self):
        pending = {
            "u1": make_pending_entry(
                plan=_ambiguous_delete_plan(),
                runtime_context={},
                thinking_steps="s",
                clarification={},
                clarify_node_id="clarify_1",
                target_node_id="delete_customer",
                now=1000.0,
            )
        }
        assert entry_is_expired(pending["u1"], now=1000.0 + 60) is False
        assert entry_is_expired(pending["u1"], now=1000.0 + 2000) is True
        expired = sweep_expired(pending, now=1000.0 + 2000)
        assert expired == ["u1"]
        assert "u1" not in pending  # 自动取消，不堆积

    def test_non_clarification_pending_is_not_swept(self):
        pending = {"u1": {"kind": "confirmation", "created_at": 1.0, "ttl_seconds": 30}}
        assert sweep_expired(pending, now=1000.0 + 2000) == []
        assert "u1" in pending


class TestResolveConfirmedTarget:
    CANDIDATES = [
        {"id": "cust_1", "name": "北京智造科技"},
        {"id": "cust_2", "name": "北京智造科技"},
    ]

    def test_resolve_by_index(self):
        assert resolve_confirmed_target("1", self.CANDIDATES) == {"id": "cust_1"}
        assert resolve_confirmed_target("2", self.CANDIDATES) == {"id": "cust_2"}

    def test_resolve_by_unique_id(self):
        assert resolve_confirmed_target("cust_2", self.CANDIDATES) == {"id": "cust_2"}

    def test_resolve_by_name(self):
        assert resolve_confirmed_target("北京智造科技", self.CANDIDATES) == {"id": "cust_1"}

    def test_unresolvable_returns_none(self):
        assert resolve_confirmed_target("3", self.CANDIDATES) is None
        assert resolve_confirmed_target("", self.CANDIDATES) is None
        assert resolve_confirmed_target("随便", []) is None


def _stock_out_plan(quantity: str) -> PlanGraph:
    return PlanGraph(
        plan_id="p1",
        intent="出库",
        todo_steps=["出库"],
        nodes=[
            WorkflowNode(
                node_id="out_node",
                tool_id="inventory",
                action="stock_out",
                params={"product_id": 1, "warehouse_id": 1, "quantity": quantity},
                risk="high",
                idempotent=False,
            )
        ],
        risk_level="high",
    )


def _report_plan() -> PlanGraph:
    return PlanGraph(
        plan_id="p2",
        intent="销售报表",
        todo_steps=["报表"],
        nodes=[
            WorkflowNode(
                node_id="report_node",
                tool_id="reports",
                action="sales_summary",
                params={},
                risk="low",
                idempotent=True,
            )
        ],
        risk_level="low",
    )


class TestErpClarification:
    """detect_erp_clarification：多单位/报表口径/冲销确认/批量范围。"""

    def test_multi_unit_asks_question(self):
        from app.application.workflow.clarification_node import detect_erp_clarification

        items = detect_erp_clarification(_stock_out_plan("500"), user_message="出 500 斤")
        assert items, "「出 500 斤」应触发多单位反问"
        assert items[0]["reason"] == "multi_unit"
        assert items[0]["severity"] in ("high", "medium")

    def test_multi_unit_does_not_execute_directly(self):
        from app.application.workflow.clarification_node import detect_erp_clarification

        items = detect_erp_clarification(_stock_out_plan("500"), user_message="出 500 斤")
        assert items, "反问存在，说明未直接执行"
        # 反问节点语义：不调用业务工具，仅产出 requires_confirmation=true
        clarify = build_clarify_node(
            items[0]["question"], {"node_id": "c1", "target_node_id": "out_node"}
        )
        assert clarify.tool_id == "clarify" and clarify.action == "ask"

    def test_no_ambiguity_when_plain_quantity(self):
        from app.application.workflow.clarification_node import detect_erp_clarification

        items = detect_erp_clarification(_stock_out_plan("500"), user_message="出库 500")
        assert not any(i["reason"] == "multi_unit" for i in items)

    def test_report_scope_missing_date_and_group(self):
        from app.application.workflow.clarification_node import detect_erp_clarification

        items = detect_erp_clarification(_report_plan(), user_message="看下销售")
        reasons = {i["reason"] for i in items}
        assert "report_scope" in reasons

    def test_reversal_confirm(self):
        from app.application.workflow.clarification_node import detect_erp_clarification

        plan = PlanGraph(
            plan_id="p3",
            intent="冲销",
            todo_steps=["冲销"],
            nodes=[
                WorkflowNode(
                    node_id="je",
                    tool_id="finance",
                    action="journal_entry_create",
                    params={"lines": [{"account_code": "1001", "debit": 100}]},
                    risk="high",
                    idempotent=False,
                )
            ],
            risk_level="high",
        )
        items = detect_erp_clarification(plan, user_message="冲销这笔分录")
        assert any(i["reason"] == "reversal_confirm" for i in items)

    def test_new_write_tools_in_fallback(self):
        from app.application.workflow.clarification_node import _WRITE_REQUIRED_FALLBACK

        assert ("sales", "quote") in _WRITE_REQUIRED_FALLBACK
        assert ("finance", "journal_entry_create") in _WRITE_REQUIRED_FALLBACK


_SHIPMENT_ITEM = {
    "product_name": "Paint",
    "quantity_tins": 1,
    "tin_spec": 10,
    "unit_price": 1,
    "amount": 10,
}
_SHIPMENT_ALIAS = {**_SHIPMENT_ITEM}
_SHIPMENT_ALIAS["name"] = _SHIPMENT_ALIAS.pop("product_name")
_SHIPMENT_ALIAS["spec_per_tin"] = _SHIPMENT_ALIAS.pop("tin_spec")


@pytest.mark.parametrize(
    "params,expected",
    [
        ({"unit_name": "待用户提供"}, ["unit_name", "products"]),
        ({"unit_name": "Co", "products": "invalid"}, ["products"]),
        ({"unit_name": "Co", "products": ["invalid"]}, ["products.0"]),
        ({"unit_name": "Co", "products": [_SHIPMENT_ITEM]}, []),
        ({"purchase_unit": "Co", "items": [_SHIPMENT_ALIAS]}, []),
        *[
            (
                {"unit_name": "Co", "products": [{**_SHIPMENT_ITEM, key: value}]},
                [f"products.0.{key}"],
            )
            for key, value in [
                ("quantity_tins", None),
                ("tin_spec", None),
                ("unit_price", None),
                ("amount", None),
                ("product_name", "待用户提供"),
                ("quantity_tins", 1.5),
                ("amount", float("nan")),
                ("quantity_tins", True),
                ("amount", float("inf")),
                ("unit_price", -1),
                ("amount", 10**1000),
            ]
        ],
    ],
)
def test_shipment_inputs_shared_by_clarification_and_execution(params, expected):
    from unittest.mock import MagicMock, patch

    from app.application.agent_orchestrator.tool_spec import validate_tool_call
    from app.services.tools_execution.registry import _validate_required_params
    from app.services.tools_workflow_shipments_docs import _registered_router_shipment_records

    params = {**params, "contact_person": "Alice", "contact_phone": "1234"}
    node = WorkflowNode(
        node_id="create",
        tool_id="shipment_records",
        action="create",
        params=params,
        risk="high",
        idempotent=False,
    )
    plan = PlanGraph(plan_id="shipment", intent="create", nodes=[node])
    clarification = needs_clarification(plan, {})
    assert (clarification[0]["missing_fields"] if clarification else []) == expected
    assert _validate_required_params("shipment_records", "create", params)[0] is (not expected)
    assert validate_tool_call("shipment_records", "create", params).ok is (not expected)
    svc = MagicMock()
    svc.create_shipment.return_value = {"success": True}
    with patch("app.bootstrap.get_shipment_app_service", return_value=svc):
        result = _registered_router_shipment_records("create", params, {}, "admin", "")
    assert result["success"] is (not expected)
    assert svc.create_shipment.call_count == (0 if expected else 1)
    if not expected:
        for key in ("contact_person", "contact_phone"):
            assert svc.create_shipment.call_args.kwargs[key] == params[key]
