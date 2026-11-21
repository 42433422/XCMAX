"""Approved long-running engineering phases consume one original SQL mandate."""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from modstore_server import strategic_company_resources as company
from modstore_server import strategic_portfolio as portfolio
from modstore_server import strategic_portfolio_usage as usage
from modstore_server import strategic_portfolio_worker as worker
from modstore_server import strategic_remote_bridge as remote
from modstore_server import strategic_remote_life as persistent
from modstore_server import strategic_remote_receipts as remote_receipts
from modstore_server import strategic_workspace_bridge as bridge
from modstore_server import strategic_workspace_grants as grants
from modstore_server import strategic_workspace_receipts as receipts
from modstore_server import xiaoc_life_reconciliation as reconciliation
from modstore_server import xiaoc_life_store as life
from modstore_server.db.identity import User
from modstore_server.db.mac_control import MacControlTask
from modstore_server.xiaoc_life_policy import LifeUpdate
from modstore_server.xiaoc_life_runtime import CyclePorts
from tests import test_strategic_remote_bridge as report_tests
from tests import test_strategic_remote_life_scope as short
from tests import test_strategic_workspace_bridge as original

database = original.database
configured = original.configured
workspace = original.workspace


@pytest.fixture
def long_env(workspace, monkeypatch):
    state = workspace
    state.clock = SimpleNamespace(now=datetime.now(UTC))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return state.clock.now.astimezone(tz) if tz else state.clock.now.replace(tzinfo=None)

    for module in (
        portfolio,
        usage,
        worker,
        company,
        remote,
        bridge,
        grants,
        receipts,
        remote_receipts,
        original,
        report_tests,
    ):
        monkeypatch.setattr(module, "datetime", Clock)
    for module in (life, reconciliation):
        monkeypatch.setattr(module, "get_session_factory", lambda: state.factory)
        monkeypatch.setattr(module, "utcnow", lambda: state.clock.now)

    def make(*, expiry_seconds=3600, life_seconds=86400, option=True):
        state.remote_kind = "workspace"
        if option:
            state.opportunity["input_data"]["remote_execution"]["life_lease"] = {
                "mode": "persistent_phases",
                "expires_at": (state.clock.now + timedelta(seconds=expiry_seconds)).isoformat(),
            }
        life.update_settings(
            LifeUpdate(
                expected_revision=1,
                level=4,
                policy={
                    "daily_token_limit": 1_000_000,
                    "authorization_expires_at": (
                        state.clock.now + timedelta(seconds=life_seconds)
                    ).isoformat(),
                },
            ),
            actor_user_id=7,
        )
        made = portfolio.create_portfolio_proposal(
            owner_user_id=7,
            goal="Deliver the original approved engineering work",
            period="xiaoc-life:remote",
            limits=state.caps,
            opportunities=[state.opportunity],
            idempotency_key="long-life-original",
        )
        state.decision_id = made["decision"]["decision_id"]
        portfolio.authorize_portfolio(
            state.decision_id,
            owner_user_id=7,
            actor="admin:7",
            expected_proposal_sha256=made["decision"]["decision_payload"]["proposal_sha256"],
        )
        seed = life.claim_cycle(domain="enterprise", reserve_tokens=0)
        life.finish_cycle(
            seed,
            status="completed",
            summary="Observe approved original work",
            evidence_refs=["retort:" + state.request_id],
            actual_tokens=0,
            goals=[
                {
                    "id": "remote",
                    "title": "Original engineering work",
                    "domain": "enterprise",
                    "decision_id": state.decision_id,
                    "status": "approved",
                    "evidence_refs": ["original-order"],
                }
            ],
        )
        life.wake(actor_user_id=7, expected_revision=life.read_state()["revision"])
        state.life_claim = life.claim_cycle(domain="enterprise", reserve_tokens=200000)
        with life.life_execution_scope(state.life_claim):
            ports = CyclePorts(state.life_claim)
            state.observed = asyncio.run(ports.advance_portfolio(ports.approved_portfolio()))
            ports.finish(state.observed)
        return state

    state.make = make
    return state


@pytest.fixture
def long_remote(long_env):
    state = long_env.make()
    assert state.observed["status"] == "awaiting_worker", state.observed
    return state


def advance(state, seconds):
    state.clock.now += timedelta(seconds=seconds)


def start_after_queue(state):
    advance(state, 360)
    state.github.phase("execute")
    return short.claim_remote(state)


def enter_resume(state):
    execute = deepcopy(state.github.jobs[0])
    execute.update(
        status="completed", conclusion="success", completed_at=state.clock.now.isoformat()
    )
    advance(state, 360)
    state.github.phase("resume")
    state.github.jobs[0] = execute


def finish_original(state):
    previous = deepcopy(state.github.jobs)
    state.github.phase("completed")
    for index, job in enumerate(previous):
        if job["status"] != "completed":
            job.update(
                status="completed", conclusion="success", completed_at=state.clock.now.isoformat()
            )
        state.github.jobs[index] = job
    original.original_terminal(state)
    assert remote_receipts.reconcile_request(state.request_id)
    assert not remote_receipts.reconcile_request(state.request_id)


def resume_identity(state):
    return {
        key: value
        for key, value in {**state.bootstrap, "phase": "resume"}.items()
        if key
        in {"run_id", "run_attempt", "repository", "source_sha", "phase", "execution_isolation"}
    }


def test_approved_long_task_survives_queue_and_renews_only_the_original_native_phase(
    long_remote, monkeypatch
):
    state = long_remote
    request, _, _ = remote.read_request(state.request_id)
    active = short.active_cycle(state)
    assert active["deadline"] == state.life_claim["deadline"]
    assert (
        portfolio._date(active["deadline"]) - portfolio._date(active["started_at"])
    ).total_seconds() == 300
    assert active["remote_task"]["request_sha256"] == portfolio.digest(request)
    assert active["remote_task"]["proposal_sha256"] == request["binding"]["proposal_sha256"]
    assert active["remote_task"]["source_sha"] == state.protocol["source_sha"]
    assert portfolio._date(request["deadline"]) > portfolio._date(active["deadline"])
    first = start_after_queue(state)
    assert life.claim_cycle(domain="enterprise", reserve_tokens=200000) is None
    assert life.read_state()["unknown_usage"] is False
    with pytest.raises(life.LifePolicyError), life.life_execution_scope(state.life_claim):
        pytest.fail("ordinary cognition cannot use the extended engineering lease")
    short.native_model(state, monkeypatch)
    old_headers = dict(state.model_headers)
    # An active native phase cannot be renewed even though the task envelope is long.
    denied = state.client.post(
        state.control + "/claim", json=resume_identity(state), headers=state.management
    )
    assert denied.status_code == 409
    enter_resume(state)
    assert receipts.reconcile_request(state.request_id)
    assert original.company_tests.totals(state.company_id)["slots"] == 0
    original.bootstrap(state, "resume")
    second = original.grant(state, original.task(state, role="verify", attempt="c" * 32))
    assert second["grant_id"] != first["grant_id"]
    assert second["run_id"] == first["run_id"] == 42
    assert portfolio._date(second["deadline"]) <= portfolio._date(request["deadline"])
    assert state.client.get(state.control + "/v1/models", headers=old_headers).status_code == 409
    response = state.client.post(
        state.control + "/v1/responses",
        headers=state.model_headers,
        json=short.response_payload(stream=True),
    )
    assert response.status_code == 200, response.text
    assert '"type":"response.completed"' in response.text
    saved = short.saved_task(state)
    assert len(saved["calls"]) == 2
    assert sorted(call["caller_binding"]["phase"] for call in saved["calls"].values()) == [
        "execute",
        "resume",
    ]
    assert sum(call["actual_tokens"] for call in saved["calls"].values()) == 26
    assert len(state.github.writes) == 1
    assert short.active_cycle(state)["cycle_id"] == state.life_claim["cycle_id"]
    finish_original(state)
    assert short.saved_task(state)["status"] == "completed"
    assert reconciliation.reconcile_usage()["resolved"] == 1
    assert life.read_state()["budget"]["used_tokens"] == 26
    assert life.read_state()["budget"]["reserved_tokens"] == 0


@pytest.mark.parametrize(
    "change", ["pause", "revision", "owner_revoked", "portfolio_stop", "company_stop", "expiry"]
)
def test_explicit_long_lease_revocation_stops_calls_but_keeps_readonly_known_settlement(
    long_remote, monkeypatch, change
):
    state = long_remote
    start_after_queue(state)
    short.native_model(state, monkeypatch)
    before = short.saved_task(state)
    if change == "expiry":
        state.clock.now = portfolio._date(
            remote.read_request(state.request_id)[0]["deadline"]
        ) + timedelta(seconds=1)
    elif change == "owner_revoked":
        with state.factory() as session:
            session.get(User, 7).is_admin = False
            session.commit()
    elif change == "portfolio_stop":
        portfolio.stop_portfolio(
            state.decision_id, owner_user_id=7, actor="admin:7", reason="original mandate stopped"
        )
    elif change == "company_stop":
        company.revoke_company(
            state.company_id,
            authorizer_user_id=7,
            actor="admin:7",
            reason="original company mandate stopped",
        )
    else:
        edit = (
            {"paused": True}
            if change == "pause"
            else {"mission": "Updated mission requires review"}
        )
        life.update_settings(
            LifeUpdate(expected_revision=life.read_state()["revision"], **edit), actor_user_id=7
        )
    denied = state.client.post(
        state.control + "/v1/responses", headers=state.model_headers, json=short.response_payload()
    )
    assert denied.status_code == 409, denied.text
    assert short.saved_task(state)["calls"] == before["calls"]
    closed = state.client.post(
        state.control + "/close-grant",
        headers=state.bootstrap_headers,
        json={"phase": "execute", "grant_id": state.grant["grant_id"]},
    )
    assert closed.status_code == 200, closed.text
    assert life.read_state()["budget"]["reserved_tokens"] == 200000
    finish_original(state)
    assert reconciliation.reconcile_usage()["resolved"] == 1
    assert life.read_state()["budget"]["used_tokens"] == 13
    assert life.read_state()["budget"]["reserved_tokens"] == 0
    if change == "portfolio_stop":
        assert (
            portfolio.portfolio_status(state.decision_id)["stop_reason"]
            == "original mandate stopped"
        )


def test_long_lease_does_not_renew_unknown_usage_or_return_its_budget(long_remote, monkeypatch):
    state = long_remote
    start_after_queue(state)
    short.native_model(state, monkeypatch, meter="absent")
    before = short.saved_task(state)
    enter_resume(state)
    assert not receipts.reconcile_request(state.request_id)
    response = state.client.post(
        state.control + "/claim", json=resume_identity(state), headers=state.management
    )
    assert response.status_code == 409
    assert short.saved_task(state) == before
    assert original.company_tests.totals(state.company_id)["slots"] == 1
    assert life.claim_cycle(domain="enterprise", reserve_tokens=200000) is None
    finish_original(state)
    assert short.saved_task(state)["status"] == "unknown"
    assert short.saved_task(state)["calls"] == before["calls"]
    assert reconciliation.reconcile_usage()["resolved"] == 0
    assert life.read_state()["budget"]["reserved_tokens"] == 200000
    assert life.read_state()["budget"]["used_tokens"] == 0


@pytest.mark.parametrize("limit", ["life", "portfolio"])
def test_long_task_cannot_exceed_approved_parent_expiry(long_env, limit):
    if limit == "portfolio":
        long_env.caps["expires_at"] = (long_env.clock.now + timedelta(seconds=1800)).isoformat()
    state = long_env.make(life_seconds=1800 if limit == "life" else 86400)
    assert state.observed["status"] != "awaiting_worker"
    with state.factory() as session:
        assert session.get(MacControlTask, UUID(state.request_id).hex) is None
    assert not state.github.writes
    assert "remote_task" not in (short.active_cycle(state) or {})


def test_long_registration_and_original_request_roll_back_in_one_transaction(long_env, monkeypatch):
    register = persistent.register

    def interrupted(*args):
        register(*args)
        raise portfolio.PortfolioError("ordinary dispatch persistence interrupted")

    monkeypatch.setattr(persistent, "register", interrupted)
    state = long_env.make()
    with state.factory() as session:
        assert session.get(MacControlTask, UUID(state.request_id).hex) is None
    assert "remote_task" not in (short.active_cycle(state) or {})
    assert not state.github.writes


def test_no_opt_in_keeps_the_original_300_second_gate(long_env):
    state = long_env.make(option=False)
    assert state.observed["status"] == "awaiting_worker"
    advance(state, 360)
    assert state.collect()["reason"] == "strategic_company_budget_binding_required"
    assert not state.github.writes
    assert life.read_state()["budget"]["reserved_tokens"] == 200000


def test_long_scope_cannot_be_used_for_another_task_or_new_cognition(long_remote):
    state = long_remote
    start_after_queue(state)
    request = remote.read_request(state.request_id)[0]
    with remote.authorization_scope(request):
        with pytest.raises(life.LifePolicyError):
            life.require_life_task_capacity(portfolio.portfolio_status(state.decision_id), 1)
        with (
            usage.portfolio_usage_scope(
                state.decision_id, "other-opportunity", request["binding"]["lease_token"]
            ),
            pytest.raises(life.LifePolicyError),
        ):
            usage.prepare_platform_call("openai", "approved-model", [], 10)
    assert not short.saved_task(state)["calls"]
    assert life.current_life_claim() is None


def test_local_queue_cannot_cancel_or_reinterpret_remote_waiting_work(long_remote, monkeypatch):
    from modstore_server.strategic_portfolio_runtime import execute_portfolio_worker

    state = long_remote
    start_after_queue(state)
    short.native_model(state, monkeypatch)
    enter_resume(state)
    assert receipts.reconcile_request(state.request_id)
    before = short.saved_task(state)
    company_before = original.company_tests.totals(state.company_id)
    life_before = life.read_state()["budget"]
    assert before["status"] == "waiting"
    with pytest.raises(portfolio.PortfolioError):
        execute_portfolio_worker(
            before["worker_binding"],
            owner_user_id=7,
            execute=lambda _task: pytest.fail("remote work cannot become a local queue task"),
        )
    assert short.saved_task(state) == before
    assert original.company_tests.totals(state.company_id) == company_before
    assert life.read_state()["budget"] == life_before
    assert reconciliation.reconcile_usage()["resolved"] == 0


def test_concurrent_resume_claims_issue_one_new_phase_grant(long_remote, monkeypatch):
    state = long_remote
    start_after_queue(state)
    short.native_model(state, monkeypatch)
    enter_resume(state)
    assert receipts.reconcile_request(state.request_id)
    identity = resume_identity(state)

    def claim():
        return state.client.post(state.control + "/claim", json=identity, headers=state.management)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: claim(), range(2)))
    assert sorted(response.status_code for response in results) == [200, 409]
    assert original.company_tests.totals(state.company_id)["slots"] == 1
    assert len(remote.read_request(state.request_id)[1]["phases"]) == 2
    assert len(state.github.writes) == 1


@pytest.mark.asyncio
async def test_pending_old_call_blocks_resume_and_closure_keeps_unknown_cost(
    long_remote, monkeypatch
):
    from starlette.requests import Request

    from modstore_server.strategic_remote_api import responses
    from tests.test_strategic_responses import _http

    state = long_remote
    start_after_queue(state)
    seen = _http(monkeypatch, (state.decision_id, short.saved_task(state)))
    body = json.dumps(short.response_payload(stream=True)).encode()

    async def receive():
        return {"type": "http.request", "body": body}

    request = Request(
        {"type": "http", "method": "POST", "path": state.control + "/v1/responses", "headers": []},
        receive,
    )
    response = await responses(
        state.request_id, request, authorization=state.model_headers["Authorization"]
    )
    assert b"response.created" in await anext(response.body_iterator)
    before = short.saved_task(state)
    assert next(iter(before["calls"].values()))["status"] == "pending"
    enter_resume(state)
    denied = state.client.post(
        state.control + "/claim", json=resume_identity(state), headers=state.management
    )
    assert denied.status_code == 409
    assert short.saved_task(state) == before
    assert original.company_tests.totals(state.company_id)["slots"] == 1
    await response.close_source()
    assert all(client.is_closed() for client in seen["clients"])
    assert next(iter(short.saved_task(state)["calls"].values()))["status"] == "unknown"
    finish_original(state)
    assert reconciliation.reconcile_usage()["resolved"] == 0
    assert life.read_state()["budget"]["reserved_tokens"] == 200000
