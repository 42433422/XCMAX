"""HTTP ownership and legacy-route guards around the real portfolio ledger."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from modstore_server import strategic_layer_api
from modstore_server import strategic_portfolio as portfolio
from modstore_server import strategic_portfolio_api
from modstore_server import strategic_portfolio_runtime as runtime
from modstore_server import strategic_portfolio_scheduler as scheduler
from modstore_server.api.deps import get_current_user
from modstore_server.db.identity import User
from modstore_server.db.strategic import StrategicActionItem
from tests.test_strategic_portfolio import database as database_fixture
from tests.test_strategic_portfolio import limits, opportunity

database = database_fixture
BASE = "/api/xcmax/strategic"


@pytest.fixture
def api(database, monkeypatch):
    from modstore_server import strategic_layer_meeting_routes
    from modstore_server.strategic_layer import council_meeting

    for module in (
        strategic_portfolio_api,
        scheduler,
        strategic_layer_meeting_routes,
        council_meeting,
    ):
        monkeypatch.setattr(module, "get_session_factory", lambda: database)
    with database() as session:
        session.add(User(id=7, username="owner", password_hash="unused", is_admin=True))
        session.commit()
    identity = {"user": SimpleNamespace(id=7, username="owner", is_admin=True)}
    app = FastAPI()
    app.include_router(strategic_layer_api.router)
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    with TestClient(app) as client:
        yield client, identity


def propose(client):
    response = client.post(
        BASE + "/portfolios",
        json={
            "goal": "Verified customer outcome",
            "period": "test",
            "limits": limits(),
            "opportunities": [opportunity()],
            "idempotency_key": "http-contract",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["decision"]
    return data["decision_id"], data["decision_payload"]["proposal_sha256"]


def test_http_approval_binds_the_authenticated_owner_and_exact_proposal(api):
    client, identity = api
    decision_id, expected = propose(client)
    route = BASE + f"/portfolios/{decision_id}/approve"
    assert client.post(route, json={"expected_proposal_sha256": "0" * 64}).status_code == 409
    assert (
        client.post(
            route, json={"expected_proposal_sha256": expected, "actor": "spoof"}
        ).status_code
        == 422
    )
    identity["user"] = SimpleNamespace(id=8, username="other", is_admin=True)
    assert client.get(BASE + f"/portfolios/{decision_id}").status_code == 404
    assert client.get(BASE + f"/decisions/{decision_id}").status_code == 404
    assert client.get(BASE + "/portfolios").json()["items"] == []
    assert client.post(route, json={"expected_proposal_sha256": expected}).status_code == 404
    identity["user"] = SimpleNamespace(id=7, username="owner", is_admin=True)
    response = client.post(route, json={"expected_proposal_sha256": expected})
    assert response.status_code == 200
    assert response.json()["authorization"]["actor"] == "admin-user:7:owner"
    identity["user"].is_admin = False
    assert client.post(BASE + f"/portfolios/{decision_id}/run").status_code == 403


def test_generic_routes_cannot_approve_or_forge_portfolio_execution(api, database):
    client, _identity = api
    decision_id, expected = propose(client)
    route = BASE + f"/decisions/{decision_id}"
    for suffix, body in (
        ("approve", {}),
        ("reject", {"review_notes": "spoof"}),
        ("withdraw", {"actor": "spoof", "reason": "spoof"}),
        ("start", {}),
        ("complete", {"execution_result": {"ok": True}}),
        ("review", {"reviewer": "spoof", "review_notes": "all good"}),
    ):
        response = client.post(route + "/" + suffix, json=body)
        assert response.status_code == 409, (suffix, response.text)
    assert (
        client.post(
            BASE + f"/portfolios/{decision_id}/approve", json={"expected_proposal_sha256": expected}
        ).status_code
        == 200
    )
    assert client.post(BASE + f"/portfolios/{decision_id}/plan").status_code == 200
    with database() as session:
        action = session.scalars(select(StrategicActionItem)).one()
        action_id = action.action_id
    assert client.get(BASE + "/action-items").json()["items"] == []
    assert (
        client.post(
            BASE + f"/action-items/{action_id}",
            json={"status": "completed", "result": {"ok": True}},
        ).status_code
        == 409
    )
    assert portfolio.portfolio_status(decision_id)["tasks"] == {}


def test_scheduler_runs_approved_work_once_and_rechecks_principal(api, database, monkeypatch):
    client, _identity = api
    decision_id, expected = propose(client)
    client.post(
        BASE + f"/portfolios/{decision_id}/approve", json={"expected_proposal_sha256": expected}
    )
    executions = []
    monkeypatch.setattr(
        runtime,
        "_execute",
        lambda task: executions.append(task) or {"ok": True, "status": "completed"},
    )
    monkeypatch.setattr(
        runtime, "_business_outcome", lambda _state: {"status": "unknown", "revenue_cents": None}
    )
    assert scheduler.tick()["selected"] == 1
    assert len(executions) == 1
    scheduler.tick()
    assert len(executions) == 1
    with database() as session:
        session.get(User, 7).is_admin = False
        session.commit()
    result = scheduler.tick()["results"][0]
    assert result["reason"] == "approving_principal_no_longer_authorized"
    assert portfolio.portfolio_status(decision_id)["status"] == "withdrawn"
    assert scheduler.tick()["selected"] == 0


@pytest.mark.parametrize("account_state", ["disabled", "suspended", "blocked", "deleted"])
def test_scheduler_withdraws_frozen_owner_before_dispatch(
    api, database, monkeypatch, account_state
):
    client, _identity = api
    decision_id, expected = propose(client)
    assert (
        client.post(
            BASE + f"/portfolios/{decision_id}/approve", json={"expected_proposal_sha256": expected}
        ).status_code
        == 200
    )
    with database() as session:
        session.get(User, 7).account_state = account_state
        session.commit()
    monkeypatch.setattr(runtime, "_execute", lambda _task: pytest.fail("frozen account dispatched"))
    result = scheduler.tick()["results"][0]
    assert result["reason"] == "approving_principal_no_longer_authorized"
    assert portfolio.portfolio_status(decision_id)["status"] == "withdrawn"
    assert scheduler.tick()["selected"] == 0
