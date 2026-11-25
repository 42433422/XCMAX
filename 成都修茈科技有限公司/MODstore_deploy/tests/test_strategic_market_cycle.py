"""Market observations reach approved native work and real customer receipt consumers."""

from __future__ import annotations

import asyncio
import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import HTTPException

import modstore_server.strategic_market_research as market
import modstore_server.strategic_portfolio as portfolio
import modstore_server.strategic_portfolio_runtime as runtime
from modstore_server import (
    customer_value_evidence,
    customer_value_lifecycle_api,
    customer_value_payment_source,
    strategic_customer_outcomes,
    strategy_bets,
    strategy_planner,
    task_router,
)
from modstore_server.db.identity import User
from modstore_server.infrastructure import http_clients
from tests import test_strategic_execution_contract as contract_fixtures
from tests import test_strategic_portfolio as portfolio_fixtures

database = portfolio_fixtures.database
csv_employee = contract_fixtures.csv_employee


@pytest.fixture
def customer(database, monkeypatch):
    portfolio_fixtures.seed_owner(database)
    with database() as session:
        client = User(
            id=8, username="original-customer", password_hash="unused", is_enterprise=True
        )
        session.add(client)
        session.commit()
        admin = session.get(User, 7)
    order = {
        "status": "paid",
        "out_trade_no": "customer-order-eight",
        "user_id": 8,
        "amount_cents": 10_000,
        "currency": "CNY",
        "paid_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        "payment_provider": "alipay",
        "provider_trade_no": "alipay-verified-eight",
        "provider_verification": "alipay_signed_callback",
        "environment": "production",
    }
    source = {
        "source_available": True,
        "source_authoritative": True,
        "source_owner": "test-payment-provider",
        "orders": [order],
    }
    for module in (customer_value_lifecycle_api, customer_value_payment_source):
        monkeypatch.setattr(module, "load_authoritative_payment_orders", lambda _days: source)
    monkeypatch.setattr(customer_value_evidence, "get_session_factory", lambda: database)
    goal = {
        "order_no": order["out_trade_no"],
        "customer_goal_id": "customer-csv-goal",
        "baseline": 0.0,
        "target": 1.0,
        "comparison": "ge",
        "unit": "valid_csv_artifact",
        "measurement_window": "approved-one-day-product-experiment",
    }
    result = customer_value_lifecycle_api.record_kpi_agreement(
        customer_value_lifecycle_api.KpiAgreementReceiptBody(
            **goal,
            idempotency_key="original-customer-goal-confirmation",
            agreement_sha256="a" * 64,
        ),
        user=client,
    )
    assert result["created"]
    return {"client": client, "admin": admin, "order": order, "source": source, "goal": goal}


def query_config(employee="test-qa-runner", **overrides):
    return {
        "queries": [
            {
                "query": "customer CSV workflow product release",
                "domain_id": "etl",
                "allowed_hosts": ["docs.example.org"],
                "employee_id": employee,
                "customer_user_id": 8,
                "order_no": "customer-order-eight",
                "customer_goal_ids": ["customer-csv-goal"],
                "window_days": 1,
                **overrides,
            }
        ],
        "max_publication_age_days": 30,
    }


@pytest.fixture
def search_service(monkeypatch):
    seen = []
    rows = [
        {
            "url": "https://docs.example.org/releases/csv-workflow",
            "title": "CSV workflow release",
            "content": "A current export workflow can reduce repetitive table preparation.",
            "publishedDate": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
            "engine": "fixture-engine",
        }
    ]

    def respond(request):
        seen.append(request)
        assert request.url.path == "/search" and request.url.params["format"] == "json"
        return httpx.Response(200, json={"results": rows})

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    monkeypatch.setenv("MODSTORE_SEARXNG_URL", "https://searx.internal.test")
    monkeypatch.setattr(http_clients, "get_external_client", lambda: client)
    monkeypatch.setattr(
        strategy_planner, "collect_context", lambda: {"assets": {}, "repo": {}, "domains": {}}
    )
    monkeypatch.setattr(strategy_bets, "read_metric", lambda _metric: None)
    monkeypatch.setattr(
        task_router, "_load_all_employee_profiles", lambda: [{"id": "test-qa-runner"}]
    )
    yield rows, seen
    asyncio.run(client.aclose())


def accept_delivered(customer, artifact, *, measured=1.0):
    goal = customer["goal"]
    outcome = customer_value_lifecycle_api.record_outcome_material(
        customer_value_lifecycle_api.OutcomeReceiptBody(
            **goal,
            idempotency_key="measured-real-csv-business-output",
            outcome_id=artifact["artifact_id"],
            artifact_sha256=artifact["artifact_sha256"],
            measured_value=measured,
            source_material_summary="Read and verified the generated CSV artifact bytes",
            source_material_sha256=artifact["artifact_sha256"],
        ),
        _admin=customer["admin"],
    )
    body = customer_value_lifecycle_api.AcceptanceReceiptBody(
        order_no=goal["order_no"],
        customer_goal_id=goal["customer_goal_id"],
        idempotency_key="original-customer-csv-acceptance",
        acceptance_id="customer-acceptance-eight",
        accepted_artifact_id=artifact["artifact_id"],
        artifact_sha256=artifact["artifact_sha256"],
        customer_confirmed=True,
    )
    with pytest.raises(HTTPException) as denied:
        customer_value_lifecycle_api.record_acceptance_receipt(body, user=customer["admin"])
    assert denied.value.status_code == 403
    accepted = customer_value_lifecycle_api.record_acceptance_receipt(body, user=customer["client"])
    assert outcome["created"] and accepted["created"]


@pytest.mark.parametrize("accepted", [True, False])
def test_market_to_sql_approval_real_csv_customer_review_and_next_cycle(
    database, csv_employee, customer, search_service, monkeypatch, accepted
):
    env = csv_employee
    monkeypatch.setattr(
        task_router, "_load_all_employee_profiles", lambda: [{"id": env["employee"]}]
    )
    template = {
        "owner_user_id": 7,
        "goal": "Validate the customer's export product opportunity",
        "limits": portfolio_fixtures.limits(),
        "period_days": 1,
        "use_llm": False,
        "input_data": {"file_path": "inputs/orders.json"},
        "market_research": query_config(env["employee"]),
    }
    discovered = asyncio.run(strategy_planner.run_scheduled_discovery(template=template))
    assert discovered["status"] == "awaiting_approval", discovered
    assert discovered["market_status"] == "observed"
    decision = discovered["registered"][0]
    state = portfolio.portfolio_status(decision)
    item = state["opportunities"][0]
    key = item["opportunity_id"]
    assert (
        state["owner_user_id"] == 7
        and item["customer_goal_bindings"][0]["customer_ref"] == "paid-user:8"
    )
    snapshot = deepcopy(item["input_data"]["market_evidence"])
    assert snapshot["sources"][0]["snapshot_sha256"] in item["source_refs"][-1]
    with pytest.raises(portfolio.PortfolioError):
        runtime.run_portfolio_cycle(decision)
    portfolio.authorize_portfolio(
        decision,
        owner_user_id=7,
        actor="admin:7",
        expected_proposal_sha256=state["proposal_sha256"],
    )
    # Both handler and completion use the real native employee path, not a mocked success.
    completed = runtime.run_portfolio_cycle(decision)
    assert completed["processed"] == 1
    state = portfolio.portfolio_status(decision)
    task = state["tasks"][key]
    assert task["status"] == "completed", task
    verification = task["execution_receipt"]["result"]["verification"]
    assert verification["passed"] and verification["files_declared"]
    file_check = next(row for row in verification["checks"] if row["name"] == "files_changed_exist")
    assert file_check["ok"] and not file_check.get("skipped")
    assert task["execution_receipt"]["result"]["path_guard"]["all_changed_files"]
    artifact = task["execution_receipt"]["delivered_artifacts"][0]
    output = env["workspace"] / artifact["output_path"]
    assert (
        output.is_file()
        and hashlib.sha256(output.read_bytes()).hexdigest() == artifact["artifact_sha256"]
    )
    assert env["extracted"] and all(not path.exists() for path in env["extracted"])
    assert b"A-7" in output.read_bytes() and not (env["caller"] / "outputs").exists()
    assert item["input_data"]["market_evidence"] == snapshot
    if accepted:
        accept_delivered(customer, artifact)
    start = portfolio._date(task["started_at"])
    moment = start + timedelta(days=1, seconds=1)

    class ReviewTime(datetime):
        @classmethod
        def now(cls, tz=UTC):
            return moment.astimezone(tz)

    monkeypatch.setattr(runtime, "datetime", ReviewTime)
    monkeypatch.setattr(strategy_bets, "_now", lambda: moment)
    review = runtime.review_portfolio(decision)
    hypothesis = review["hypotheses"][0]
    assert hypothesis["verdict"] == ("hit" if accepted else "miss")
    assert hypothesis["evidence"]["value"] == (1.0 if accepted else 0.0)
    from modstore_server import xiaoc_life_reconciliation as reconciliation
    from modstore_server import xiaoc_life_store as life
    from modstore_server.xiaoc_life_cognition import (
        cognition_messages,
        feedback_facts,
        parse_decision,
    )
    from modstore_server.xiaoc_life_policy import LifeUpdate

    for module in (life, reconciliation):
        monkeypatch.setattr(module, "get_session_factory", lambda: database)
    life.update_settings(LifeUpdate(expected_revision=1, level=6), actor_user_id=7)
    # The read-only reconciliation projects the original SQL review even while
    # autonomous spending has no configured allowance. No model supplies it.
    life._mutate(
        lambda saved, _db: saved.update(
            owner_user_id=7,
            goals=[
                {
                    "id": "original-market-goal",
                    "title": "Approved customer goal",
                    "decision_id": decision,
                }
            ],
        )
    )
    assert reconciliation.reconcile_goals()["observed"] == 1
    saved = life.read_state()
    messages, refs = cognition_messages(saved, "reflection", feedback_facts(saved))
    observed = json.loads(messages[1]["content"])["observations"][0]["business_feedback"]
    actual = observed["hypotheses"][0]
    assert actual["metric_id"] == strategy_bets.CUSTOMER_ACCEPTANCE_METRIC
    assert actual["verdict"] == hypothesis["verdict"]
    assert actual["value"] == hypothesis["evidence"]["value"]
    for name in ("window_start", "window_end", "reviewed_at", "snapshot_sha256"):
        assert actual[name] == hypothesis[name]
    assert "customer-order-eight" not in messages[1]["content"]
    with pytest.raises(ValueError):
        parse_decision(
            json.dumps(
                {
                    "action": "reflect",
                    "summary": "Invented success",
                    "evidence_refs": list(refs),
                    "business_feedback": {"hypotheses": [{"verdict": "hit"}]},
                }
            ),
            refs=refs,
            level=6,
            domain="reflection",
        )
    if not accepted:
        assert review["decision"] == "stop" and review["stop_reason"] == f"hypothesis_missed:{key}"
        accept_delivered(customer, artifact)
        assert (
            runtime.review_portfolio(decision)["hypotheses"][0]["snapshot_sha256"]
            == hypothesis["snapshot_sha256"]
        )
    captured = []
    generate = strategy_planner.generate_candidates

    async def observe_context(context, chat=None):
        captured.append(context)
        return await generate(context, chat=chat)

    monkeypatch.setattr(strategy_planner, "generate_candidates", observe_context)
    next_cycle = asyncio.run(
        strategy_planner.run_scheduled_discovery(template=template, now=moment)
    )
    assert next_cycle["status"] == "awaiting_approval"
    assert (
        captured[0]["prior_outcome_reviews"][-1]["hypotheses"][0]["verdict"]
        == hypothesis["verdict"]
    )
    assert len(search_service[1]) == 2


def test_market_source_window_host_and_snapshot_use_real_searxng_http_contract(
    customer, search_service
):
    rows, seen = search_service
    original = deepcopy(rows[0])
    for label, values in (
        ("old", {"publishedDate": (datetime.now(UTC) - timedelta(days=90)).isoformat()}),
        ("future", {"publishedDate": (datetime.now(UTC) + timedelta(days=1)).isoformat()}),
        ("undated", {"publishedDate": None}),
        ("wrong-source", {"url": "https://other.example.net/new-product"}),
    ):
        rows.insert(0, {**original, "title": label, **values})
    result = asyncio.run(
        market.discover_market(query_config(), owner_user_id=7, employees=["test-qa-runner"])
    )
    assert len(result["evidence"]) == 1
    assert result["rejected_sources"] == {
        "publication_date_outside_window": 2,
        "publication_date_unknown": 1,
        "source_host_not_allowed": 1,
    }
    source = result["evidence"][0]
    assert source["url"] == original["url"] and source["observed_at"] and source["published_at"]
    assert "customer-order" not in str(seen[0].url) and "customer-csv-goal" not in str(seen[0].url)
    frozen = {
        key: value for key, value in source.items() if key not in {"snapshot_sha256", "evidence_id"}
    }
    assert source["snapshot_sha256"] == portfolio.digest(frozen)


def test_unavailable_market_has_no_fabricated_candidate(customer, search_service, monkeypatch):
    monkeypatch.delenv("MODSTORE_SEARXNG_URL")
    result = asyncio.run(
        runtime.discover_portfolio_opportunities(
            owner_user_id=7,
            goal="Validate original customer demand",
            limits=portfolio_fixtures.limits(),
            use_llm=False,
            market_research=query_config(),
        )
    )
    assert result["opportunities"] == []
    assert result["company_evidence"]["market"]["reason"] == "MODSTORE_SEARXNG_URL_not_configured"
    assert not search_service[1]


def test_original_customer_binding_is_resolved_before_outbound_search(customer, search_service):
    for override in (
        {"customer_user_id": 7},
        {"order_no": "unrelated-order"},
        {"domain_id": "invented-domain"},
    ):
        with pytest.raises(portfolio.PortfolioError):
            asyncio.run(
                market.discover_market(
                    query_config(**override), owner_user_id=7, employees=["test-qa-runner"]
                )
            )
    assert not search_service[1]


def test_customer_acceptance_does_not_claim_an_unmet_original_kpi(database, customer):
    binding = strategic_customer_outcomes.load_customer_goal_bindings(
        8, "customer-order-eight", ["customer-csv-goal"]
    )
    started = datetime.now(UTC)
    artifact = {"artifact_id": "strategy-delivered-business-csv", "artifact_sha256": "b" * 64}
    status = {
        "owner_user_id": 7,
        "opportunities": [
            portfolio_fixtures.opportunity(
                customer_goal_ids=["customer-csv-goal"], customer_goal_bindings=binding
            )
        ],
        "tasks": {
            "a": {
                "status": "completed",
                "completed_at": started.isoformat(),
                "execution_receipt": artifact,
            }
        },
    }
    accept_delivered(customer, artifact, measured=0.0)
    result = strategic_customer_outcomes.customer_acceptance_outcome(
        status, window_start=started, window_end=datetime.now(UTC)
    )
    assert result["status"] == "verified" and result["acceptance_ratio"] == 0.0


@pytest.mark.parametrize("failure", ["missing_file", "handler_error"])
def test_native_file_verification_retains_file_and_handler_failures(tmp_path, failure):
    from modstore_server.employee_verification import run_verification

    path = tmp_path / "output.csv"
    if failure != "missing_file":
        path.write_text("order,quantity\nA-7,3\n")
    native = {
        "ok": failure != "handler_error",
        "summary": "Converted customer orders into CSV output",
        "items": [{"output_path": str(path)}],
    }
    result = run_verification(
        employee_id="csv-generate-employee",
        task="Convert the customer orders",
        reasoning={"skipped_cognition": True},
        config={},
        project_root=tmp_path,
        result={"outputs": [{"handler": "direct_python", "ok": native["ok"], "output": native}]},
    )
    assert result["passed"] is False
    check = "files_changed_exist" if failure == "missing_file" else "status_honest"
    assert next(row for row in result["checks"] if row["name"] == check)["ok"] is False
