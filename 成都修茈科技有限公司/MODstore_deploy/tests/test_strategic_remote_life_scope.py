"""Remote consumers retain the original XiaoC lease without local-queue cancellation."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from modstore_server import strategic_portfolio as portfolio
from modstore_server import strategic_portfolio_worker as local_worker
from modstore_server import strategic_remote_bridge as remote
from modstore_server import strategic_remote_receipts as remote_receipts
from modstore_server import strategic_workspace_bridge as workspace_bridge
from modstore_server import strategic_workspace_receipts as workspace_receipts
from modstore_server import xiaoc_life_reconciliation as reconciliation
from modstore_server import xiaoc_life_store as life
from modstore_server.db.xiaoc_life import XiaoCLifeState
from modstore_server.xiaoc_life_policy import IDENTITY_ID, LifeUpdate
from modstore_server.xiaoc_life_runtime import CyclePorts
from tests import test_strategic_company_resources as company_tests
from tests import test_strategic_remote_bridge as report_tests
from tests import test_strategic_workspace_bridge as workspace_tests
from tests.test_strategic_responses import _http

database = workspace_tests.database
configured = workspace_tests.configured
workspace = workspace_tests.workspace


@pytest.fixture(params=["workspace", "report"])
def life_remote(workspace, monkeypatch, request):
    state = workspace
    for module in (life, reconciliation):
        monkeypatch.setattr(module, "get_session_factory", lambda: state.factory)
    life.update_settings(
        LifeUpdate(
            expected_revision=1,
            level=4,
            policy={
                "daily_token_limit": 1_000_000,
                "authorization_expires_at": (life.utcnow() + timedelta(days=1)).isoformat(),
            },
        ),
        actor_user_id=7,
    )
    state.remote_kind = request.param
    if request.param == "report":
        monkeypatch.setenv("MODSTORE_STRATEGIC_REPORTS_ENABLED", "1")
        state.opportunity["input_data"]["remote_execution"] = {
            "kind": remote.KIND,
            "repository": report_tests.REPO,
            "source_sha": report_tests.SOURCE,
            "provider": "openai",
            "model": "approved-model",
        }
    made = portfolio.create_portfolio_proposal(
        owner_user_id=7,
        goal="Original approved remote goal",
        period="xiaoc-life:remote",
        limits=state.caps,
        opportunities=[state.opportunity],
        idempotency_key="life-original-remote",
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
        summary="Observe original approved work",
        evidence_refs=["retort:" + state.request_id],
        actual_tokens=0,
        goals=[
            {
                "id": "remote",
                "title": "Original remote work",
                "domain": "enterprise",
                "decision_id": state.decision_id,
                "status": "approved",
                "evidence_refs": ["original-work-order"],
            }
        ],
    )
    life.wake(actor_user_id=7, expected_revision=life.read_state()["revision"])
    state.life_claim = life.claim_cycle(domain="enterprise", reserve_tokens=200000)
    with life.life_execution_scope(state.life_claim):
        ports = CyclePorts(state.life_claim)
        observed = asyncio.run(ports.advance_portfolio(ports.approved_portfolio()))
        assert observed["status"] == "awaiting_worker", observed
        result = portfolio.portfolio_status(state.decision_id)
        assert result["tasks"]["a"]["status"] == "waiting", result["tasks"]["a"]
    state.request_id = result["tasks"]["a"]["worker_binding"]["receipt_id"]
    state.control = f"/api/service/mac-control/strategic-runs/{state.request_id}"
    state.identity = {
        "run_id": 42,
        "run_attempt": 1,
        "repository": report_tests.REPO,
        "source_sha": report_tests.SOURCE,
    }
    life.defer_cycle(
        state.life_claim,
        summary=observed["summary"],
        evidence_refs=ports.evidence,
        details=ports.details,
    )
    return state


def claim_remote(state):
    assert life.current_life_claim() is None
    if state.remote_kind == "workspace":
        assert state.collect().get(
            "event_id"
        ), "original lifecycle scope was not restored before runner admission"
        workspace_tests.bootstrap(state)
        return workspace_tests.grant(state, workspace_tests.task(state))
    return report_tests.claim(state)


def test_original_life_cycle_reaches_the_existing_remote_consumer(life_remote):
    grant = claim_remote(life_remote)
    assert grant["request_id"] == life_remote.request_id
    request, _, _ = remote.read_request(life_remote.request_id)
    bound = request["binding"]["life_scope"]
    assert set(bound) == local_worker._LIFE_FIELDS
    assert bound == {key: life_remote.life_claim[key] for key in local_worker._LIFE_FIELDS}
    assert portfolio._date(grant["deadline"]) <= portfolio._date(bound["deadline"])
    assert portfolio._date(request["deadline"]) <= portfolio._date(bound["deadline"])
    assert (
        portfolio._date(bound["deadline"]) - portfolio._date(life_remote.life_claim["started_at"])
    ).total_seconds() == 300
    assert life.current_life_claim() is None


def saved_task(state):
    return portfolio.portfolio_status(state.decision_id)["tasks"]["a"]


def active_cycle(state):
    with state.factory() as session:
        return json.loads(session.get(XiaoCLifeState, IDENTITY_ID).state_json)["active_cycle"]


def response_payload(*, stream=False):
    return {
        "model": "approved-model",
        "input": "Complete the original approved report work",
        "store": False,
        "max_output_tokens": 16,
        "stream": stream,
    }


def native_model(state, monkeypatch, *, stream=False, meter="reported"):
    seen = _http(monkeypatch, (state.decision_id, saved_task(state)), meter=meter)
    response = state.client.post(
        state.control + "/v1/responses",
        headers=state.model_headers,
        json=response_payload(stream=stream),
    )
    assert response.status_code == 200, response.text
    assert len(seen["requests"]) == 1
    assert all(client.is_closed() for client in seen["clients"])
    assert all(response.is_closed for response in seen["responses"])
    return response


def end_native_work(state, monkeypatch):
    if state.remote_kind == "workspace":
        state.github.phase("completed")
        workspace_tests.original_terminal(state)
    else:
        receipt = report_tests.notify(state)
        state.github.phase("completed")
        state.github.publish(receipt)
        report_tests.download_transport(state, monkeypatch)
    assert remote_receipts.reconcile_request(state.request_id)
    assert not remote_receipts.reconcile_request(state.request_id)


@pytest.mark.parametrize("stream", [False, True])
def test_remote_raw_sdk_calls_reenter_original_life_scope_and_journal_sql(
    life_remote, monkeypatch, stream
):
    state = life_remote
    claim_remote(state)
    response = native_model(state, monkeypatch, stream=stream)
    if stream:
        assert '"type":"response.completed"' in response.text
    call = next(iter(saved_task(state)["calls"].values()))
    assert call["status"] == "settled" and call["actual_tokens"] == 13
    assert call["response_id"] == "resp-orders"
    active = active_cycle(state)
    assert active["cycle_id"] == state.life_claim["cycle_id"]
    assert active["deadline"] == state.life_claim["deadline"]
    assert [step["request_id"] for step in active["steps"] if step["kind"] == "model"] == list(
        saved_task(state)["calls"]
    )
    assert life.current_life_claim() is None
    if state.remote_kind == "workspace":
        assert workspace_bridge.candidate_metered(
            state.request_id,
            {key: state.grant[key] for key in ("task_id", "subtask_id", "attempt_id")},
        )
    assert reconciliation.reconcile_usage()["resolved"] == 0
    end_native_work(state, monkeypatch)
    assert saved_task(state)["status"] == "completed"
    assert reconciliation.reconcile_usage()["resolved"] == 1
    assert reconciliation.reconcile_usage()["resolved"] == 0
    assert life.read_state()["budget"]["used_tokens"] == 13
    assert life.read_state()["budget"]["reserved_tokens"] == 0
    assert life.read_state()["activity"] is None


@pytest.mark.parametrize("change", ["pause", "expiry"])
def test_life_revocation_preserves_remote_responsibility_and_allows_readonly_receipts(
    life_remote, monkeypatch, change
):
    state = life_remote
    claim_remote(state)
    native_model(state, monkeypatch)
    before = saved_task(state)
    cancel = MagicMock()
    monkeypatch.setattr(local_worker, "_cancel_waiting_worker", cancel)
    if change == "expiry":
        later = portfolio._date(state.life_claim["deadline"]) + timedelta(seconds=1)
        monkeypatch.setattr(life, "utcnow", lambda: later)
    else:
        life.update_settings(
            LifeUpdate(expected_revision=life.read_state()["revision"], paused=True),
            actor_user_id=7,
        )
    denied = state.client.post(
        state.control + "/v1/responses",
        headers=state.model_headers,
        json=response_payload(),
    )
    assert denied.status_code == 409, denied.text
    assert saved_task(state) == before
    assert company_tests.totals(state.company_id)["slots"] == 1
    assert life.read_state()["budget"]["reserved_tokens"] == 200000
    assert reconciliation.reconcile_usage()["resolved"] == 0
    if state.remote_kind == "workspace":
        response = state.client.post(
            state.control + "/close-grant",
            json={"phase": "execute", "grant_id": state.grant["grant_id"]},
            headers=state.bootstrap_headers,
        )
        assert response.status_code == 200, response.text
        assert saved_task(state) == before
    end_native_work(state, monkeypatch)
    cancel.assert_not_called()
    assert saved_task(state)["status"] == "completed"
    assert saved_task(state)["actual_tokens"] == 13
    assert company_tests.totals(state.company_id)["slots"] == 0
    assert reconciliation.reconcile_usage()["resolved"] == 1
    assert life.read_state()["budget"]["reserved_tokens"] == 0
    assert life.read_state()["budget"]["used_tokens"] == 13
    assert life.read_state()["paused"] == (change == "pause")
    assert life.current_life_claim() is None


def test_unknown_usage_survives_expiry_native_terminal_and_life_reconciliation(
    life_remote, monkeypatch
):
    state = life_remote
    claim_remote(state)
    native_model(state, monkeypatch, meter="absent")
    call = next(iter(saved_task(state)["calls"].values()))
    assert call["status"] == "unknown" and "actual_tokens" not in call
    later = portfolio._date(state.life_claim["deadline"]) + timedelta(seconds=1)
    monkeypatch.setattr(life, "utcnow", lambda: later)
    end_native_work(state, monkeypatch)
    saved = saved_task(state)
    assert saved["status"] == "unknown"
    assert next(iter(saved["calls"].values())) == call
    assert company_tests.totals(state.company_id)["slots"] == 1
    assert company_tests.totals(state.company_id)["held"]["tokens"] > 0
    assert reconciliation.reconcile_usage()["resolved"] == 0
    assert life.read_state()["budget"]["reserved_tokens"] == 200000
    assert life.read_state()["budget"]["used_tokens"] == 0
    assert life.claim_cycle(domain="enterprise", reserve_tokens=200000) is None
    assert active_cycle(state)["cycle_id"] == state.life_claim["cycle_id"]


@pytest.mark.parametrize("life_remote", ["workspace"], indirect=True)
def test_existing_resume_phase_uses_the_same_live_cycle_and_deadline(life_remote, monkeypatch):
    state = life_remote
    claim_remote(state)
    native_model(state, monkeypatch)
    original = active_cycle(state)
    state.github.phase("resume")
    assert workspace_receipts.reconcile_request(state.request_id)
    assert company_tests.totals(state.company_id)["slots"] == 0
    workspace_tests.bootstrap(state, "resume")
    grant = workspace_tests.grant(
        state, workspace_tests.task(state, role="verify", attempt="c" * 32)
    )
    assert portfolio._date(grant["deadline"]) <= portfolio._date(original["deadline"])
    assert company_tests.totals(state.company_id)["slots"] == 1
    response = state.client.post(
        state.control + "/v1/responses",
        headers=state.model_headers,
        json=response_payload(stream=True),
    )
    assert response.status_code == 200, response.text
    assert '"type":"response.completed"' in response.text
    calls = list(saved_task(state)["calls"].values())
    assert sorted(call["caller_binding"]["phase"] for call in calls) == ["execute", "resume"]
    assert sum(call["actual_tokens"] for call in calls) == 26
    assert active_cycle(state)["cycle_id"] == original["cycle_id"]
    assert active_cycle(state)["deadline"] == original["deadline"]
    end_native_work(state, monkeypatch)
    assert reconciliation.reconcile_usage()["resolved"] == 1
    assert life.read_state()["budget"]["used_tokens"] == 26


@pytest.mark.parametrize("life_remote", ["workspace"], indirect=True)
def test_idle_remote_phase_does_not_renew_expired_original_cycle(life_remote, monkeypatch):
    state = life_remote
    claim_remote(state)
    native_model(state, monkeypatch)
    later = portfolio._date(state.life_claim["deadline"]) + timedelta(seconds=1)
    monkeypatch.setattr(life, "utcnow", lambda: later)
    state.github.phase("resume")
    assert workspace_receipts.reconcile_request(state.request_id)
    saved = saved_task(state)
    assert saved["status"] == "waiting" and saved["worker_capacity"]["state"] == "idle"
    assert company_tests.totals(state.company_id)["slots"] == 0
    assert company_tests.totals(state.company_id)["held"]["tokens"] > 0
    response = state.client.post(
        state.control + "/claim",
        headers=state.management,
        json={
            key: value
            for key, value in {**state.bootstrap, "phase": "resume"}.items()
            if key
            in {"run_id", "run_attempt", "repository", "source_sha", "phase", "execution_isolation"}
        },
    )
    assert response.status_code == 409, response.text
    assert saved_task(state) == saved
    assert life.read_state()["budget"]["reserved_tokens"] == 200000
    assert life.claim_cycle(domain="enterprise", reserve_tokens=200000) is None
    assert active_cycle(state)["deadline"] == state.life_claim["deadline"]
    end_native_work(state, monkeypatch)
    assert reconciliation.reconcile_usage()["resolved"] == 1


@pytest.mark.asyncio
async def test_stream_expiry_closes_real_sdk_without_clearing_unknown_usage(
    life_remote, monkeypatch
):
    from starlette.requests import Request

    from modstore_server.strategic_remote_api import responses

    state = life_remote
    claim_remote(state)
    seen = _http(monkeypatch, (state.decision_id, saved_task(state)))
    body = json.dumps(response_payload(stream=True)).encode()

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
    later = portfolio._date(state.life_claim["deadline"]) + timedelta(seconds=1)
    monkeypatch.setattr(life, "utcnow", lambda: later)
    remainder = b"".join([item async for item in response.body_iterator])
    assert b"strategic_budget_stopped" in remainder
    assert all(client.is_closed() for client in seen["clients"])
    assert all(response.is_closed for response in seen["responses"])
    assert life.current_life_claim() is None
    call = next(iter(saved_task(state)["calls"].values()))
    assert call["status"] == "unknown" and "actual_tokens" not in call
    assert len(seen["requests"]) == 1
    end_native_work(state, monkeypatch)
    assert reconciliation.reconcile_usage()["resolved"] == 0
    assert life.read_state()["budget"]["reserved_tokens"] == 200000
