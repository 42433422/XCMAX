"""Persisted component integration with isolated HTTP/executor boundaries."""

import json
import os
from uuid import uuid4

import pytest
from fastapi import HTTPException

from modstore_server import retort_evolution as service
from modstore_server import retort_github_workspace as workspace
from modstore_server.api.deps import require_admin
from modstore_server.app import app
from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.models import IncidentEvent, RetortEvolutionRun, User, get_session_factory


@pytest.fixture
def setup(client, tmp_path, monkeypatch):
    monkeypatch.setenv(
        "MODSTORE_RETORT_CHECKPOINT_DSN", "sqlite:///" + str(tmp_path / "flow.sqlite")
    )
    monkeypatch.setenv("MODSTORE_GITHUB_REPOSITORY", "example/product")
    monkeypatch.delenv("MODSTORE_RETORT_RSI_PROTOCOL", raising=False)
    template = {
        "name": "恢复协议",
        "criterion_ids": ["shared-engine-B2"],
        "container_image": "example/test@sha256:" + "c" * 64,
        "checks": [
            {
                "id": "restore",
                "criterion_ids": ["shared-engine-B2"],
                "files": {"check.py": "b" * 64},
                "argv": ["python", "check.py"],
                "timeout_seconds": 10,
            }
        ],
    }
    templates = tmp_path / "protocols.json"
    templates.write_text(json.dumps({"restore": template}))
    monkeypatch.setenv("MODSTORE_RETORT_PROTOCOLS", str(templates))
    calls = []

    def github(method, path, body=None):
        calls.append((method, path, body))
        if path.endswith("/commits/main"):
            return {"sha": "a" * 40}
        if method == "POST" and path.endswith("/issues"):
            return {"number": 123}
        if "/issues?" in path:
            return []
        raise AssertionError((method, path))

    monkeypatch.setattr(workspace, "github", github)
    monkeypatch.setattr("modstore_server.retort_evolution_api.github", github)
    with get_session_factory()() as db:
        db.query(RetortEvolutionRun).delete()
        user = User(username=uuid4().hex, password_hash="test-only", is_admin=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[require_admin] = lambda: user
    yield {"client": client, "user": user, "calls": calls}
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)


def create(setup):
    request_id = str(uuid4())
    response = setup["client"].post(
        "/api/retort-evolution",
        json={
            "request_id": request_id,
            "template_id": "restore",
            "title": "验证恢复",
            "goal": "中断后恢复原任务，禁止重复发布",
        },
    )
    assert response.status_code == 200, response.text
    return request_id


def read(client, request_id):
    response = client.get(f"/api/retort-evolution/{request_id}")
    assert response.status_code == 200, response.text
    return response.json()


def decision(client, request_id, *, approved=True, extra=None):
    current = read(client, request_id)
    return client.post(
        f"/api/retort-evolution/{request_id}/decision",
        json={
            "digest": current["snapshot"]["pending"][0]["digest"],
            "approved": approved,
            **(extra or {}),
        },
    )


def test_management_to_verified_knowledge_preserves_two_approvals(setup, monkeypatch):
    client = setup["client"]
    request_id = create(setup)
    assert read(client, request_id)["status"] == "awaiting_dispatch_approval"
    assert not [c for c in setup["calls"] if c[0] == "POST"]
    stale = decision(client, request_id, extra={"digest": "0" * 64})
    assert stale.status_code == 409
    assert decision(client, request_id, extra={"actor_id": 999}).status_code == 422
    assert decision(client, request_id).status_code == 200
    assert len([c for c in setup["calls"] if c[0] == "POST"]) == 1
    monkeypatch.setattr(
        workspace,
        "collect_execution",
        lambda _: {"status": "completed", "run_id": "42", "target_sha": "d" * 40},
    )
    monkeypatch.setattr(
        workspace,
        "verify_execution",
        lambda *_: {
            "status": "checks_passed",
            "target_sha": "d" * 40,
            "evidence_digest": "f" * 64,
            "domain_status": "UNRATED",
            "score": None,
        },
    )
    service.tick()
    assert read(client, request_id)["status"] == "awaiting_acceptance"
    assert service.accepted_knowledge() == []
    assert decision(client, request_id).status_code == 200
    assert read(client, request_id)["status"] == "waiting_delivery"
    assert service.accepted_knowledge() == []
    monkeypatch.setattr(
        "modstore_server.retort_delivery.collect_delivery",
        lambda _: {"status": "waiting_delivery", "reason": "awaiting_protected_merge"},
    )
    service.tick()
    assert read(client, request_id)["status"] == "waiting_delivery"
    assert service.accepted_knowledge() == []
    monkeypatch.setattr(
        "modstore_server.retort_delivery.collect_delivery",
        lambda _: {"status": "deployment_verified", "merge_sha": "e" * 40},
    )
    service.tick()
    assert read(client, request_id)["status"] == "completed"
    records = service.accepted_knowledge()
    assert len(records) == 1 and records[0]["verification"]["score"] is None
    with get_session_factory()() as db:
        stored = json_loads(db.get(RetortEvolutionRun, request_id).knowledge_json, {})
        assert stored["approval"]["actor_id"] == setup["user"].id
    assert (
        client.post(
            f"/api/retort-evolution/{request_id}/decision",
            json={"digest": "0" * 64, "approved": True},
        ).status_code
        == 409
    )
    service.tick()
    assert len(service.accepted_knowledge()) == 1


def test_uncertain_issue_response_never_republishes(setup, monkeypatch):
    request_id = create(setup)
    posts = []

    def github(method, path, body=None):
        if method == "POST":
            posts.append(body)
            raise HTTPException(502, "response unknown")
        return []

    monkeypatch.setattr(workspace, "github", github)
    response = decision(setup["client"], request_id)
    assert response.status_code == 502
    for _ in range(3):
        service.advance_run(request_id)
    assert len(posts) == 1 and read(setup["client"], request_id)["status"] == "waiting_execution"
    assert service.accepted_knowledge() == []


def test_historical_branch_acceptance_is_not_promoted_to_production(setup):
    request_id = create(setup)
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, request_id)
        row.status = "completed"
        row.snapshot_json = json_dumps({"status": "completed", "knowledge": {"recorded": True}})
        row.knowledge_json = json_dumps({"evidence_verified": True})
        db.commit()
    assert read(setup["client"], request_id)["status"] == "branch_accepted"
    assert service.accepted_knowledge() == []


def test_rejected_work_cannot_dispatch_and_forged_incident_cannot_run(setup):
    request_id = create(setup)
    assert decision(setup["client"], request_id, approved=False).status_code == 200
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, request_id)
        payload = {
            "retort_run_id": request_id,
            "user_id": setup["user"].id,
            "github_workspace": {"retort_run_id": request_id, "request_id": request_id},
        }
        event = IncidentEvent(
            event_type="ops.retort.evolution", source="retort", payload_json=json_dumps(payload)
        )
        db.add(event)
        db.flush()
        row.event_id = event.id
        db.commit()
        assert workspace.authorized_incident(db, payload, event.id) is False
    assert not [c for c in setup["calls"] if c[0] == "POST"]


def test_overview_maps_all_18_domains_and_missing_configuration_is_explicit(setup, monkeypatch):
    monkeypatch.delenv("MODSTORE_RETORT_CHECKPOINT_DSN")
    result = setup["client"].get("/api/retort-evolution").json()
    assert len(result["domains"]) == 18
    assert sum(len(d["criteria"]) for d in result["domains"]) == 108
    assert result["connections"]["checkpoint"] is False
    assert service.tick() == {"processed": 0, "reason": "not_configured"}


def test_old_prompt_entry_does_not_promote_model_opinions(monkeypatch):
    from modstore_server import prompt_evolution_ab as prompts

    monkeypatch.delenv("MODSTORE_RETORT_RSI_PROTOCOL", raising=False)
    result = prompts.maybe_auto_apply_prompt_evolution(
        employee_id="test", prompt_before="a", prompt_after="b"
    )
    assert result["applied"] is False and result["ab"]["reason"] == "awaiting_measured_baseline"


def test_failed_auxiliary_experiment_keeps_retort_plan_and_approval(setup, tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_RETORT_RSI_PROTOCOL", str(tmp_path / "missing.json"))
    request_id = create(setup)
    result = read(setup["client"], request_id)
    assert result["status"] == "awaiting_dispatch_approval"
    assert result["snapshot"]["optimization"]["status"] == "experiment_failed"
    assert result["snapshot"]["optimization"]["automatically_applied"] is False
    assert result["snapshot"]["plan"]["public_body"]
    assert not [c for c in setup["calls"] if c[0] == "POST"]


def test_scheduler_repairs_projection_after_checkpoint_was_committed(setup, monkeypatch):
    request_id = create(setup)
    assert decision(setup["client"], request_id).status_code == 200
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, request_id)
        row.status = "awaiting_dispatch_approval"
        row.snapshot_json = "{}"
        db.commit()
    monkeypatch.setattr(workspace, "collect_execution", lambda _: {"status": "waiting"})
    service.tick()
    assert read(setup["client"], request_id)["status"] == "waiting_execution"
    assert len([c for c in setup["calls"] if c[0] == "POST"]) == 1


@pytest.mark.parametrize(
    "entry, digest_matches", [("log.txt", True), ("../escape", True), ("log.txt", False)]
)
def test_artifact_download_checks_digest_paths_and_credential_boundary(
    tmp_path, monkeypatch, entry, digest_matches
):
    import hashlib
    import io
    import zipfile

    import httpx

    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(entry, "raw execution evidence")
    payload = stream.getvalue()
    observed = []

    def respond(request):
        observed.append(request)
        if request.url.host == "api.github.com":
            return httpx.Response(
                302,
                headers={
                    "Location": "https://results.blob.core.windows.net/artifact?signature=test"
                },
            )
        return httpx.Response(200, content=payload)

    original = httpx.Client
    monkeypatch.setattr(
        workspace.httpx,
        "Client",
        lambda **kw: original(transport=httpx.MockTransport(respond), **kw),
    )
    monkeypatch.setenv("MODSTORE_GITHUB_TOKEN", "test-only-never-forward")
    expected = "sha256:" + (hashlib.sha256(payload).hexdigest() if digest_matches else "0" * 64)
    if entry.startswith("..") or not digest_matches:
        with pytest.raises(ValueError):
            workspace._download_artifact("example/product", 42, tmp_path, expected)
    else:
        workspace._download_artifact("example/product", 42, tmp_path, expected)
        assert (tmp_path / entry).read_text() == "raw execution evidence"
    assert observed[0].headers["authorization"] == "Bearer test-only-never-forward"
    assert "authorization" not in observed[1].headers


def test_completion_requires_issue_linked_pr_at_the_verified_commit(setup, monkeypatch):
    request_id = create(setup)
    assert decision(setup["client"], request_id).status_code == 200
    workspace._save(request_id, run_id=42)
    pulls = []

    def github(method, path, body=None):
        assert method == "GET"
        if path.endswith("/pulls"):
            return pulls
        return {
            "id": 42,
            "head_branch": "main",
            "head_sha": "a" * 40,
            "run_attempt": 1,
            "path": ".github/workflows/fhd-para-github-worker.yml",
            "status": "completed",
            "conclusion": "success",
            "html_url": "https://github.com/example/product/actions/runs/42",
        }

    monkeypatch.setattr(workspace, "github", github)
    monkeypatch.setattr(
        workspace,
        "worker_status",
        lambda _: {"finished": True, "conclusion": "success", "target_sha": "d" * 40},
    )
    assert workspace.collect_execution(request_id)["reason"] == "awaiting_pull_request"
    pulls.append(
        {
            "number": 456,
            "body": "Refs #123",
            "head": {"sha": "e" * 40},
            "base": {"ref": "main", "repo": {"full_name": "example/product"}},
        }
    )
    assert workspace.collect_execution(request_id)["reason"] == "awaiting_pull_request"
    pulls[0]["head"]["sha"] = "d" * 40
    result = workspace.collect_execution(request_id)
    assert result["status"] == "completed" and result["pull_request_number"] == 456


def test_verified_logs_are_retained_with_existing_retort_encryption(tmp_path, monkeypatch):
    import base64

    from cryptography.fernet import Fernet
    from retort_engine.secure_artifacts import read_private_json

    runtime, raw = tmp_path / "runtime", tmp_path / "raw"
    raw.mkdir()
    (raw / "execution.log").write_bytes(b"private test evidence")
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("RETORT_ARTIFACT_MASTER_KEY", Fernet.generate_key().decode())
    request_id = str(uuid4())
    reference = workspace._retain_artifact(request_id, "sha256:" + "a" * 64, raw)
    path = runtime / reference
    assert path.stat().st_mode & 0o777 == 0o600
    assert b"private test evidence" not in path.read_bytes()
    retained = read_private_json(path, allow_legacy=False)
    assert base64.b64decode(retained["files"]["execution.log"]) == b"private test evidence"
    assert workspace._retain_artifact(request_id, "sha256:" + "a" * 64, raw) == reference


@pytest.mark.skipif(
    not os.environ.get("RETORT_TEST_POSTGRES_DSN"), reason="isolated PostgreSQL required"
)
def test_postgres_native_lock_excludes_another_connection(monkeypatch):
    from sqlalchemy import create_engine

    engine = create_engine(os.environ["RETORT_TEST_POSTGRES_DSN"])
    monkeypatch.setattr(service, "get_engine", lambda: engine)
    request_id = str(uuid4())
    try:
        with service.run_lock(request_id):
            with pytest.raises(ValueError, match="另一执行节点"):
                with service.run_lock(request_id):
                    pytest.fail("duplicate owner entered the execution lock")
        with service.run_lock(request_id):
            pass
    finally:
        engine.dispose()


@pytest.mark.parametrize("failure", [ValueError("invalid protocol"), AssertionError("invariant")])
def test_optimizer_only_recovers_operational_errors(monkeypatch, failure):
    from types import SimpleNamespace

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setenv("MODSTORE_RETORT_RSI_PROTOCOL", "synthetic-protocol.json")
    monkeypatch.setattr(
        service, "load_repository_module", lambda _: SimpleNamespace(optimize_protocol=fail)
    )
    ports = service.ComponentPorts(str(uuid4()))
    if isinstance(failure, AssertionError):
        with pytest.raises(AssertionError, match="invariant"):
            ports.optimize({}, {"public_body": "original"})
    else:
        result = ports.optimize({}, {"public_body": "original"})
        assert result["status"] == "experiment_failed"
        assert result["error_type"] == "ValueError"
        assert result["automatically_applied"] is False


@pytest.mark.parametrize(
    "failure", [ValueError("temporarily unavailable"), AssertionError("invariant")]
)
def test_background_only_recovers_operational_errors(monkeypatch, caplog, failure):
    from modstore_server.retort_evolution_api import _advance

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(service, "advance_run", fail)
    if isinstance(failure, AssertionError):
        with pytest.raises(AssertionError, match="invariant"):
            _advance("synthetic-request")
    else:
        _advance("synthetic-request")
        assert "Retort continuation incomplete" in caplog.text


@pytest.mark.parametrize(
    "failure", [ValueError("temporarily unavailable"), AssertionError("invariant")]
)
def test_tick_only_recovers_operational_errors(setup, monkeypatch, failure):
    request_id = create(setup)

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(service, "advance_run", fail)
    if isinstance(failure, AssertionError):
        with pytest.raises(AssertionError, match="invariant"):
            service.tick()
    else:
        assert service.tick()["errors"] == [{"request_id": request_id, "error": "ValueError"}]


@pytest.mark.parametrize("failure", [ValueError("invalid dispatch"), AssertionError("invariant")])
def test_advance_only_projects_operational_errors(setup, monkeypatch, failure):
    request_id = create(setup)
    before = read(setup["client"], request_id)

    def fail(self, state):
        raise failure

    monkeypatch.setattr(service.ComponentPorts, "dispatch", fail)
    with pytest.raises(type(failure), match=str(failure)):
        service.advance_run(
            request_id,
            approval={
                "digest": before["snapshot"]["pending"][0]["digest"],
                "approved": True,
                "actor_id": setup["user"].id,
            },
        )
    after = read(setup["client"], request_id)
    assert after["error"] == ("" if isinstance(failure, AssertionError) else "invalid dispatch")
    assert not [call for call in setup["calls"] if call[0] == "POST"]


def test_feedback_selection_scans_past_already_used_candidates(setup, monkeypatch):
    from modstore_server import retort_customer_feedback as feedback
    from modstore_server.models_cs import CustomerServiceSession, CustomerServiceTicket

    monkeypatch.setattr(feedback, "_eligible", lambda *_: True)
    with get_session_factory()() as db:
        customer = User(username=uuid4().hex, password_hash="test-only", is_admin=False)
        db.add(customer)
        db.flush()
        session = CustomerServiceSession(user_id=customer.id)
        db.add(session)
        db.flush()
        tickets = [
            CustomerServiceTicket(
                user_id=customer.id,
                session_id=session.id,
                ticket_no=f"{uuid4()}",
                submitter_type="customer",
                intent="product_issue",
                status="open",
                summary="真实问题",
                evidence_json="{}",
            )
            for _ in range(21)
        ]
        db.add_all(tickets)
        db.flush()
        selected = feedback._candidates(db, "platform", {(item.id, "") for item in tickets[1:]})
        assert [item["ticket_id"] for item in selected.values()] == [tickets[0].id]


@pytest.mark.parametrize("customer_decision", ["resolved", "reopen"])
def test_feedback_run_binds_original_customer_and_production_release(
    setup, monkeypatch, customer_decision
):
    from datetime import UTC, datetime

    from modstore_server.api.deps import get_current_user
    from modstore_server.models_cs import (
        CustomerServiceMessage,
        CustomerServiceSession,
        CustomerServiceTicket,
    )

    ticket_no = f"isolated-feedback-{uuid4()}"
    with get_session_factory()() as db:
        customer = User(username=uuid4().hex, password_hash="test-only", is_admin=False)
        db.add(customer)
        db.flush()
        session = CustomerServiceSession(user_id=customer.id)
        db.add(session)
        db.flush()
        db.add(
            CustomerServiceTicket(
                user_id=customer.id,
                session_id=session.id,
                ticket_no=ticket_no,
                submitter_type="customer",
                intent="product_issue",
                status="open",
                summary="首次导入未成功。联系 test-private@example.com",
                evidence_json=json_dumps(
                    {
                        "issue_domain": "platform",
                        "resolution": {"state": "received", "route": "shared_core"},
                    }
                ),
            )
        )
        db.commit()
        ticket = db.query(CustomerServiceTicket).filter_by(ticket_no=ticket_no).one()
        ticket_id = ticket.id
        db.refresh(customer)
        db.expunge(customer)

    with open(os.environ["MODSTORE_RETORT_PROTOCOLS"], encoding="utf-8") as fh:
        templates = json.load(fh)
    templates["restore"]["customer_feedback"] = {
        "domain": "platform",
        "surface": "shared_web",
        "goal": "验证首次导入反馈并恢复正确路径",
    }
    with open(os.environ["MODSTORE_RETORT_PROTOCOLS"], "w", encoding="utf-8") as fh:
        json.dump(templates, fh)

    def model(messages, **kwargs):
        assert "首次导入未成功" in messages[1]["content"]
        assert "test-private@example.com" not in messages[1]["content"]
        assert ticket_no not in messages[1]["content"]
        return {"ok": True, "content": '{"candidate": 1}'}

    monkeypatch.setattr(service, "reflect", model)
    client, request_id = setup["client"], str(uuid4())
    base = "/api/retort-evolution"
    body = {"request_id": request_id, "template_id": "restore", "source": "customer_feedback"}
    response = client.post(base, json=body)
    assert response.status_code == 200, response.text
    assert client.post(base, json=body).json()["id"] == request_id
    selected = read(client, request_id)
    assert selected["status"] == "awaiting_dispatch_approval"
    assert selected["effects"]["customer_feedback"]["ticket_id"] == ticket_id
    assert selected["effects"]["customer_feedback"]["allocated_worker_slots"] == 1
    assert ticket_no not in selected["snapshot"]["plan"]["public_body"]

    monkeypatch.setattr(service.ComponentPorts, "collect", lambda _self, _: {"status": "completed"})
    monkeypatch.setattr(
        service.ComponentPorts,
        "verify",
        lambda _self, _: {"status": "checks_passed", "target_sha": "b" * 40},
    )
    monkeypatch.setattr(
        service.ComponentPorts, "delivery", lambda _self, _: {"status": "waiting_delivery"}
    )

    def approve():
        status = read(client, request_id)
        digest = status["snapshot"]["pending"][0]["digest"]
        result = client.post(
            f"{base}/{request_id}/decision", json={"digest": digest, "approved": True}
        )
        assert result.status_code == 200, result.text

    def resume():
        result = client.post(f"{base}/{request_id}/resume")
        assert result.status_code == 200, result.text
        return read(client, request_id)

    approve()
    assert resume()["status"] == "awaiting_acceptance"
    approve()
    assert resume()["status"] == "waiting_delivery"
    with get_session_factory()() as db:
        assert db.get(CustomerServiceTicket, ticket_id).status == "open"

    delivery = {
        "status": "deployment_verified",
        "merge_sha": "c" * 40,
        "deployment_run_id": 205,
        "verified_at": datetime.now(UTC).isoformat(),
    }
    monkeypatch.setattr(service.ComponentPorts, "delivery", lambda _self, _: delivery)
    assert resume()["status"] == "delivered"
    assert resume()["status"] == "waiting_customer_impact"
    assert resume()["status"] == "waiting_customer_impact"
    with get_session_factory()() as db:
        assert db.get(CustomerServiceTicket, ticket_id).status == "awaiting_customer"
        assert db.query(CustomerServiceMessage).filter_by(ticket_id=ticket_id).count() == 1

    decision_path = f"/api/customer-service/issues/{ticket_id}/decision"
    decision = {
        "decision": customer_decision,
        "note": "已按原业务路径复测成功",
        "idempotency_key": str(uuid4()),
    }
    app.dependency_overrides[get_current_user] = lambda: setup["user"]
    assert client.post(decision_path, json=decision).status_code == 404
    app.dependency_overrides[get_current_user] = lambda: customer
    result = client.post(decision_path, json=decision)
    assert result.status_code == 200, result.text
    if customer_decision == "reopen":
        with get_session_factory()() as db:
            ticket = db.get(CustomerServiceTicket, ticket_id)
            evidence = json_loads(ticket.evidence_json, {})
            evidence["resolution"]["state"] = "processing"
            ticket.evidence_json = json_dumps(evidence)
            db.commit()
    final = resume()
    if customer_decision == "reopen":
        assert final["status"] == "customer_impact_rejected"
        assert final["snapshot"]["impact"]["release_sha"] == "c" * 40
        return
    assert final["status"] == "completed"
    assert final["snapshot"]["impact"]["release_sha"] == "c" * 40
    assert final["snapshot"]["impact"]["status"] == "customer_impact_verified"
    assert final["snapshot"]["impact"]["commercial"]["status"] == "not_configured"


def test_growthbook_requires_same_run_production_exposure_and_valid_sample():
    from modstore_server.retort_feedback_measurements import _snapshot

    sha = "c" * 40
    spec = {"id": "exp_feedback", "project": "prod", "metric": "first_import", "minimum_users": 100}
    delivery = {"merge_sha": sha, "verified_at": "2026-01-01T00:00:00Z"}
    result = {
        "experiment": {
            "id": spec["id"],
            "project": "prod",
            "type": "standard",
            "status": "stopped",
            "trackingKey": "xcagi-retort-run",
            "tags": [f"xcagi-release-{sha}"],
        },
        "result": {
            "id": "snapshot_feedback",
            "experimentId": spec["id"],
            "dateStart": "2026-01-02T00:00:00Z",
            "dateUpdated": "2026-01-03T00:00:00Z",
            "dimension": {"type": "none"},
            "results": [
                {
                    "totalUsers": 120,
                    "checks": {"srm": 0.9},
                    "metrics": [
                        {
                            "metricId": "first_import",
                            "variations": [
                                {"users": 60},
                                {
                                    "users": 60,
                                    "analyses": [
                                        {"percentChange": 0.12, "ciLow": 0.02, "ciHigh": 0.22}
                                    ],
                                },
                            ],
                        }
                    ],
                }
            ],
        },
    }
    observed = _snapshot(result, spec, "run", delivery)
    assert observed["status"] == "measured"
    assert observed["lift"] == 0.12
    assert _snapshot(result, spec, "other-run", delivery)["status"] == "unbound"
    result["result"]["results"][0]["checks"]["srm"] = 0.0001
    assert _snapshot(result, spec, "run", delivery)["status"] == "sample_unverified"
