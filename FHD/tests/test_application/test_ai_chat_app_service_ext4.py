"""Active Excel helpers and unified model-plan contracts; no retired dispatch brain.

Removed internal source classifiers are covered through process_chat, model admission,
registered authenticated tools and the durable approval/session regression suites.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from app.application.ai_chat_app_service import AIChatApplicationService
from tests.test_application.ai_chat_test_helpers import (
    _make_svc as _make_service,
)


class TestCustomerHintFromPreviewGrid:
    def test_with_customer_column(self):
        service = _make_service()
        preview_data = {
            "grid_preview": {
                "rows": [
                    [{"text": "客户"}, {"text": "产品名称"}, {"text": "单价"}],
                    [{"text": "公司A"}, {"text": "涂料"}, {"text": "100"}],
                ]
            }
        }
        with patch(
            "app.application.template_grid_core._extract_inline_customer_hits_from_cell",
            return_value=["公司A"],
        ):
            result = service._customer_hint_from_preview_grid(preview_data)
        assert "公司A" in result

    def test_empty_grid(self):
        service = _make_service()
        result = service._customer_hint_from_preview_grid({})
        assert result == ""

    def test_no_rows(self):
        service = _make_service()
        result = service._customer_hint_from_preview_grid({"grid_preview": {"rows": []}})
        assert result == ""

    def test_non_dict_preview(self):
        service = _make_service()
        result = service._customer_hint_from_preview_grid("not a dict")
        assert result == ""

    def test_no_grid_preview_key(self):
        service = _make_service()
        result = service._customer_hint_from_preview_grid({"other_key": []})
        assert result == ""


class TestDefaultPurchaseUnitForImport:
    def test_with_unit_name_in_context(self):
        service = _make_service()
        result = service._default_purchase_unit_for_import(
            {"unit_name": "公司A"},
            {"grid_preview": {"rows": []}},
            {"excel_customer_hint": "公司A"},
        )
        assert "公司A" in result

    def test_with_guess_from_file(self):
        service = _make_service()
        result = service._default_purchase_unit_for_import(
            {"file_name": "某某有限公司报价表.xlsx"},
            {"grid_preview": {"rows": []}},
        )
        assert isinstance(result, str)

    def test_empty_context(self):
        service = _make_service()
        result = service._default_purchase_unit_for_import({}, {})
        assert result == ""


class TestTryStructuredReloadRecords:
    def test_no_excel_analysis(self):
        service = _make_service()
        result = service._try_structured_reload_records({}, {})
        assert result is None

    def test_no_file_path(self):
        service = _make_service()
        result = service._try_structured_reload_records({"file_path": ""}, {})
        assert result is None

    def test_with_nonexistent_file_path(self):
        service = _make_service()
        excel_analysis = {"file_path": "/nonexistent.xlsx"}
        result = service._try_structured_reload_records(excel_analysis, {})
        assert result is None


class TestResolveUnitPriceColumn:
    def test_single_price_column(self):
        col, err = AIChatApplicationService._resolve_unit_price_column(
            keys=["产品名称", "单价", "数量"],
            current="",
            user_message="",
            overrides={},
        )
        assert col == "单价"
        assert err is None

    def test_ambiguous_price_columns(self):
        # When both before and after price columns exist AND user says both, it's ambiguous
        col, err = AIChatApplicationService._resolve_unit_price_column(
            keys=["产品名称", "调价前单价", "调价后单价"],
            current="",
            user_message="导入调价前和调价后",
            overrides={},
        )
        assert err == "ambiguous_price_columns"

    def test_override_resolves_ambiguity(self):
        col, err = AIChatApplicationService._resolve_unit_price_column(
            keys=["产品名称", "调价前单价", "调价后单价"],
            current="",
            user_message="",
            overrides={"unit_price": "调价前单价"},
        )
        assert col == "调价前单价"
        assert err is None

    def test_user_message_before_price(self):
        col, err = AIChatApplicationService._resolve_unit_price_column(
            keys=["产品名称", "调价前单价", "调价后单价"],
            current="",
            user_message="导入调价前",
            overrides={},
        )
        assert col == "调价前单价"

    def test_no_price_columns(self):
        col, err = AIChatApplicationService._resolve_unit_price_column(
            keys=["产品名称", "数量"],
            current="",
            user_message="",
            overrides={},
        )
        assert col == ""
        assert err is None

    def test_current_already_set(self):
        col, err = AIChatApplicationService._resolve_unit_price_column(
            keys=["产品名称", "单价"],
            current="单价",
            user_message="",
            overrides={},
        )
        assert col == "单价"


# Migration map: old normal/pro dispatch and response overlays now use one
# model-authored graph. Real reads below cover products/customers/shipment_records;
# signed write/readback isolation is in test_owned_business_tool_isolation;
# persisted approval consumption/cancel/resume is in test_approval_session_renewal.
# Regex order assembly/model splitting is not a second planner: the complete
# structured shipment parameters must survive model admission unchanged.
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _model_plan(payload, message="查询产品", source="normal"):
    import json

    from app.application.workflow.planner import LLMWorkflowPlanner
    from app.application.workflow_registry_app import get_workflow_tool_registry

    completion = Mock(return_value={"choices": [{"message": {"content": json.dumps(payload)}}]})
    planner = LLMWorkflowPlanner(
        ai_service=Mock(get_context=Mock(return_value=None)), completion=completion
    )
    plan = planner.plan("test", message, get_workflow_tool_registry(), {"source": source})
    completion.assert_called_once()
    return plan


@pytest.mark.parametrize("source", ["normal", "pro", None])
@pytest.mark.parametrize(
    "tool,action,params",
    [
        ("products", "query", {"keyword": "涂料"}),
        ("products", "query", {"model_number": "5003A"}),
        ("customers", "query", {"keyword": "公司A"}),
        ("shipment_records", "query", {"unit_name": "公司A"}),
        ("customers", "create", {"unit_name": "公司A"}),
        (
            "shipment_orders",
            "generate",
            {
                "unit_name": "公司A",
                "products": [{"model_number": "5003A", "quantity": 10, "specification": "20kg"}],
            },
        ),
    ],
)
def test_model_structured_tools_use_same_registered_plan_for_every_source(
    source, tool, action, params
):
    from app.application.workflow.workflow_types import plan_fingerprint

    payload = {
        "intent": "用户指定业务",
        "nodes": [{"node_id": "business", "tool_id": tool, "action": action, "params": params}],
    }
    plan = _model_plan(payload, source=source)
    assert not plan.metadata.get("planning_rejected"), plan.metadata
    assert [(n.tool_id, n.action, n.params) for n in plan.nodes] == [(tool, action, params)]
    before = plan_fingerprint(plan)
    # Changing caller-owned model data cannot mutate the admitted/frozen plan.
    payload["nodes"][0]["params"] = {"unexpected": True}
    assert plan_fingerprint(plan) == before
    if action in {"create", "generate"}:
        from app.application.workflow.risk_gate import HybridRiskGate

        decision = HybridRiskGate().evaluate(plan, {})
        assert decision.requires_confirmation or not decision.allowed


@pytest.mark.parametrize(
    "tool,action,params",
    [
        ("unknown_tool", "execute", {}),
        ("products", "unknown_action", {}),
        ("customers", "create", {}),
        ("shipment_orders", "generate", {"unit_name": "公司A"}),
    ],
)
def test_unknown_or_incomplete_business_plan_cannot_dispatch(tool, action, params):
    plan = _model_plan(
        {"intent": "业务", "nodes": [{"tool_id": tool, "action": action, "params": params}]}
    )
    if tool == "unknown_tool" or action == "unknown_action":
        assert plan.metadata.get("planning_rejected") is True
        assert all(node.tool_id == "clarify" for node in plan.nodes)
    else:
        assert plan.nodes[0].tool_id == "clarify"
        assert plan.nodes[0].action == "ask"
        assert plan.nodes[1].params == params
        assert plan.nodes[1].tool_id == tool


@pytest.mark.parametrize(
    "tool,permission",
    [
        ("products", "product.view"),
        ("customers", "customer.view"),
        ("shipment_records", "shipment.view"),
    ],
)
@pytest.mark.parametrize("has_rows", [True, False])
def test_current_business_queries_read_real_rows_and_require_permission(
    trusted_actor, monkeypatch, tool, permission, has_rows
):
    from app.application.agent_orchestrator.run_models import AgentStep
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
    from app.db.models import Product, PurchaseUnit
    from app.db.models.shipment import ShipmentRecord
    from app.infrastructure.tenant_scope import tenant_scope

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    actor = trusted_actor(permissions=[permission])
    denied = trusted_actor(role="restricted", permissions=[])
    if has_rows:
        with tenant_scope(7), actor.factory.begin() as db:
            db.add(Product(tenant_id=7, name="涂料", model_number="5003A"))
            db.add(PurchaseUnit(tenant_id=7, unit_name="公司A"))
            db.add(
                ShipmentRecord(
                    tenant_id=7,
                    purchase_unit="公司A",
                    product_name="涂料",
                    quantity_tins=1,
                    quantity_kg=0,
                )
            )
    params = (
        {"keyword": "涂料"}
        if tool == "products"
        else {"unit_name": "公司A"}
        if tool == "shipment_records"
        else {}
    )
    step = AgentStep(node_id="read", tool_id=tool, action="query", params=params)
    result = AgentToolExecutor().execute(step, runtime_context=actor.context)
    assert result["success"] is True, result
    assert bool(result["data"]) is has_rows
    rejected = AgentToolExecutor().execute(step, runtime_context=denied.context)
    assert rejected["success"] is False
    assert rejected["error_code"] == "tool_permission_denied"
