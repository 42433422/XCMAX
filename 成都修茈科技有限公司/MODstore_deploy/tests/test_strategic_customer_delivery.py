"""Original customers download real native outputs before explicit acceptance."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from modstore_server import customer_value_lifecycle_api as lifecycle
from modstore_server import strategic_customer_delivery as delivery
from modstore_server import strategic_customer_outcomes as outcomes
from modstore_server import strategic_portfolio as portfolio
from modstore_server import strategic_portfolio_runtime as runtime
from modstore_server.api.deps import get_current_user
from modstore_server.db.customer_value import CustomerValueReceipt
from modstore_server.db.identity import User
from tests import test_strategic_market_cycle as market_fixtures
from tests import test_strategic_portfolio as portfolio_fixtures

database = portfolio_fixtures.database
csv_employee = market_fixtures.csv_employee
customer = market_fixtures.customer


@pytest.fixture
def completed_delivery(database, csv_employee, customer, monkeypatch):
    monkeypatch.setattr(delivery, "get_session_factory", lambda: database)
    goal = customer["goal"]
    bindings = outcomes.load_customer_goal_bindings(8, goal["order_no"], [goal["customer_goal_id"]])
    decision = portfolio_fixtures.proposal(
        database,
        rows=[
            portfolio_fixtures.opportunity(
                employee_id=csv_employee["employee"],
                input_data={"file_path": "inputs/orders.json"},
                customer_goal_ids=[goal["customer_goal_id"]],
                customer_goal_bindings=bindings,
            )
        ],
    )
    state = runtime.run_portfolio_cycle(decision)
    assert state["tasks"]["a"]["status"] == "completed", state
    # The native employee reports an absolute path and its verified relative
    # files_changed alias; they must identify one delivered file.
    assert len(state["tasks"]["a"]["execution_receipt"]["delivered_artifacts"]) == 1
    artifact = state["tasks"]["a"]["execution_receipt"]["delivered_artifacts"][0]
    app = FastAPI()
    app.include_router(lifecycle.router)
    actor = [customer["client"]]
    app.dependency_overrides[get_current_user] = lambda: actor[0]
    with TestClient(app) as http:
        query = {"order_no": goal["order_no"], "customer_goal_id": goal["customer_goal_id"]}
        path = f"/api/customer-value/deliveries/{decision}/a/{artifact['artifact_id']}"
        yield {
            "http": http,
            "actor": actor,
            "decision": decision,
            "artifact": artifact,
            "path": path,
            "query": query,
            "output": csv_employee["workspace"] / artifact["output_path"],
        }


def test_original_customer_downloads_same_csv_then_explicitly_accepts(
    completed_delivery, customer, database
):
    env = completed_delivery
    listing = env["http"].get("/api/customer-value/deliveries", params=env["query"])
    assert listing.status_code == 200, listing.text
    assert len(listing.json()["items"]) == 1
    row = listing.json()["items"][0]
    assert set(row) == {
        "artifact_id",
        "artifact_sha256",
        "filename",
        "download_url",
        "completed_at",
    }
    received = env["http"].get(row["download_url"])
    assert received.status_code == 200, received.text
    assert received.content == env["output"].read_bytes() and b"A-7" in received.content
    assert hashlib.sha256(received.content).hexdigest() == row["artifact_sha256"]
    assert received.headers["etag"] == f'"{row["artifact_sha256"]}"'
    assert received.headers["cache-control"] == "private, no-store"
    assert "attachment" in received.headers["content-disposition"]
    with database() as session:
        assert not session.scalars(
            select(CustomerValueReceipt).where(CustomerValueReceipt.receipt_kind == "acceptance")
        ).all()
    market_fixtures.accept_delivered(customer, env["artifact"])
    with database() as session:
        accepted = session.scalar(
            select(CustomerValueReceipt).where(CustomerValueReceipt.receipt_kind == "acceptance")
        )
        assert accepted.customer_ref == "paid-user:8"
        assert accepted.artifact_id == row["artifact_id"]


@pytest.mark.parametrize("actor", ["admin", "other_customer", "non_enterprise"])
def test_admin_and_other_accounts_cannot_download_customer_files(
    completed_delivery, customer, actor
):
    env = completed_delivery
    env["actor"][0] = (
        customer["admin"]
        if actor == "admin"
        else User(
            id=9 if actor == "other_customer" else 8,
            username="other-customer",
            password_hash="unused",
            is_enterprise=actor == "other_customer",
        )
    )
    assert env["http"].get(env["path"], params=env["query"]).status_code == 403
    assert env["http"].get("/api/customer-value/deliveries", params=env["query"]).status_code == 403


@pytest.mark.parametrize("change", ["bytes", "missing", "symlink", "traversal"])
def test_download_fails_closed_for_changed_or_escaped_source(completed_delivery, change):
    env = completed_delivery
    path: Path = env["output"]
    if change == "bytes":
        path.write_bytes(b"a later generation, not the accepted artifact")
    elif change == "missing":
        path.unlink()
    elif change == "symlink":
        external = path.parents[2] / "other-tenant-secret"
        external.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(external)
    else:

        def alter(_row, _proposal, state, _session):
            artifact = state["tasks"]["a"]["execution_receipt"]["delivered_artifacts"][0]
            artifact["output_path"] = "../other-tenant-secret"

        portfolio.mutate_portfolio(env["decision"], alter)
    response = env["http"].get(env["path"], params=env["query"])
    assert response.status_code == 409, response.text
    assert str(path) not in response.text


@pytest.mark.parametrize("change", ["refund", "agreement", "incomplete", "binding"])
def test_only_current_original_goal_and_completed_artifact_can_be_read(
    completed_delivery, customer, change
):
    env = completed_delivery
    if change == "refund":
        customer["source"]["orders"][0]["status"] = "refunded"
    elif change == "agreement":
        lifecycle.record_kpi_agreement(
            lifecycle.KpiAgreementReceiptBody(
                **customer["goal"],
                idempotency_key="revised-customer-agreement",
                agreement_sha256="b" * 64,
            ),
            user=customer["client"],
        )
    else:

        def alter(_row, _proposal, state, _session):
            if change == "incomplete":
                state["tasks"]["a"]["status"] = "queued"
            else:
                state["authorization"]["proposal_sha256"] = "b" * 64

        portfolio.mutate_portfolio(env["decision"], alter)
    response = env["http"].get(env["path"], params=env["query"])
    assert response.status_code == (409 if change == "refund" else 404)
