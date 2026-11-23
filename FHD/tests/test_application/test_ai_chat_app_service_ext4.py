"""Active Excel helpers and unified model-plan contracts; no retired dispatch brain.

Removed internal source classifiers are covered through process_chat, model admission,
registered authenticated tools and the durable approval/session regression suites.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from app.application.ai_chat_app_service import AIChatApplicationService

# Migration map: old normal/pro dispatch and response overlays now use one
# model-authored graph. Real reads below cover products/customers/shipment_records;
# signed write/readback isolation is in test_owned_business_tool_isolation;
# persisted approval consumption/cancel/resume is in test_approval_session_renewal.
# Regex order assembly/model splitting is not a second planner: the complete
# structured shipment parameters must survive model admission unchanged.
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.planner_model import goal_review_response
from tests.test_application.ai_chat_test_helpers import (
    _make_svc as _make_service,
)


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
