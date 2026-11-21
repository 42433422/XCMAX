"""Public company approvals and existing engineering stage capacity contracts."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import modstore_server.strategic_company_resources as company
import modstore_server.strategic_portfolio as portfolio
import modstore_server.strategic_portfolio_runtime as runtime
import modstore_server.strategic_portfolio_usage as usage
import tests.test_strategic_company_resources as company_fixtures
from modstore_server.db.identity import User
from modstore_server.db.strategic import StrategicDecision
from tests.test_strategic_company_resources import (
    budget,
    complete,
    finish,
    proposal,
    reserve,
    totals,
)
from tests.test_strategic_portfolio import limits, opportunity
from tests.test_strategic_portfolio_api import BASE
from tests.test_strategic_portfolio_api import api as api_fixture

api = api_fixture
configured = company_fixtures.configured
database = company_fixtures.database


def phase(task, state):
    def apply(_row, _proposal, portfolio_state, _session):
        saved = portfolio_state["tasks"][task["opportunity_id"]]
        saved["status"] = "waiting" if state == "idle" else "running"
        saved["worker_binding"] = {"adapter": "github_opencode_workspace"}
        saved["worker_capacity"] = {
            "state": state,
            "phase_receipt_id": "github:xcagi/approved-repo:run:123:job:456",
        }

    portfolio.mutate_portfolio(task["decision_id"], apply)


def test_verified_stage_releases_only_slot_and_resume_reacquires(configured):
    identity = budget(configured)
    first, second = proposal(7), proposal(8)
    task = runtime._claim(first, 7)
    receipt = reserve(task)
    complete(receipt)
    phase(task, "idle")
    released = totals(identity)
    assert released["slots"] == 0 and released["held"]["tokens"] == 40000 - 25
    other = runtime._claim(second, 8)
    assert other and totals(identity)["slots"] == 1
    with pytest.raises(portfolio.PortfolioError, match="capacity"):
        phase(task, "active")
    assert portfolio.portfolio_status(first)["tasks"]["a"]["worker_capacity"]["state"] == "idle"
    finish(other)
    phase(task, "active")
    assert totals(identity)["slots"] == 1
    complete(reserve(task))
    finish(task)
    assert totals(identity)["slots"] == 0
    assert totals(identity)["held"] == dict.fromkeys(portfolio.RESOURCES, 0)


def test_idle_stage_cannot_release_an_unsettled_model_call(configured):
    identity = budget(configured)
    task = runtime._claim(proposal(), 7)
    second = proposal(8)
    receipt = reserve(task)
    phase(task, "idle")
    assert totals(identity)["slots"] == 1
    assert runtime._claim(second, 8) is None
    usage.complete_platform_call(receipt, None)
    assert totals(identity)["slots"] == 1


def test_company_uses_real_cpsat_priority_when_only_one_slot_is_free(configured):
    identity = budget(configured)
    first = proposal(
        rows=[opportunity("low", value_score=1), opportunity("important", value_score=9)]
    )
    task = runtime._claim(first, 7)
    assert task["opportunity_id"] == "important"
    assert totals(identity)["slots"] == 1


def test_operator_member_removal_blocks_new_usage_and_preserves_recovery(configured, monkeypatch):
    identity = budget(configured)
    task = runtime._claim(proposal(8), 8)
    receipt = reserve(task)
    monkeypatch.setenv(
        company.CONTROL_ENV,
        json.dumps(
            {
                "scope": "xcagi-company",
                "authorizer_user_ids": [7],
                "eligible_owner_user_ids": [7],
            }
        ),
    )
    with pytest.raises(portfolio.PortfolioError, match="not a member"):
        reserve(task)
    complete(receipt)
    finish(task)
    assert totals(identity)["slots"] == 0


def test_initial_company_activation_does_not_forget_legacy_running_work(configured, monkeypatch):
    configured_control = company.control().model_dump_json()
    monkeypatch.delenv(company.CONTROL_ENV)
    first = proposal()
    task = runtime._claim(first, 7)
    monkeypatch.setenv(company.CONTROL_ENV, configured_control)
    identity = budget(configured, approved=False)
    with configured() as session:
        row = session.scalars(
            select(StrategicDecision).where(StrategicDecision.decision_id == identity)
        ).one()
        expected = json.loads(row.decision_payload_json)["proposal_sha256"]
    with pytest.raises(portfolio.PortfolioError, match="pre-company task liabilities"):
        company.authorize_company(
            identity, authorizer_user_id=7, actor="admin:7", expected_proposal_sha256=expected
        )
    finish(task)
    company.authorize_company(
        identity, authorizer_user_id=7, actor="admin:7", expected_proposal_sha256=expected
    )
    with pytest.raises(portfolio.PortfolioError, match="company mandate"):
        runtime._claim(first, 7)


def test_caller_receipt_is_frozen_with_the_original_model_reservation(configured):
    budget(configured)
    task = runtime._claim(proposal(), 7)
    binding = {
        "grant_id": "grant-1",
        "event_id": "evt-1",
        "task_id": "task-1",
        "subtask_id": "subtask-1",
        "attempt": 1,
        "phase": "execute",
        "github_run_id": 123,
        "run_attempt": 1,
    }
    frozen = dict(binding)
    with usage.portfolio_usage_scope(
        task["decision_id"], task["opportunity_id"], task["lease_token"]
    ):
        receipt = usage.prepare_platform_call("test", "model", [], 20, caller_binding=binding)
    binding["subtask_id"] = "different-task"
    complete(receipt)
    call = portfolio.portfolio_status(task["decision_id"])["tasks"]["a"]["calls"][
        receipt["request_id"]
    ]
    assert call["caller_binding"] == frozen
    assert call["caller_binding_sha256"] == portfolio.digest(frozen)


@pytest.mark.parametrize(
    "binding",
    [
        {},
        {"api_key": "secret"},
        {"attempt": True},
        {"attempt": -1},
        {"task_id": {"nested": "not-an-id"}},
        {"task_id": "x" * 257},
        {"phase": "execute\nresume"},
    ],
)
def test_invalid_caller_identity_cannot_create_a_call_reservation(configured, binding):
    identity = budget(configured)
    task = runtime._claim(proposal(), 7)
    before = totals(identity)
    with usage.portfolio_usage_scope(
        task["decision_id"], task["opportunity_id"], task["lease_token"]
    ):
        with pytest.raises(portfolio.PortfolioError, match="caller binding"):
            usage.prepare_platform_call("test", "model", [], 20, caller_binding=binding)
    assert portfolio.portfolio_status(task["decision_id"])["tasks"]["a"]["calls"] == {}
    assert totals(identity) == before


def test_http_company_authority_uses_original_admin_and_blocks_generic_mutation(
    api, database, monkeypatch
):
    client, identity = api
    monkeypatch.setenv(
        company.CONTROL_ENV,
        json.dumps(
            {
                "scope": "one-deployment",
                "authorizer_user_ids": [7],
                "eligible_owner_user_ids": [7, 8],
            }
        ),
    )
    with database() as session:
        session.add(User(id=8, username="member", password_hash="unused", is_admin=True))
        session.commit()
    caps = {
        key: value for key, value in limits().items() if key in company.CompanyLimits.model_fields
    }
    caps["max_parallel"] = 1
    path = BASE + "/portfolios/company-budgets"
    response = client.post(
        path,
        json={
            "period": "quarter",
            "limits": caps,
            "member_owner_ids": [7, 8],
            "idempotency_key": "http",
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()["decision"]
    decision_id = result["decision_id"]
    assert client.post(BASE + f"/decisions/{decision_id}/approve", json={}).status_code == 409
    assert all(
        item["decision_id"] != decision_id
        for item in client.get(BASE + "/decisions").json()["items"]
    )
    identity["user"] = SimpleNamespace(id=8, username="member", is_admin=True)
    approval = {"expected_proposal_sha256": result["decision_payload"]["proposal_sha256"]}
    assert client.post(path + f"/{decision_id}/approve", json=approval).status_code == 409
    identity["user"] = SimpleNamespace(id=7, username="owner", is_admin=True)
    approved = client.post(path + f"/{decision_id}/approve", json=approval)
    assert approved.status_code == 200, approved.text
    assert approved.json()["authorization"]["actor"] == "admin-user:7:owner"
    assert client.post(path + f"/{decision_id}/stop", json={"reason": "pause"}).status_code == 200
    assert client.get(path + f"/{decision_id}").json()["status"] == "withdrawn"
