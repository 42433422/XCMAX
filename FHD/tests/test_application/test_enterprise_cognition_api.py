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
    (candidate,) = query["operating_gap_candidates"]
    assert candidate["goal_id"] == _goal(order_id)["goal_id"]
    assert Decimal(candidate["evidence"]["gap"]) == 6
    assert candidate["deadline_missed"] is True
    assert candidate["execution_authorized"] is False
    assert candidate["requires_original_approval"] is True
    assert candidate["evidence"]["source_version"] == query["snapshots"][0]["source_version"]
    assert query["business_data_written"] is False
    again = client.post(
        "/api/enterprise/cognition",
        json={"action": "query", "params": {"entity_id": order_id}},
        headers=actor.headers,
    ).json()["data"]
    assert again["operating_gap_candidates"][0]["candidate_id"] == candidate["candidate_id"]


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
        "journal_entry",
    }
    assert data["read_only_sources"] is True
    unknowns = data["unverified_aggregate_metrics"]
    assert {row["metric"] for row in unknowns} >= {
        "cash_balance",
        "accounts_receivable_balance",
        "accounts_payable_balance",
        "available_inventory_balance",
    }
    assert all(row["knowledge_kind"] == "unknown" for row in unknowns)
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


def test_met_goal_and_foreign_entity_do_not_produce_operating_gap(enterprise_http):
    actor, _, order_id, _, foreign_id = enterprise_http
    service = EnterpriseCognitionService()
    service.invoke("bind_goal", _goal(order_id, target="6"), context=actor.context)
    own = service.invoke("query", {"entity_id": order_id}, context=actor.context)
    assert own["goal_progress"][0]["target_met"] is True
    assert own["operating_gap_candidates"] == []
    foreign = service.invoke("query", {"entity_id": foreign_id}, context=actor.context)
    assert foreign["current_state_verified"] is False
    assert foreign["operating_gap_candidates"] == []


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


def test_empty_authorized_world_query_is_unknown_not_a_verified_fact():
    from app.application.enterprise_cognition.service import (
        EnterpriseCognitionService,
        cognition_result_verified,
    )

    class NoVisibleRecords:
        def list_refs(self, entity_type, *, limit, **scope):
            return {"refs": [], "has_more": False}

    class NoGoals:
        def list(self, **scope):
            raise AssertionError("empty source must not synthesize a goal")

    query = {"entity_type": "order", "entity_id": None, "limit": 10, "force_refresh": False}
    result = EnterpriseCognitionService(projections=NoVisibleRecords(), goals=NoGoals()).query(
        query, tenant_id="11", actor_id="1", mod_id=""
    )
    assert result["snapshots"] == []
    assert result["current_state_verified"] is False
    assert result["reason_code"] == "no_visible_source_records"
    assert cognition_result_verified("query", query, result) is False


def test_erp_fact_reference_requires_live_source_version_before_reuse(enterprise_http):
    """A confirmed memory version is not a license to reuse a stale ERP fact."""
    actor, client, order_id, _, foreign_id = enterprise_http
    base = {"entity_type": "order", "entity_id": order_id}
    original_result = client.post(
        "/api/enterprise/cognition",
        json={"action": "query", "params": base},
        headers=actor.headers,
    ).json()["data"]
    original = original_result["snapshots"][0]
    remembered_version = original["source_version"]
    remembered_token = original_result["fact_references"][0]["fact_token"]
    assert original_result["fact_references"][0]["entity_id"] == order_id
    guarded = {
        **base,
        "expected_source_version": remembered_version,
        "expected_fact_token": remembered_token,
    }
    current = client.post(
        "/api/enterprise/cognition",
        json={"action": "query", "params": guarded},
        headers=actor.headers,
    ).json()
    assert current["success"] is True
    assert current["data"]["fact_verification"]["status"] == "current"
    assert current["data"]["fact_verification"]["memory_reuse_allowed"] is True
    assert current["data"]["snapshots"][0]["retrieved_from"] == "authority"

    # Change only ERP, within the original TTL, without emitting an event.
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        db.query(SalesOrderItem).filter_by(order_id=int(order_id)).one().delivered_quantity = 5
    obsolete = client.post(
        "/api/enterprise/cognition",
        json={"action": "query", "params": guarded},
        headers=actor.headers,
    ).json()
    assert obsolete["success"] is False
    check = obsolete["data"]["fact_verification"]
    assert check["status"] == "superseded"
    assert check["expected_source_version"] == remembered_version
    assert check["expected_fact_token"] == remembered_token
    assert check["current_source_version"] != remembered_version
    assert check["memory_reuse_allowed"] is False
    assert check["requires_reconciliation"] is True
    assert obsolete["data"]["remembered_fact_current"] is False
    assert obsolete["data"]["operating_gap_candidates"] == []
    assert obsolete["data"]["snapshots"][0]["retrieved_from"] == "authority"
    assert Decimal(obsolete["data"]["snapshots"][0]["state"]["remaining_quantity"]) == 5
    tool = execute_registered_workflow_tool(
        "enterprise_cognition", "query", {**guarded, "_runtime_context": actor.context}
    )
    assert tool["success"] is False
    assert tool["data"]["fact_verification"]["status"] == "superseded"

    corrected = {
        **base,
        "expected_source_version": check["current_source_version"],
        "expected_fact_token": check["current_fact_token"],
    }
    assert (
        client.post(
            "/api/enterprise/cognition",
            json={"action": "query", "params": corrected},
            headers=actor.headers,
        ).json()["data"]["fact_verification"]["status"]
        == "current"
    )
    missing = client.post(
        "/api/enterprise/cognition",
        json={
            "action": "query",
            "params": {**guarded, "entity_id": foreign_id},
        },
        headers=actor.headers,
    ).json()
    assert missing["success"] is False
    assert missing["data"]["fact_verification"]["status"] == "unknown"
    assert missing["data"]["fact_verification"]["current_source_version"] is None


@pytest.mark.parametrize(
    "params",
    [
        {"expected_source_version": "sha256:" + "0" * 64},
        {"entity_id": "1", "expected_fact_token": "erp:" + "f" * 64},
        {
            "entity_id": "1",
            "expected_source_version": "sha256:not-a-hash",
            "expected_fact_token": "erp:" + "f" * 64,
        },
        {
            "entity_id": "1",
            "expected_source_version": "sha256:" + "0" * 64,
            "expected_fact_token": "not-a-token",
        },
        {
            "entity_id": "1",
            "expected_source_version": "sha256:" + "0" * 64,
            "expected_fact_token": "erp:" + "f" * 64,
            "as_of": "2026-01-01T00:00:00+00:00",
        },
        {
            "entity_id": "1",
            "expected_source_version": "sha256:" + "0" * 64,
            "expected_fact_token": "erp:" + "f" * 64,
            "scenario_delivery_quantity": "2",
        },
        {
            "entity_id": "1",
            "expected_source_version": "sha256:" + "0" * 64,
            "expected_fact_token": "erp:" + "f" * 64,
            "tenant_id": "999",
        },
        {
            "expected_source_version": "sha256:" + "0" * 64,
            "expected_fact_token": "erp:" + "f" * 64,
        },
    ],
)
def test_erp_fact_reference_rejects_ambiguity_and_identity_injection(enterprise_http, params):
    actor, client, *_ = enterprise_http
    result = client.post(
        "/api/enterprise/cognition",
        json={"action": "query", "params": params},
        headers=actor.headers,
    )
    assert result.status_code == 422


def test_erp_reference_cannot_be_verified_from_cached_or_unknown_projection():
    from app.application.enterprise_cognition.service import verify_source_reference

    version = "sha256:" + "a" * 64
    stale = {
        "freshness": "fresh",
        "knowledge_kind": "fact",
        "retrieved_from": "projection",
        "source_version": version,
        "evidence": [{"content_sha256": "a" * 64}],
    }
    for untrusted in (
        stale,
        {"freshness": "unknown", "reason_code": "authority_unavailable"},
    ):
        result = verify_source_reference(untrusted, version, "erp:" + "b" * 64)
        assert result["status"] == "unknown"
        assert result["memory_reuse_allowed"] is False
        assert result["requires_reconciliation"] is True
        assert result["business_data_written"] is False


@pytest.mark.parametrize(
    "changed",
    [
        {"entity_id": "202"},
        {"tenant_id": "22"},
        {"mod_id": "finance"},
        {"entity_type": "order"},
        {"source": "different_authority"},
    ],
)
def test_erp_reference_token_rejects_identical_content_with_wrong_identity(changed):
    from app.application.enterprise_cognition.service import (
        make_fact_reference,
        verify_source_reference,
    )

    snapshot = {
        "freshness": "fresh",
        "knowledge_kind": "fact",
        "retrieved_from": "authority",
        "tenant_id": "11",
        "mod_id": "",
        "source": "customers",
        "entity_type": "customer",
        "entity_id": "201",
        "source_version": "sha256:" + "a" * 64,
        "observed_at": "2026-11-25T00:00:00+00:00",
        "evidence": [{"source": "customers", "content_sha256": "a" * 64}],
    }
    original_reference = make_fact_reference(snapshot)
    assert original_reference is not None
    version = snapshot["source_version"]
    token = original_reference["fact_token"]
    assert verify_source_reference(snapshot, version, token)["status"] == "current"
    different = verify_source_reference({**snapshot, **changed}, version, token)
    assert different["status"] == "superseded"
    assert different["reason_code"] == "fact_reference_scope_or_entity_mismatch"
    assert different["memory_reuse_allowed"] is False
