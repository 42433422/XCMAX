"""Original approved engineering work orders consume the shared SQL budget."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modstore_server import customer_ticket_github, llm_key_resolver
from modstore_server import retort_github_workspace as original
from modstore_server import strategic_portfolio as p
from modstore_server import strategic_portfolio_runtime as runtime
from modstore_server import strategic_remote_bridge as remote
from modstore_server import strategic_workspace_bridge as bridge
from modstore_server import strategic_workspace_receipts as receipts
from modstore_server.api.deps import get_db
from modstore_server.integrations.repository_packages import load_repository_module
from modstore_server.mac_control_dispatch_api import router
from modstore_server.models import IncidentEvent, RetortEvolutionRun
from modstore_server.para_execution_isolation import HEADER_ONLY_PLATFORM_PROFILE
from modstore_server.retort_feedback_recovery import _immutable_recovery
from tests import test_strategic_company_resources as company_tests
from tests import test_strategic_portfolio as strategic_tests
from tests.test_strategic_remote_bridge import REPO, SOURCE, TOKEN, GitHub
from tests.test_strategic_responses import _http

database = company_tests.database
configured = company_tests.configured
ATTEMPT = "b" * 32


class WorkspaceGitHub(GitHub):
    def __init__(self):
        super().__init__()
        self.jobs = []
        self.phase("execute")

    def phase(self, phase):
        now = datetime.now(UTC)
        names = (
            ["employee-workspace"]
            if phase == "execute"
            else ["employee-workspace", "publish-candidate", "resume-verification"]
        )
        if phase == "completed":
            names.append("independent-verification")
        self.jobs = [
            {
                "id": 100 + index,
                "run_id": 42,
                "run_attempt": 1,
                "name": name,
                "head_sha": SOURCE,
                "head_branch": "main",
                "status": (
                    "in_progress"
                    if index == len(names) - 1 and phase != "completed"
                    else "completed"
                ),
                "conclusion": (
                    None if index == len(names) - 1 and phase != "completed" else "success"
                ),
                "started_at": (now - timedelta(seconds=12 - 2 * index)).isoformat(),
                "completed_at": (now - timedelta(seconds=11 - 2 * index)).isoformat(),
            }
            for index, name in enumerate(names)
        ]
        if phase == "completed":
            self.run_state, self.conclusion = "completed", "success"

    def __call__(self, method, path, body=None):
        if path.endswith("/jobs?per_page=100"):
            return {"total_count": len(self.jobs), "jobs": deepcopy(self.jobs)}
        return super().__call__(method, path, body)


@pytest.fixture
def workspace(configured, monkeypatch):
    monkeypatch.setattr(remote, "get_session_factory", lambda: configured)
    monkeypatch.setattr(original, "get_session_factory", lambda: configured)
    monkeypatch.setenv("MODSTORE_STRATEGIC_WORKSPACES_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_PUBLIC_ORIGIN", "https://xiu-ci.com")
    monkeypatch.setenv("DEVFLEET_FORCE_OPENCODE", "1")
    monkeypatch.setenv("MODSTORE_PARA_PLATFORM_POOL", "1")
    monkeypatch.setenv("MODSTORE_PARA_GITHUB_DEVICE_ID", "cloud")
    monkeypatch.setenv("MODSTORE_PARA_GITHUB_API_BASE", "https://para.example.test")
    monkeypatch.setenv("MODSTORE_PARA_GITHUB_AUTH_TOKEN", "fixture-para-control-token")
    monkeypatch.setenv(
        "MODSTORE_PARA_DISPATCH_TOKEN_SHA256", hashlib.sha256(TOKEN.encode()).hexdigest()
    )
    monkeypatch.setattr(llm_key_resolver, "platform_api_key", lambda _provider: "platform-test-key")
    monkeypatch.setattr(llm_key_resolver, "platform_base_url", lambda _provider: None)
    github = WorkspaceGitHub()
    monkeypatch.setattr(customer_ticket_github, "github", github)
    monkeypatch.setattr(original, "github", github)
    request_id = str(uuid4())
    contract = load_repository_module("retort_engine.evolution_contract")
    protocol = {
        "request_id": request_id,
        "repository": REPO,
        "source_sha": SOURCE,
        "title": "Approved repair",
        "goal": "Repair an ordinary report export",
        "criteria": [
            {"id": "export", "domain_id": "shared-engine", "requirement": "Retain report output"}
        ],
    }
    protocol["protocol_digest"] = contract.digest(protocol)
    recovery_policy = {
        "mode": "restore_previous_release",
        "target": {
            "git_sha": SOURCE,
            "artifact_sha256": "a" * 64,
            "image_digest": "",
            "product_version": "1.0.0",
            "release_id": f"xcagi-1.0.0-{SOURCE}",
        },
    }
    plan = {
        "public_title": "Approved repair",
        "public_body": "Repair an ordinary report export",
        "feedback_policy": {"recovery": recovery_policy},
    }
    optimization = {"status": "awaiting_measured_baseline"}
    approval = {
        "approved": True,
        "actor_id": 7,
        "digest": contract.digest(
            {"protocol": protocol, "plan": plan, "optimization": optimization}
        ),
    }
    effects = {
        "authorization": approval,
        "plan": plan,
        "optimization": optimization,
        "issue_number": 123,
        "customer_feedback": {"ticket_ids": [1], "recovery": recovery_policy},
    }
    with configured() as session:
        session.add(
            RetortEvolutionRun(
                id=request_id,
                user_id=7,
                status="waiting_execution",
                protocol_json=json.dumps(protocol),
                effects_json=json.dumps(effects),
            )
        )
        session.commit()
    tariffs = [
        {
            "provider": "openai",
            "model": "approved-model",
            "input_cents_per_million": 100,
            "output_cents_per_million": 100,
            "source": "approved-native-price",
        }
    ]
    company_id = company_tests.budget(
        configured, tokens=600000, compute_seconds=1000, tariffs=tariffs
    )
    row = strategic_tests.opportunity(
        tokens=200000,
        compute_seconds=300,
        input_data={
            "remote_execution": {
                "kind": bridge.KIND,
                "original_request_id": request_id,
                "protocol_digest": protocol["protocol_digest"],
                "approval_digest": approval["digest"],
                "repository": REPO,
                "source_sha": SOURCE,
                "provider": "openai",
                "model": "approved-model",
            }
        },
    )
    caps = strategic_tests.limits(tokens=300000, tariffs=tariffs)
    state = SimpleNamespace(
        factory=configured,
        github=github,
        request_id=request_id,
        protocol=protocol,
        effects=effects,
        opportunity=row,
        caps=caps,
        company_id=company_id,
        contract=contract,
        tasks={},
        phase="execute",
    )
    state.allocation = {
        "status": "admitted",
        "model": "approved-model",
        "provider": "openai",
        "approved_models": ["approved-model"],
        "execution_isolation": HEADER_ONLY_PLATFORM_PROFILE,
    }
    monkeypatch.setattr(
        "modstore_server.para_model_admission.platform_model_admission",
        lambda _profile: state.allocation,
    )
    state.dispatched = []
    monkeypatch.setattr(
        "modstore_server.incident_team_dispatch.dispatch_incident_team", state.dispatched.append
    )

    def devices():
        return [
            {
                "id": "cloud",
                "status": "online",
                "lastSeen": datetime.now(UTC).isoformat(),
                "capabilities": {
                    "github_actions": True,
                    "github_request_id": request_id,
                    "github_run_id": "42",
                    "github_run_attempt": "1",
                    "github_stage": state.phase,
                },
                "tools": [{"toolName": "opencode", "status": "idle"}],
            }
        ]

    state.devices = devices

    def collect():
        client = httpx.Client
        with monkeypatch.context() as patch:
            patch.setattr(
                original.httpx,
                "Client",
                lambda **kwargs: client(
                    transport=httpx.MockTransport(
                        lambda _request: httpx.Response(200, json={"devices": devices()})
                    ),
                    **kwargs,
                ),
            )
            return original.collect_execution(request_id)

    state.collect = collect
    monkeypatch.setattr(
        "modstore_server.mac_control_transport.ParaClient",
        lambda **_kwargs: SimpleNamespace(
            task=lambda task_id: deepcopy(state.tasks[task_id]), devices=devices, close=lambda: None
        ),
    )
    app = FastAPI()
    app.include_router(router)

    def session():
        with configured() as db:
            yield db

    app.dependency_overrides[get_db] = session
    state.app = app
    state.management = {"Authorization": "Bearer " + TOKEN}
    state.control = f"/api/service/mac-control/strategic-runs/{request_id}"
    with TestClient(app) as client:
        state.client = client
        yield state


def attach(workspace):
    workspace.decision_id = strategic_tests.proposal(
        workspace.factory, rows=[workspace.opportunity], caps=workspace.caps
    )
    status = runtime.run_portfolio_cycle(workspace.decision_id, owner_user_id=7)
    saved = status["tasks"]["a"]
    assert saved["status"] == "waiting", saved
    assert saved["worker_binding"]["receipt_id"] == workspace.request_id
    return status


def bootstrap(workspace, phase="execute"):
    workspace.phase = phase
    identity = {
        "run_id": 42,
        "run_attempt": 1,
        "repository": REPO,
        "source_sha": SOURCE,
        "phase": phase,
        "execution_isolation": HEADER_ONLY_PLATFORM_PROFILE,
    }
    response = workspace.client.post(
        workspace.control + "/claim", json=identity, headers=workspace.management
    )
    assert response.status_code == 200, response.text
    workspace.bootstrap = response.json()
    workspace.bootstrap_headers = {
        "Authorization": "Bearer " + workspace.bootstrap["bootstrap_token"]
    }
    return response.json()


def task(workspace, *, role="fix", attempt=ATTEMPT):
    task_id, subtask_id = f"task-{role}", f"sub-{role}"
    title = (
        f"[xcmax:{hashlib.sha256(workspace.request_id.encode()).hexdigest()[:32]}:{attempt}] {role}"
    )
    value = {
        "id": task_id,
        "status": "running",
        "title": title,
        "description": "Repair the approved ordinary report export.",
        "repo_url": f"https://github.com/{REPO}.git",
        "branch": "c" * 40 if role == "verify" else SOURCE,
        "auto_merge": False,
        "subTasks": [
            {
                "id": subtask_id,
                "device_id": "cloud",
                "tool_name": "opencode",
                "status": "running",
                "branch_name": f"devfleet/opencode/{subtask_id}",
            }
        ],
    }
    workspace.tasks[task_id] = value
    with workspace.factory() as session:
        original_row = session.get(RetortEvolutionRun, workspace.request_id)
        event = session.get(IncidentEvent, original_row.event_id)
        payload = json.loads(event.payload_json)
        previous = payload.get("_team_claim", {}).get("team", [])
        if role == "verify":
            for member in previous:
                if member["role"] == "fix":
                    member.update(ok=True, status="completed")
                    member["handler_outputs"]["outputs"][0]["commit_sha"] = "c" * 40
        payload["_team_claim"] = {
            "team": [
                {
                    "employee_id": "approved-maintainer",
                    "role": role,
                    "status": "dispatched",
                    "attempt_id": attempt,
                    "handler_outputs": {
                        "outputs": [
                            {
                                "handler": "para_delegate",
                                "accepted": True,
                                "executor": "github_actions",
                                "task_id": task_id,
                                "required_subtask_ids": [subtask_id],
                                "planned_devices": ["cloud"],
                            }
                        ]
                    },
                }
            ]
        }
        payload["_team_claim"]["team"].extend(
            member for member in previous if member["role"] != role
        )
        event.payload_json = json.dumps(payload)
        session.commit()
    return {
        "phase": workspace.phase,
        "run_id": 42,
        "task_id": task_id,
        "subtask_id": subtask_id,
        "attempt_id": attempt,
        "device_id": "cloud",
        "title": title,
        "description": value["description"],
        "repo_url": value["repo_url"],
        "base_branch": value["branch"],
        "work_branch": value["subTasks"][0]["branch_name"],
        "auto_merge": False,
    }


def grant(workspace, identity):
    response = workspace.client.post(
        workspace.control + "/task-grant", json=identity, headers=workspace.bootstrap_headers
    )
    assert response.status_code == 200, response.text
    result = response.json()
    workspace.model_headers = {"Authorization": "Bearer " + result["model_token"]}
    workspace.grant = result
    return result


def model(workspace, monkeypatch, *, usage=True):
    saved = p.portfolio_status(workspace.decision_id)["tasks"]["a"]
    _http(monkeypatch, (workspace.decision_id, saved), meter="reported" if usage else "absent")
    response = workspace.client.post(
        workspace.control + "/v1/responses",
        headers=workspace.model_headers,
        json={
            "model": "approved-model",
            "input": "ordinary repair",
            "store": False,
            "max_output_tokens": 16,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def start(workspace):
    attach(workspace)
    assert workspace.collect()["status"] == "waiting"
    assert workspace.dispatched
    bootstrap(workspace)
    return grant(workspace, task(workspace))


def test_original_feedback_reaches_original_device_and_event_only_after_company_binding(workspace):
    before = workspace.collect()
    assert before["reason"] == "strategic_company_budget_binding_required"
    assert not workspace.github.writes and not workspace.dispatched
    attach(workspace)
    outcome = workspace.collect()
    assert outcome["event_id"] == workspace.dispatched[0]
    assert len(workspace.github.writes) == 1
    assert workspace.collect()["event_id"] == outcome["event_id"]
    assert len(workspace.github.writes) == 1
    bootstrap(workspace)
    response = workspace.client.post(
        workspace.control + "/v1/responses",
        headers=workspace.bootstrap_headers,
        json={"model": "approved-model", "input": "not bound", "store": False},
    )
    assert response.status_code == 409
    assert not p.portfolio_status(workspace.decision_id)["tasks"]["a"]["calls"]


def test_original_task_raw_sdk_usage_and_candidate_are_bound_to_the_same_grant(
    workspace, monkeypatch
):
    bound = start(workspace)
    candidate = {key: bound[key] for key in ("task_id", "subtask_id", "attempt_id")}
    assert not bridge.candidate_metered(workspace.request_id, candidate)
    model(workspace, monkeypatch)
    saved = p.portfolio_status(workspace.decision_id)["tasks"]["a"]
    call = next(iter(saved["calls"].values()))
    assert call["status"] == "settled"
    assert call["caller_binding"]["grant_id"] == bound["grant_id"]
    assert call["caller_binding"]["event_id"] == bound["event_id"]
    assert call["caller_binding_sha256"] == p.digest(call["caller_binding"])
    assert bridge.candidate_metered(workspace.request_id, candidate)
    assert not bridge.candidate_metered(
        workspace.request_id, {**candidate, "task_id": "another-task"}
    )
    assert not receipts.reconcile_request(workspace.request_id)
    assert p.portfolio_status(workspace.decision_id)["tasks"]["a"]["status"] == "running"


@pytest.mark.parametrize(
    "field,value",
    [
        ("attempt_id", "e" * 32),
        ("subtask_id", "other"),
        ("description", "changed input"),
        ("device_id", "other"),
    ],
)
def test_task_binding_requires_the_original_native_receipt(workspace, field, value):
    attach(workspace)
    workspace.collect()
    bootstrap(workspace)
    identity = task(workspace)
    response = workspace.client.post(
        workspace.control + "/task-grant",
        json={**identity, field: value},
        headers=workspace.bootstrap_headers,
    )
    assert response.status_code == 409
    assert not p.portfolio_status(workspace.decision_id)["tasks"]["a"]["calls"]


def test_execute_and_resume_revoke_old_grants_and_use_remaining_native_compute(
    workspace, monkeypatch
):
    old = start(workspace)
    model(workspace, monkeypatch)
    old_headers = dict(workspace.model_headers)
    rejected = workspace.client.post(
        workspace.control + "/claim",
        headers=workspace.management,
        json={
            key: value
            for key, value in {**workspace.bootstrap, "phase": "resume"}.items()
            if key
            in {"run_id", "run_attempt", "repository", "source_sha", "phase", "execution_isolation"}
        },
    )
    assert rejected.status_code == 409
    workspace.github.phase("resume")
    assert receipts.reconcile_request(workspace.request_id)
    saved = p.portfolio_status(workspace.decision_id)["tasks"]["a"]
    assert saved["status"] == "waiting" and saved["worker_capacity"]["state"] == "idle"
    assert company_tests.totals(workspace.company_id)["slots"] == 0
    assert company_tests.totals(workspace.company_id)["held"]["tokens"] > 0
    before = saved["compute_seconds"]
    bootstrap(workspace, "resume")
    saved = p.portfolio_status(workspace.decision_id)["tasks"]["a"]
    assert saved["compute_seconds"] >= before
    assert company_tests.totals(workspace.company_id)["slots"] == 1
    assert (
        workspace.client.get(workspace.control + "/v1/models", headers=old_headers).status_code
        == 409
    )
    newer = grant(workspace, task(workspace, role="verify", attempt="c" * 32))
    assert newer["grant_id"] != old["grant_id"] and newer["phase"] == "resume"
    assert p._date(newer["deadline"]) < p._date(
        remote.read_request(workspace.request_id)[0]["deadline"]
    )


def test_unknown_provider_usage_never_unlocks_a_new_phase_or_candidate(workspace, monkeypatch):
    bound = start(workspace)
    model(workspace, monkeypatch, usage=False)
    workspace.github.phase("resume")
    assert not receipts.reconcile_request(workspace.request_id)
    assert company_tests.totals(workspace.company_id)["slots"] == 1
    assert not bridge.candidate_metered(workspace.request_id, bound)
    identity = {
        key: workspace.bootstrap[key]
        for key in ("run_id", "run_attempt", "repository", "source_sha", "execution_isolation")
    }
    response = workspace.client.post(
        workspace.control + "/claim",
        headers=workspace.management,
        json={**identity, "phase": "resume"},
    )
    assert response.status_code == 409
    call = next(iter(p.portfolio_status(workspace.decision_id)["tasks"]["a"]["calls"].values()))
    assert call["status"] == "unknown" and call["reserved_tokens"] > 0


def original_terminal(workspace, *, status="completed"):
    with workspace.factory() as session:
        row = session.get(RetortEvolutionRun, workspace.request_id)
        effects = json.loads(row.effects_json)
        verification = {
            "status": "checks_passed",
            "request_id": workspace.request_id,
            "protocol_digest": workspace.protocol["protocol_digest"],
            "run_id": "42",
            "target_sha": "c" * 40,
            "artifact_id": 901,
            "artifact_digest": "sha256:" + "d" * 64,
            "evidence_archive": "retort-evidence/retained-native-benchmark.json",
        }
        delivery = {
            "status": "deployment_verified",
            "candidate_sha": "c" * 40,
            "release_sha": "e" * 40,
            "identity": {"git_sha": "e" * 40, "artifact_sha256": "f" * 64},
            "receipt": {
                "workflow_run_id": "90",
                "environment": "production",
                "approval_reference": "approved-release",
                "signature_verified": True,
            },
        }
        state = {
            "status": status,
            "verification": verification,
            "delivery": delivery,
            "approval": {
                "approved": True,
                "actor_id": 7,
                "digest": workspace.contract.digest(verification),
            },
            "has_customer_feedback": True,
            "impact": {"status": "customer_impact_verified"},
        }
        effects["verification"] = verification
        row.effects_json, row.snapshot_json, row.status = (
            json.dumps(effects),
            json.dumps(state),
            status,
        )
        session.commit()
    return state


def test_only_original_benchmark_acceptance_deployment_and_impact_finish_the_portfolio(
    workspace, monkeypatch
):
    start(workspace)
    model(workspace, monkeypatch)
    workspace.github.phase("completed")
    for stage in (
        "waiting_execution",
        "awaiting_acceptance",
        "waiting_delivery",
        "waiting_customer_impact",
    ):
        original_terminal(workspace, status=stage)
        receipts.reconcile_request(workspace.request_id)
        assert p.portfolio_status(workspace.decision_id)["tasks"]["a"]["status"] == "waiting"
    original_terminal(workspace)
    assert receipts.reconcile_request(workspace.request_id)
    saved = p.portfolio_status(workspace.decision_id)["tasks"]["a"]
    assert saved["status"] == "completed"
    assert saved["execution_receipt"]["artifact_sha256"] == "f" * 64
    assert saved["compute_seconds"] < 30  # Four native jobs, no release-wait wall clock.
    assert company_tests.totals(workspace.company_id)["slots"] == 0
    before = deepcopy(saved)
    original_terminal(workspace, status="waiting_recovery")
    assert not receipts.reconcile_request(workspace.request_id)
    assert p.portfolio_status(workspace.decision_id)["tasks"]["a"] == before


def test_original_recovery_stays_pending_until_its_rollback_receipt(workspace, monkeypatch):
    start(workspace)
    model(workspace, monkeypatch)
    workspace.github.phase("completed")
    original_terminal(workspace, status="customer_impact_rejected")
    receipts.reconcile_request(workspace.request_id)
    assert p.portfolio_status(workspace.decision_id)["tasks"]["a"]["status"] == "waiting"
    with workspace.factory() as session:
        row = session.get(RetortEvolutionRun, workspace.request_id)
        state = json.loads(row.snapshot_json)
        effects = json.loads(row.effects_json)
        state["impact"] = {
            "status": "customer_impact_rejected",
            "reason": "experiment_regression",
        }
        delivery = state["delivery"]
        delivery["identity"].update(
            image_digest="",
            product_version="1.1.0",
            release_id=f"xcagi-1.1.0-{delivery['release_sha']}",
        )
        rollback_request_id = f"retort:{row.id}:rollback"
        state["recovery"] = effects["recovery"] = {
            "status": "rollback_verified",
            "receipt": {"request_id": rollback_request_id},
        }
        row.snapshot_json = json.dumps(state)
        row.effects_json = json.dumps(effects)
        session.commit()
    assert not receipts.reconcile_request(workspace.request_id)
    assert p.portfolio_status(workspace.decision_id)["tasks"]["a"]["status"] == "waiting"

    target = effects["customer_feedback"]["recovery"]["target"]
    reader = _immutable_recovery()
    payload = reader.request_payload(
        {
            "request_id": rollback_request_id,
            "expected_identity": delivery["identity"],
            "target_identity": target,
            "reason": state["impact"]["reason"],
        }
    )
    recovery = {
        "status": "rollback_verified",
        "request_id": workspace.request_id,
        "identity": target,
        "receipt": {
            **payload,
            "status": "rollback_verified",
            "identity": target,
            "request_sha256": reader._request_digest(payload),
        },
        "verified_at": datetime.now(UTC).isoformat(),
    }
    with workspace.factory() as session:
        row = session.get(RetortEvolutionRun, workspace.request_id)
        state["recovery"] = effects["recovery"] = recovery
        row.snapshot_json = json.dumps(state)
        row.effects_json = json.dumps(effects)
        session.commit()
    assert receipts.reconcile_request(workspace.request_id)
    saved = p.portfolio_status(workspace.decision_id)["tasks"]["a"]
    assert saved["status"] == "failed"
    assert remote.read_request(workspace.request_id)[2] == "failed"
    assert saved["execution_receipt"]["remote_receipt"]["recovery"] == recovery


def test_changed_original_approval_revokes_the_task_before_another_model_call(
    workspace, monkeypatch
):
    start(workspace)
    with workspace.factory() as session:
        row = session.get(RetortEvolutionRun, workspace.request_id)
        effects = json.loads(row.effects_json)
        effects["plan"]["public_body"] = "a different operation"
        row.effects_json = json.dumps(effects)
        session.commit()
    response = workspace.client.get(
        workspace.control + "/v1/models", headers=workspace.model_headers
    )
    assert response.status_code == 409
    assert not p.portfolio_status(workspace.decision_id)["tasks"]["a"]["calls"]
