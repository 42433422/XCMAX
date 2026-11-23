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
    "entry, digest_matches",
    [("log.txt", True), ("../escape", True), ("log.txt", False)],
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


@pytest.mark.parametrize("customer_feedback", [False, True])
def test_completion_requires_issue_linked_pr_at_the_verified_commit(
    setup, monkeypatch, customer_feedback
):
    request_id = create(setup)
    assert decision(setup["client"], request_id).status_code == 200
    workspace._save(request_id, run_id=42)
    if customer_feedback:
        # Existing executions created before the credential pause retain readback.
        workspace._save(request_id, customer_feedback={"ticket_id": 1})
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
    missing = (
        "customer_feedback_requires_non_exportable_model_credentials"
        if customer_feedback
        else "awaiting_pull_request"
    )
    assert workspace.collect_execution(request_id)["reason"] == missing
    pulls.append(
        {
            "number": 456,
            "body": "Refs #123",
            "head": {"sha": "e" * 40},
            "base": {"ref": "main", "repo": {"full_name": "example/product"}},
        }
    )
    assert workspace.collect_execution(request_id)["reason"] == missing
    pulls[0]["head"]["sha"] = "d" * 40
    result = workspace.collect_execution(request_id)
    assert result["status"] == "completed" and result["pull_request_number"] == 456


@pytest.mark.parametrize(
    "existing",
    [
        {},
        {"issue_number": 123},
        {"issue_number": 123, "runner_intent": True},
        {"issue_number": 123, "run_id": 42},
    ],
)
def test_customer_feedback_resume_never_starts_or_redispatches_a_model(
    setup, monkeypatch, existing
):
    from modstore_server.retort_customer_feedback import CREDENTIAL_BLOCK

    request_id = create(setup)
    workspace._save(request_id, customer_feedback={"ticket_id": 1}, **existing)
    calls = []

    def github(method, path, body=None):
        calls.append((method, path))
        assert method == "GET" and path.endswith("/actions/runs/42")
        return {
            "id": 42,
            "head_branch": "main",
            "head_sha": "a" * 40,
            "run_attempt": 1,
            "path": ".github/workflows/fhd-para-github-worker.yml",
            "status": "in_progress",
        }

    monkeypatch.setattr(workspace, "github", github)
    monkeypatch.setattr(
        workspace.httpx, "Client", lambda **kw: pytest.fail("no device or model dispatch")
    )
    for _ in range(2):
        assert workspace.collect_execution(request_id) == {
            "status": "blocked",
            "reason": CREDENTIAL_BLOCK,
        }
    assert len(calls) == (2 if existing.get("run_id") else 0)
    with get_session_factory()() as db:
        assert db.get(RetortEvolutionRun, request_id).event_id is None


def test_failed_independent_report_is_archived_but_not_accepted(monkeypatch):
    import hashlib

    from retort_engine.evolution_contract import digest

    request_id = str(uuid4())
    protocol = {
        "request_id": request_id,
        "repository": "example/product",
        "source_sha": "a" * 40,
        "criterion_ids": ["shared-engine-B2"],
        "checks": [{"id": "restore", "criterion_ids": ["shared-engine-B2"]}],
    }
    protocol["protocol_digest"] = digest(protocol)
    target = "d" * 40
    run = {
        "id": 41,
        "status": "completed",
        "conclusion": "failure",
        "run_attempt": 1,
        "head_sha": protocol["source_sha"],
        "path": f".github/workflows/{workspace.WORKFLOW}",
    }
    effects = {"run_id": 41}
    artifact = {
        "id": 1,
        "digest": "sha256:" + "b" * 64,
        "name": f"retort-verification-{request_id}",
        "expired": False,
    }
    monkeypatch.setattr(
        workspace,
        "worker_status",
        lambda _: {
            "finished": True,
            "conclusion": "success",
            "request_id": request_id,
            "run_id": 41,
            "target_sha": target,
        },
    )
    calls = []

    def github(method, path):
        calls.append((method, path))
        assert method == "GET"
        assert path == "/repos/example/product/actions/runs/41/artifacts"
        return {"artifacts": [artifact]}

    def download(repo, artifact_id, root, artifact_digest):
        assert (repo, artifact_id, artifact_digest) == (
            "example/product", 1, artifact["digest"]
        )
        row = {"id": "restore", "check_digest": digest(protocol["checks"][0])}
        for phase, code in (("before", 0), ("after", 1)):
            path = root / f"{phase}.log"
            path.write_bytes(phase.encode())
            row[phase] = {
                "returncode": code,
                "timed_out": False,
                "log_path": path.name,
                "log_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        bundle = {
            "request_id": request_id,
            "protocol_digest": protocol["protocol_digest"],
            "repository": protocol["repository"],
            "source_sha": protocol["source_sha"],
            "target_sha": target,
            "run_id": "41",
            "run_attempt": 1,
            "isolation": "docker",
            "checks": [row],
        }
        (root / "verification.json").write_text(json.dumps(bundle))

    monkeypatch.setattr(workspace, "github", github)
    monkeypatch.setattr(workspace, "_download_artifact", download)
    monkeypatch.setattr(workspace, "_retain_artifact", lambda *_: "encrypted-reference")
    monkeypatch.setattr(workspace, "_save", lambda _, **updates: effects.update(updates))

    assert workspace.archive_failed_verification(
        request_id, protocol, effects, {**run, "conclusion": "success"}
    ) is None
    report = workspace.archive_failed_verification(request_id, protocol, effects, run)
    assert report["status"] == "workflow_failed"
    assert report["comparison"]["candidate_passed"] == 0
    assert report["comparison"]["baseline_passed"] == 1
    assert effects["failed_verification"] == report
    assert "verification" not in effects
    assert workspace.archive_failed_verification(request_id, protocol, effects, run) == report
    assert len(calls) == 1


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
    not os.environ.get("RETORT_TEST_POSTGRES_DSN"),
    reason="isolated PostgreSQL required",
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
