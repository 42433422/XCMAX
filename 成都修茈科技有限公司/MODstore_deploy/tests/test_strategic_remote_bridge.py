"""Hosted business reports consume the real SDK/SQL path and native artifacts."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modstore_server import customer_ticket_github, llm_key_resolver
from modstore_server import strategic_portfolio as p
from modstore_server import strategic_portfolio_runtime as runtime
from modstore_server import strategic_portfolio_usage as usage
from modstore_server import strategic_remote_bridge as bridge
from modstore_server import strategic_remote_receipts as receipts
from modstore_server.api.deps import get_db
from modstore_server.mac_control_dispatch_api import router
from tests import test_strategic_portfolio as strategic_tests
from tests.test_strategic_responses import _http, _payload

database = strategic_tests.database
TOKEN = "ordinary-dispatch-service-token-32-characters"
SOURCE = "a" * 40
REPO = "42433422/XCMAX"


class GitHub:
    def __init__(self):
        self.writes = []
        self.request_id = None
        self.run_state = "in_progress"
        self.conclusion = None
        self.artifact = None
        self.archive = b""

    def __call__(self, method, path, body=None):
        if path == f"/repos/{REPO}/commits/main":
            return {"sha": SOURCE}
        if method == "POST":
            self.writes.append((path, body))
            self.request_id = body["inputs"]["request_id"]
            return {}
        if path == f"/repos/{REPO}/actions/runs/42":
            return {
                "id": 42,
                "path": ".github/workflows/fhd-para-github-worker.yml",
                "event": "workflow_dispatch",
                "head_branch": "main",
                "head_sha": SOURCE,
                "run_attempt": 1,
                "repository": {"full_name": REPO},
                "display_title": "para-workspace-" + self.request_id,
                "status": self.run_state,
                "conclusion": self.conclusion,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        if path.endswith("/jobs?per_page=100"):
            return {
                "total_count": 1,
                "jobs": [
                    {
                        "name": "employee-workspace",
                        "run_id": 42,
                        "conclusion": self.conclusion,
                    }
                ],
            }
        if path.endswith("/artifacts?per_page=100"):
            return {
                "total_count": 1 if self.artifact else 0,
                "artifacts": [self.artifact] if self.artifact else [],
            }
        if "/actions/workflows/" in path and "/runs?" in path:
            return {
                "total_count": 1,
                "workflow_runs": [self("GET", f"/repos/{REPO}/actions/runs/42")],
            }
        raise AssertionError((method, path, body))

    def publish(self, receipt, report="Support cases decreased from 10 to 8."):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr("execution.json", json.dumps(receipt))
            archive.writestr("report.md", report)
        self.archive = data.getvalue()
        self.artifact = {
            "id": 900,
            "name": "para-strategic-report-" + self.request_id,
            "expired": False,
            "digest": "sha256:" + hashlib.sha256(self.archive).hexdigest(),
            "workflow_run": {"id": 42, "head_sha": SOURCE},
        }
        self.run_state, self.conclusion = "completed", "success"


@pytest.fixture
def remote(database, monkeypatch):
    monkeypatch.setattr(bridge, "get_session_factory", lambda: database)
    monkeypatch.setenv("MODSTORE_STRATEGIC_REPORTS_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_PUBLIC_ORIGIN", "https://xiu-ci.com")
    monkeypatch.setenv(
        "MODSTORE_PARA_DISPATCH_TOKEN_SHA256",
        hashlib.sha256(TOKEN.encode()).hexdigest(),
    )
    monkeypatch.setattr(llm_key_resolver, "platform_api_key", lambda _provider: "platform-test-key")
    monkeypatch.setattr(llm_key_resolver, "platform_base_url", lambda _provider: None)
    github = GitHub()
    monkeypatch.setattr(customer_ticket_github, "github", github)
    row = strategic_tests.opportunity(
        tokens=200000,
        compute_seconds=300,
        input_data={
            "business_notes": "Support cases decreased from 10 to 8.",
            "remote_execution": {
                "kind": bridge.KIND,
                "repository": REPO,
                "source_sha": SOURCE,
                "provider": "openai",
                "model": "approved-model",
            },
        },
    )
    caps = strategic_tests.limits(
        tokens=300000,
        tariffs=[
            {
                "provider": "openai",
                "model": "approved-model",
                "input_cents_per_million": 100,
                "output_cents_per_million": 100,
                "source": "approved-native-price",
            }
        ],
    )
    decision_id = strategic_tests.proposal(database, rows=[row], caps=caps)
    outcome = runtime.run_portfolio_cycle(decision_id, owner_user_id=7)
    saved = outcome["tasks"]["a"]
    assert saved["status"] == "waiting"
    request_id = saved["worker_binding"]["receipt_id"]
    app = FastAPI()
    app.include_router(router)

    def session():
        with database() as db:
            yield db

    app.dependency_overrides[get_db] = session
    with TestClient(app) as client:
        state = SimpleNamespace(
            app=app,
            client=client,
            github=github,
            factory=database,
            decision_id=decision_id,
            request_id=request_id,
            management={"Authorization": "Bearer " + TOKEN},
        )
        state.control = f"/api/service/mac-control/strategic-runs/{request_id}"
        state.identity = {
            "run_id": 42,
            "run_attempt": 1,
            "repository": REPO,
            "source_sha": SOURCE,
        }
        state.task = {**row, "lease_token": saved["lease_token"]}
        yield state


def claim(remote):
    response = remote.client.post(
        remote.control + "/claim", json=remote.identity, headers=remote.management
    )
    assert response.status_code == 200, response.text
    grant = response.json()
    remote.grant = grant
    remote.model_headers = {"Authorization": "Bearer " + grant["model_token"]}
    return grant


def notify(remote, report="Support cases decreased from 10 to 8."):
    receipt = {
        key: remote.grant[key]
        for key in (
            "schema",
            "kind",
            "request_id",
            "binding_id",
            "owner_user_id",
            "run_id",
            "run_attempt",
            "repository",
            "source_sha",
        )
    }
    receipt.update(status="completed", report_sha256=hashlib.sha256(report.encode()).hexdigest())
    response = remote.client.post(
        remote.control + "/result", json=receipt, headers=remote.management
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending_artifact_readback"
    return receipt


def download_transport(remote, monkeypatch):
    client_type = httpx.Client
    seen = []

    def respond(request):
        seen.append(request)
        if request.url.host == "api.github.com":
            return httpx.Response(
                302,
                headers={"location": "https://report.blob.core.windows.net/artifact"},
            )
        assert request.url.host == "report.blob.core.windows.net"
        assert "authorization" not in request.headers
        return httpx.Response(200, content=remote.github.archive)

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs),
    )
    return seen


@pytest.mark.parametrize("stream", [False, True])
def test_real_gateway_sdk_ledger_and_immutable_report_finish_original_task(
    remote, monkeypatch, stream
):
    grant = claim(remote)
    assert grant["gateway_url"].endswith(remote.request_id + "/v1")
    seen = _http(monkeypatch, (remote.decision_id, remote.task, remote.factory))
    response = remote.client.post(
        remote.control + "/v1/responses",
        json=_payload(stream=stream),
        headers=remote.model_headers,
    )
    assert response.status_code == 200, response.text
    assert "resp-orders" in response.text
    saved = p.portfolio_status(remote.decision_id)["tasks"]["a"]
    assert saved["status"] == "running"
    assert [
        (call["status"], call["actual_tokens"], call["response_id"])
        for call in saved["calls"].values()
    ] == [("settled", 13, "resp-orders")]
    receipt = notify(remote)
    # The controller acknowledgement alone never completes an approved task.
    assert p.portfolio_status(remote.decision_id)["tasks"]["a"]["status"] == "running"
    remote.github.publish(receipt)
    reads = download_transport(remote, monkeypatch)
    result = runtime.run_portfolio_cycle(remote.decision_id, owner_user_id=7)
    completed = result["tasks"]["a"]
    assert completed["status"] == "completed"
    assert completed["actual_tokens"] == 13
    assert completed["execution_receipt"]["artifact_sha256"] == receipt["report_sha256"]
    assert (
        completed["execution_receipt"]["remote_receipt"]["archive_digest"]
        == remote.github.artifact["digest"]
    )
    assert bridge.worker_status(remote.request_id)["finished"] is True
    assert len(remote.github.writes) == 1 and len(reads) == 2
    assert all(client.is_closed() for client in seen["clients"])
    assert usage._SCOPE.get() is None
    remote.github.artifact = None
    runtime.run_portfolio_cycle(remote.decision_id, owner_user_id=7)
    assert len(reads) == 2 and len(remote.github.writes) == 1
    assert (
        p.portfolio_status(remote.decision_id)["tasks"]["a"]["execution_receipt"]
        == completed["execution_receipt"]
    )


def test_pending_original_request_is_not_dispatched_or_claimed_twice(remote):
    runtime.run_portfolio_cycle(remote.decision_id, owner_user_id=7)
    assert len(remote.github.writes) == 1
    claim(remote)
    duplicate = remote.client.post(
        remote.control + "/claim", json=remote.identity, headers=remote.management
    )
    assert duplicate.status_code == 409
    runtime.run_portfolio_cycle(remote.decision_id, owner_user_id=7)
    assert len(remote.github.writes) == 1


@pytest.mark.parametrize("stopped", [False, True])
def test_unknown_provider_usage_keeps_hold_and_business_receipt_cannot_release_it(
    remote, monkeypatch, stopped
):
    claim(remote)
    _http(monkeypatch, (remote.decision_id, remote.task, remote.factory), meter="absent")
    response = remote.client.post(
        remote.control + "/v1/responses", json=_payload(), headers=remote.model_headers
    )
    assert response.status_code == 200
    state = p.portfolio_status(remote.decision_id)
    call = next(iter(state["tasks"]["a"]["calls"].values()))
    assert state["halted"] and call["status"] == "unknown" and "actual_tokens" not in call
    receipt = notify(remote)
    if stopped:
        p.stop_portfolio(
            remote.decision_id,
            owner_user_id=7,
            actor="admin:7",
            reason="approved operation stopped",
        )
    remote.github.publish(receipt)
    download_transport(remote, monkeypatch)
    assert receipts.reconcile_request(remote.request_id)
    result = p.portfolio_status(remote.decision_id)
    final_call = next(iter(result["tasks"]["a"]["calls"].values()))
    assert result["halted"] and result["tasks"]["a"]["status"] == "unknown"
    assert final_call == call
    assert result["tasks"]["a"]["actual_tokens"] == call["reserved_tokens"]
    if stopped:
        assert result["stop_reason"] == "approved operation stopped"


def test_stop_rejects_further_model_calls_without_releasing_original_holds(remote, monkeypatch):
    claim(remote)
    p.stop_portfolio(
        remote.decision_id,
        owner_user_id=7,
        actor="admin:7",
        reason="ordinary operation stopped",
    )
    response = remote.client.post(
        remote.control + "/v1/responses", json=_payload(), headers=remote.model_headers
    )
    assert response.status_code == 409
    assert p.portfolio_status(remote.decision_id)["tasks"]["a"]["calls"] == {}
    assert len(remote.github.writes) == 1


def test_stream_stop_keeps_internal_error_private_and_preserves_unknown_hold(remote, monkeypatch):
    claim(remote)
    seen = _http(monkeypatch, (remote.decision_id, remote.task, remote.factory))
    authenticate = bridge.authenticate_model
    checks = []
    private_detail = "controlled-private-sentinel: /operator/private/config; credential-example"
    reservation = {}

    def authenticate_until_stopped(request_id, token):
        binding = authenticate(request_id, token)
        checks.append(request_id)
        if len(checks) == 2:
            saved = p.portfolio_status(remote.decision_id)["tasks"]["a"]
            reservation.update(next(iter(saved["calls"].values())))
            # Inject only at the internal error boundary, after a real admitted
            # SDK call. This does not claim a provider credential leaked in use.
            raise p.PortfolioError(private_detail)
        return binding

    monkeypatch.setattr(bridge, "authenticate_model", authenticate_until_stopped)
    response = remote.client.post(
        remote.control + "/v1/responses",
        json=_payload(stream=True),
        headers=remote.model_headers,
    )
    assert response.status_code == 200, response.text
    assert private_detail not in response.text
    events = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    assert [event["type"] for event in events] == ["response.created", "error"]
    assert events[-1] == {
        "type": "error",
        "code": "strategic_budget_stopped",
        "message": "Model stream stopped because authorization or budget is no longer available.",
    }
    assert len(checks) == 2 and len(seen["requests"]) == 1
    assert all(client.is_closed() for client in seen["clients"])
    assert all(upstream.is_closed for upstream in seen["responses"])
    state = p.portfolio_status(remote.decision_id)
    call = next(iter(state["tasks"]["a"]["calls"].values()))
    assert state["halted"] and call["status"] == "unknown"
    assert "actual_tokens" not in call and "accrued_cost_cents" not in call
    assert call["reserved_tokens"] == reservation["reserved_tokens"] > 0
    assert call["reserved_cost_cents"] == reservation["reserved_cost_cents"] > 0
    assert usage._SCOPE.get() is None and len(remote.github.writes) == 1


def test_only_same_native_artifact_can_finish_original_report(remote, monkeypatch):
    claim(remote)
    _http(monkeypatch, (remote.decision_id, remote.task, remote.factory))
    assert (
        remote.client.post(
            remote.control + "/v1/responses",
            json=_payload(),
            headers=remote.model_headers,
        ).status_code
        == 200
    )
    receipt = notify(remote)
    remote.github.publish(receipt, report="A different ordinary report")
    download_transport(remote, monkeypatch)
    with pytest.raises(p.PortfolioError, match="differs from"):
        receipts.reconcile_request(remote.request_id)
    assert p.portfolio_status(remote.decision_id)["tasks"]["a"]["status"] == "running"
    remote.github.publish(receipt)
    assert receipts.reconcile_request(remote.request_id)
    assert p.portfolio_status(remote.decision_id)["tasks"]["a"]["status"] == "completed"


@pytest.mark.asyncio
async def test_disconnect_before_first_downstream_chunk_closes_open_sdk_stream(remote, monkeypatch):
    from starlette.requests import ClientDisconnect, Request

    from modstore_server.strategic_remote_api import responses

    claim(remote)
    seen = _http(monkeypatch, (remote.decision_id, remote.task, remote.factory), pause=True)
    body = json.dumps(_payload(stream=True)).encode()

    async def receive():
        return {"type": "http.request", "body": body}

    scope = {
        "type": "http",
        "method": "POST",
        "path": remote.control + "/v1/responses",
        "headers": [],
        "asgi": {"spec_version": "2.4"},
    }
    response = await responses(
        remote.request_id,
        Request(scope, receive),
        remote.model_headers["Authorization"],
    )

    async def disconnected(_message):
        raise OSError("ordinary client disconnected before response headers")

    with pytest.raises(ClientDisconnect):
        await response(scope, receive, disconnected)
    assert all(client.is_closed() for client in seen["clients"])
    state = p.portfolio_status(remote.decision_id)
    call = next(iter(state["tasks"]["a"]["calls"].values()))
    assert state["halted"] and call["status"] == "unknown"
    assert "actual_tokens" not in call and call["reserved_tokens"] > 0


def test_stopped_portfolio_readback_retains_cost_and_stop_without_new_dispatch(remote, monkeypatch):
    from modstore_server import strategic_portfolio_scheduler as scheduler

    monkeypatch.setattr(scheduler, "get_session_factory", lambda: remote.factory)
    claim(remote)
    _http(monkeypatch, (remote.decision_id, remote.task, remote.factory))
    assert (
        remote.client.post(
            remote.control + "/v1/responses",
            json=_payload(),
            headers=remote.model_headers,
        ).status_code
        == 200
    )
    receipt = notify(remote)
    p.stop_portfolio(
        remote.decision_id,
        owner_user_id=7,
        actor="admin:7",
        reason="approved operation stopped",
    )
    remote.github.publish(receipt)
    reads = download_transport(remote, monkeypatch)
    assert scheduler.tick()["selected"] == 0
    stopped = p.portfolio_status(remote.decision_id)
    assert stopped["halted"] and stopped["stop_reason"] == "approved operation stopped"
    assert stopped["tasks"]["a"]["status"] == "completed"
    assert stopped["tasks"]["a"]["actual_tokens"] == 13
    assert len(remote.github.writes) == 1
    assert receipts.reconcile_pending_reports()["checked"] == 0
    assert len(reads) == 2


def test_execution_deadline_rejects_new_call_and_native_failure_is_terminal(remote, monkeypatch):
    claim(remote)

    def expire(_row, _proposal, state, _session):
        state["tasks"]["a"]["deadline"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()

    p.mutate_portfolio(remote.decision_id, expire)
    response = remote.client.post(
        remote.control + "/v1/responses", json=_payload(), headers=remote.model_headers
    )
    assert response.status_code == 409
    assert p.portfolio_status(remote.decision_id)["tasks"]["a"]["calls"] == {}
    remote.github.run_state, remote.github.conclusion = "completed", "failure"
    assert receipts.reconcile_request(remote.request_id)
    assert p.portfolio_status(remote.decision_id)["tasks"]["a"]["status"] == "failed"
    assert receipts.reconcile_request(remote.request_id) is False
    assert len(remote.github.writes) == 1


def test_public_origin_is_shared_with_configured_staging(monkeypatch):
    monkeypatch.setenv("MODSTORE_PUBLIC_ORIGIN", "https://staging.xiu-ci.com")
    assert (
        bridge.public_base() == "https://staging.xiu-ci.com/api/service/mac-control/strategic-runs"
    )
