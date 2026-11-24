"""Real authenticated HTTP/model read paths share authority and immutable goal inputs."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator.tool_spec import get_tool_action_spec, validate_tool_call
from app.application.enterprise_cognition.service import EnterpriseCognitionService
from app.application.tools.workflow_tools.dispatch import execute_registered_workflow_tool
from app.db.models import SalesOrder, SalesOrderItem
from app.db.models.permission import Role
from app.fastapi_routes.domains.agent.task_routes import router
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def enterprise_http(trusted_actor, monkeypatch):
    actor = trusted_actor(role="enterprise-reader", permissions=["tool.sales.query"])
    monkeypatch.setattr("app.db.SessionLocal", actor.factory)
    monkeypatch.delenv("FHD_ALLOW_X_USER_ID_HEADER", raising=False)
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        order = SalesOrder(order_no="STATE-A", state="confirmed", total_amount=100)
        order.items = [
            SalesOrderItem(
                product_name="产品A",
                quantity=10,
                ordered_quantity=10,
                delivered_quantity=4,
                unit="件",
                reserved_quantity=0,
                returned_quantity=0,
            )
        ]
        newer = SalesOrder(order_no="STATE-B", state="confirmed", total_amount=100)
        newer.items = [
            SalesOrderItem(
                product_name="产品B",
                quantity=2,
                ordered_quantity=2,
                unit="件",
            )
        ]
        db.add_all([order, newer])
        db.flush()
        order_id, newer_id = str(order.id), str(newer.id)
    with tenant_scope(actor.tenant_id + 1), actor.factory.begin() as db:
        secret = SalesOrder(order_no="OTHER-TENANT-SECRET", total_amount=888)
        db.add(secret)
        db.flush()
        foreign_id = str(secret.id)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield actor, client, order_id, newer_id, foreign_id


def _goal(entity_id, **changes):
    return {
        "goal_id": f"deliver-{entity_id}",
        "objective": "把订单剩余待发数量降为0件",
        "entity_type": "order",
        "entity_id": entity_id,
        "metric": "remaining_quantity",
        "unit": "件",
        "direction": "decrease",
        "target": "0",
        **changes,
    }


def test_http_and_registered_model_tool_read_same_authority_without_business_writes(
    enterprise_http,
):
    actor, client, order_id, _, _ = enterprise_http
    params = {"entity_type": "order", "entity_id": order_id}
    response = client.post(
        "/api/enterprise/cognition",
        json={"action": "query", "params": params},
        headers=actor.headers,
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["current_state_verified"] is True
    snapshot = payload["snapshots"][0]
    assert Decimal(snapshot["state"]["remaining_quantity"]) == 6
    assert snapshot["source_version"].startswith("sha256:")
    assert snapshot["evidence"] and snapshot["observed_at"] and snapshot["expires_at"]
    assert payload["observations"][0]["delay_status"] == "unknown"
    assert payload["observations"][0]["root_cause"] == "unknown"
    result = execute_registered_workflow_tool(
        "enterprise_cognition", "query", {**params, "_runtime_context": actor.context}
    )
    assert result["success"] is True
    assert result["data"]["snapshots"][0]["source_version"] == snapshot["source_version"]
    assert result["data"]["snapshots"][0]["retrieved_from"] == "projection"
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        assert db.get(SalesOrder, int(order_id)).items[0].delivered_quantity == 4
        assert db.query(SalesOrder).count() == 2
    with tenant_scope(actor.tenant_id + 1), actor.factory() as db:
        assert db.query(SalesOrder).one().total_amount == 888


def test_goal_deadline_is_user_objective_not_invented_order_due_date(enterprise_http):
    actor, client, order_id, _, _ = enterprise_http
    deadline = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    result = client.post(
        "/api/enterprise/cognition",
        json={"action": "bind_goal", "params": _goal(order_id, deadline=deadline)},
        headers=actor.headers,
    )
    assert result.status_code == 200
    assert result.json()["data"]["source"]["kind"] == "user_goal"
    query = client.post(
        "/api/enterprise/cognition",
        json={"action": "query", "params": {"entity_id": order_id}},
        headers=actor.headers,
    ).json()["data"]
    assert query["goal_progress"][0]["goal_deadline_missed"] is True
    assert query["goal_progress"][0]["knowledge_kind"] == "inference"
    assert query["goal_progress"][0]["derivation"] == "deterministic_metric_target_comparison"
    assert query["goal_progress"][0]["evidence"]
    assert query["goal_progress"][0]["deadline_source"] == "user_goal"
    assert query["goal_progress"][0]["order_promised_date_inferred"] is False
    assert query["observations"][0]["delay_status"] == "unknown"


def test_goal_filter_precedes_limit_and_matches_selected_authority(enterprise_http):
    actor, _, order_id, newer_id, _ = enterprise_http
    service = EnterpriseCognitionService()
    service.invoke("bind_goal", _goal(order_id), context=actor.context)
    service.invoke("bind_goal", _goal(newer_id), context=actor.context)
    with tenant_scope(actor.tenant_id):
        bound = service.goals.list(
            tenant_id=actor.tenant_id,
            actor_id=str(actor.user_id),
            entity_type="order",
            entity_ids=[order_id],
            limit=1,
        )
    assert [goal["entity_id"] for goal in bound] == [order_id]
    result = service.invoke("query", {"entity_id": order_id}, context=actor.context)
    assert [goal["entity_id"] for goal in result["goals"]] == [order_id]


def test_goal_uses_the_same_canonical_authority_id_as_queries(enterprise_http):
    actor, client, order_id, _, _ = enterprise_http
    goal = _goal("000" + order_id, goal_id="canonical-id")
    first = client.post(
        "/api/enterprise/cognition",
        json={"action": "bind_goal", "params": goal},
        headers=actor.headers,
    )
    assert first.status_code == 200
    assert first.json()["data"]["entity_id"] == order_id
    second = client.post(
        "/api/enterprise/cognition",
        json={"action": "bind_goal", "params": {**goal, "entity_id": order_id}},
        headers=actor.headers,
    )
    assert second.status_code == 200
    assert first.json() == second.json()
    query = client.post(
        "/api/enterprise/cognition",
        json={"action": "query", "params": {"entity_id": order_id}},
        headers=actor.headers,
    )
    assert query.json()["data"]["goals"][0]["goal_id"] == "canonical-id"


def test_http_rejects_anonymous_forged_identity_and_permission_revocation(enterprise_http):
    actor, client, order_id, _, foreign_id = enterprise_http
    body = {"action": "query", "params": {"entity_id": order_id}}
    assert client.post("/api/enterprise/cognition", json=body).status_code == 401
    assert (
        client.post(
            "/api/enterprise/cognition", json=body, headers={"X-User-ID": str(actor.user_id)}
        ).status_code
        == 401
    )
    foreign = client.post(
        "/api/enterprise/cognition",
        json={"action": "query", "params": {"entity_id": foreign_id}},
        headers=actor.headers,
    )
    assert foreign.status_code == 200
    assert foreign.json()["data"]["current_state_verified"] is False
    assert "OTHER-TENANT-SECRET" not in foreign.text
    client.post("/api/enterprise/cognition", json=body, headers=actor.headers)
    with actor.factory.begin() as db:
        db.query(Role).filter_by(name="enterprise-reader").one().permissions = []
    assert (
        client.post("/api/enterprise/cognition", json=body, headers=actor.headers).status_code
        == 403
    )
    denied = execute_registered_workflow_tool(
        "enterprise_cognition", "query", {"entity_id": order_id, "_runtime_context": actor.context}
    )
    assert denied["success"] is False and denied["error_code"] == "enterprise_access_denied"


@pytest.mark.parametrize(
    "injected",
    [
        {"tenant_id": "999"},
        {"approved": True},
        {"_runtime_context": {}},
        {"force_refresh": True, "limit": True},
    ],
)
def test_http_action_parameters_cannot_inject_identity_or_approval(enterprise_http, injected):
    actor, client, order_id, _, _ = enterprise_http
    response = client.post(
        "/api/enterprise/cognition",
        json={"action": "query", "params": {"entity_id": order_id, **injected}},
        headers=actor.headers,
    )
    assert response.status_code == 422


def test_model_and_http_share_strict_catalog_contract(enterprise_http):
    actor, client, *_ = enterprise_http
    data = client.post(
        "/api/enterprise/cognition", json={"action": "catalog"}, headers=actor.headers
    ).json()["data"]
    assert {item["entity_type"] for item in data["entities"]} == {
        "order",
        "customer",
        "employee",
        "task",
        "fund",
        "inventory",
        "production",
        "supplier",
        "purchase_order",
        "purchase_inbound",
    }
    assert data["read_only_sources"] is True
    spec = get_tool_action_spec("enterprise_cognition", "query")
    assert spec.read_only and spec.idempotent
    assert validate_tool_call(
        "enterprise_cognition", "query", {"entity_type": "order", "entity_id": "1"}
    ).ok
    assert not validate_tool_call("enterprise_cognition", "query", {"approved": True}).ok
    assert not validate_tool_call(
        "enterprise_cognition",
        "plan",
        {"goal_id": "g", "request_id": "r", "message": "plan", "approved": True},
    ).ok


def test_world_history_and_scenario_share_http_and_model_status(enterprise_http):
    actor, client, order_id, *_ = enterprise_http
    params = {"entity_id": order_id}
    first = client.post(
        "/api/enterprise/cognition",
        json={"action": "query", "params": params},
        headers=actor.headers,
    ).json()["data"]["snapshots"][0]
    history_params = {**params, "as_of": first["observed_at"]}
    response = client.post(
        "/api/enterprise/cognition",
        json={"action": "query", "params": history_params},
        headers=actor.headers,
    ).json()
    assert response["success"] is True
    assert response["data"]["current_state_verified"] is False
    assert response["data"]["history"]["observation"]["source_version"] == first["source_version"]
    result = execute_registered_workflow_tool(
        "enterprise_cognition", "query", {**history_params, "_runtime_context": actor.context}
    )
    assert result["success"] is True
    prediction = client.post(
        "/api/enterprise/cognition",
        json={"action": "query", "params": {**params, "scenario_delivery_quantity": "2"}},
        headers=actor.headers,
    ).json()
    assert prediction["success"] is True
    assert prediction["data"]["scenario"]["knowledge_kind"] == "prediction"
    assert Decimal(prediction["data"]["scenario"]["value"]) == 4
    unknown = client.post(
        "/api/enterprise/cognition",
        json={"action": "query", "params": {**params, "scenario_delivery_quantity": "100"}},
        headers=actor.headers,
    ).json()
    assert unknown["success"] is False
    assert unknown["data"]["scenario"]["knowledge_kind"] == "unknown"


def test_goal_comparison_without_verified_evidence_stays_unknown():
    from app.application.enterprise_cognition.service import _goal_progress

    result = _goal_progress(
        {
            "goal_id": "no-evidence",
            "metric": "remaining_quantity",
            "unit": "件",
            "target": "0",
            "direction": "decrease",
        },
        {
            "freshness": "fresh",
            "source_version": "sha256:synthetic",
            "state": {"remaining_quantity": "2", "quantity_unit": "件"},
            "evidence": [],
        },
    )
    assert result["knowledge_kind"] == "unknown"
    assert result["target_met"] is None


def test_goal_inference_keeps_strategic_goal_provenance():
    from app.application.enterprise_cognition.service import _goal_progress

    goal = {
        "goal_id": "strategy-bound-goal",
        "metric": "remaining_quantity",
        "unit": "件",
        "target": "0",
        "direction": "decrease",
        "source": {"kind": "strategic_plan", "plan_sha256": "e" * 64},
    }
    snapshot = {
        "freshness": "fresh",
        "source_version": "sha256:synthetic",
        "state": {"remaining_quantity": "2", "quantity_unit": "件"},
        "evidence": [{"source": "sales_orders", "row_id": "42"}],
    }
    result = _goal_progress(goal, snapshot)
    assert result["knowledge_kind"] == "inference"
    assert result["goal_assertion_kind"] == "strategic_plan"
    assert result["source_knowledge_kind"] == "fact"
    assert result["target_met"] is False
