"""Supplier returns are only reachable through original ToolSpecV2 and approvals."""

from __future__ import annotations

from unittest.mock import Mock

from app.application.agent_orchestrator.tool_spec import get_tool_action_spec, validate_tool_call
from app.domain.shared_services.tools_workflow_erp import _registered_router_purchase
from app.fastapi_routes import purchase


def _request():
    return {
        "return_no": "RET-AUTH-001",
        "approval_request_id": 11,
        "inbound_id": 17,
        "items": [{"inbound_item_id": 33, "quantity": "1.0000"}],
    }


def test_return_capability_is_registered_high_risk_and_requires_approval():
    spec = get_tool_action_spec("purchase", "post_return")
    assert spec is not None
    assert spec.risk == "high"
    assert spec.idempotent is True
    assert spec.policy.get("requires_write_approval") is True
    assert spec.policy.get("action_class") == "business_db.write"
    assert set(spec.required_params) == {
        "return_no", "approval_request_id", "inbound_id", "items",
    }


def test_return_capability_schema_validates_original_id_and_source_rows():
    assert validate_tool_call("purchase", "post_return", _request()).ok
    for invalid in (
        {"inbound_id": -1},
        {"approval_request_id": 0},
        {"items": []},
        {"items": [{"inbound_item_id": -1, "quantity": 1}]},
        {"items": [{"inbound_item_id": 33, "quantity": 1, "tenant_id": 2}]},
    ):
        values = {**_request(), **invalid}
        assert not validate_tool_call("purchase", "post_return", values).ok


def test_canonical_purchase_router_calls_existing_service(monkeypatch):
    from app.application.facades import inventory_facade

    fake = Mock()
    fake.post_purchase_return.return_value = {"success": True, "return_id": 77}
    monkeypatch.setattr(inventory_facade, "PurchaseService", lambda: fake)
    call = _registered_router_purchase(
        "post_return", _request(), {"tenant_id": 3}, "business", "",
    )
    assert call == {"success": True, "return_id": 77}
    fake.post_purchase_return.assert_called_once_with(_request())


def test_http_return_route_preserves_body_and_rejects_id_overrides(monkeypatch):
    observed = []

    def fake_agent(*, request, action, params, route_path):
        observed.append((action, params, route_path))
        return "queued"

    monkeypatch.setattr(purchase, "_run_purchase_agent", fake_agent)
    original = _request()
    body = {key: value for key, value in original.items() if key != "inbound_id"}
    response = purchase.purchase_inbound_supplier_return(None, 17, body)
    assert response == "queued"
    assert observed == [
        ("post_return", _request(), "/api/purchase/inbounds/{inbound_id}/return")
    ]
    for injected in (
        {"inbound_id": 99},
        {"tenant_id": 7},
        {"user_id": 1},
    ):
        denied = purchase.purchase_inbound_supplier_return(
            None, 17, {**body, **injected},
        )
        assert denied.status_code == 400
    assert len(observed) == 1
