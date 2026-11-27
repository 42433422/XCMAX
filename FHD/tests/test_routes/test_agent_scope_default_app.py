"""Real application/session ownership checks; no model or business worker runs."""

from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest
from openpyxl import Workbook
from sqlalchemy.orm import Session as DbSession

from app.application.agent_orchestrator.artifact_files import store_spreadsheet
from app.application.agent_orchestrator.run_models import AgentRun, artifact_from_dict
from app.infrastructure.tenant_scope import tenant_scope
from tests.test_routes.test_template_create_default_app import template_app as host_app

pytestmark = pytest.mark.release_gate


@pytest.fixture
def scoped_app(host_app):  # noqa: F811 - imported pytest fixture
    from app.db.models.user import Session, User

    client, engine, repo = host_app
    with DbSession(engine) as db, db.begin():
        admin = db.get(User, 9)
        admin.role, admin.tier = "admin", "admin"
        db.add(
            User(
                id=10,
                username="legacy-admin",
                password="unused",
                role="admin",
                tier="enterprise",
                tenant_id=11,
            )
        )
        db.add(
            Session(
                session_id="legacy-admin-session",
                user_id=10,
                account_kind="enterprise",
                expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
            )
        )
    from app.infrastructure.session.session_manager import SessionManager

    assert SessionManager()._validate_session_once("label-session-7") is not None
    yield client, repo


def _run_with_file(repo, user_id, tenant):
    run = AgentRun(user_id=str(user_id), message="private customer task", status="completed")
    run.metadata["runtime_context"] = {"tenant_id": str(tenant)}
    workbook = Workbook()
    workbook.active.append(["synthetic customer evidence"])
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    run.artifacts.append(artifact_from_dict(store_spreadsheet(run.run_id, output.getvalue())))
    repo.save(run)
    return run, output.getvalue()


@pytest.mark.parametrize(
    "session_id", ["label-session-9", "legacy-admin-session", "label-session-8"]
)
def test_registered_app_denies_other_owner_before_read_or_mutation(scoped_app, session_id):
    client, repo = scoped_app
    run, _content = _run_with_file(repo, 7, 11)
    before = repo.get(run.run_id).to_dict()
    operations = [
        ("GET", ""),
        ("GET", "/events"),
        ("GET", "/events/stream"),
        ("GET", f"/artifacts/{run.artifacts[0].artifact_id}"),
    ]
    operations += [
        ("POST", "/" + action)
        for action in ("clarification", "continue", "pause", "cancel", "resume", "retry")
    ]
    for method, suffix in operations:
        response = client.request(
            method,
            f"/api/agent/runs/{run.run_id}{suffix}",
            headers={"X-Session-ID": session_id},
            json={"step_id": "private-step", "parameters": {}} if method == "POST" else None,
        )
        assert response.status_code == 403, (suffix, response.text)
        assert response.json()["message"] == "无权访问该 agent run"
        assert "private customer task" not in response.text
        assert "synthetic customer evidence" not in response.text
        assert repo.get(run.run_id).to_dict() == before
        assert repo.latest_task_control(run.run_id) is None


@pytest.mark.parametrize(
    "user_id,tenant,session_id", [(7, "11", "label-session-7"), (9, "", "label-session-9")]
)
def test_registered_app_preserves_owner_and_admin_own_artifacts(
    scoped_app, user_id, tenant, session_id
):
    client, repo = scoped_app
    run, content = _run_with_file(repo, user_id, tenant)
    headers = {"X-Session-ID": session_id}
    detail = client.get(f"/api/agent/runs/{run.run_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["run_id"] == run.run_id
    assert client.get(f"/api/agent/runs/{run.run_id}/events", headers=headers).status_code == 200
    artifact = client.get(
        f"/api/agent/runs/{run.run_id}/artifacts/{run.artifacts[0].artifact_id}", headers=headers
    )
    assert artifact.status_code == 200, artifact.text
    assert artifact.content == content
    assert artifact.headers["cache-control"] == "private, no-store"


def test_registered_app_rejects_forged_identity_headers_without_session(scoped_app):
    client, repo = scoped_app
    run, _content = _run_with_file(repo, 7, 11)
    with tenant_scope(None):
        response = client.get(
            f"/api/agent/runs/{run.run_id}", headers={"X-User-ID": "7", "X-Tenant-ID": "11"}
        )
    assert response.status_code == 401, response.text


@pytest.mark.parametrize("invalid", ["bytes", "uri", "type"])
def test_registered_office_download_requires_owner_and_original_file(scoped_app, invalid):
    from docx import Document

    from app.application.agent_orchestrator.artifact_files import artifact_path, store_run_file

    client, repo = scoped_app
    run = AgentRun(user_id="7", message="private office task", status="completed")
    run.metadata["runtime_context"] = {"tenant_id": "11"}
    document = Document()
    document.add_paragraph("Synthetic owner-bound office artifact")
    output = BytesIO()
    document.save(output)
    content = output.getvalue()
    saved = store_run_file(run.run_id, content, name="sample.docx", owner_user_id=7, tenant_id="11")
    saved["artifact_type"] = "office_document"
    run.artifacts.append(artifact_from_dict(saved))
    repo.save(run)
    uri = saved["uri"]
    headers = {"X-Session-ID": "label-session-7"}
    response = client.get(uri, headers=headers)
    assert response.status_code == 200, response.text
    assert response.content == content
    assert response.headers["cache-control"] == "private, no-store"
    for session_id in ("label-session-8", "label-session-9"):
        assert client.get(uri, headers={"X-Session-ID": session_id}).status_code == 403
    assert client.get(uri).status_code == 401
    if invalid == "bytes":
        artifact_path(run.run_id, saved["artifact_id"]).write_bytes(b"changed")
    else:
        artifact = run.artifacts[0]
        if invalid == "uri":
            artifact.uri = "/api/ai/kitten/document/pickup/unrelated"
        else:
            artifact.artifact_type = "unregistered_document"
        repo.save(run)
    denied = client.get(uri, headers=headers)
    assert denied.status_code == (404 if invalid == "type" else 410), denied.text
    assert "Synthetic owner-bound office artifact" not in denied.text


def test_credentialed_cross_origin_download_exposes_artifact_integrity(scoped_app, monkeypatch):
    import hashlib

    from fastapi.testclient import TestClient

    from app.config import TestingConfig
    from app.fastapi_app import factory

    _client, repo = scoped_app
    run, content = _run_with_file(repo, 7, 11)
    monkeypatch.setattr(factory, "_app_singleton", None)
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:5173")
    client = TestClient(factory.create_fastapi_app(TestingConfig, enable_cors=True))
    try:
        response = client.get(
            run.artifacts[0].uri,
            headers={
                "X-Session-ID": "label-session-7",
                "Origin": "http://localhost:5173",
            },
        )
        assert response.status_code == 200
        assert response.content == content
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
        assert response.headers["access-control-allow-credentials"] == "true"
        exposed = {
            item.strip().lower()
            for item in response.headers["access-control-expose-headers"].split(",")
        }
        assert {"x-artifact-sha256", "x-artifact-size"} <= exposed
        assert response.headers["x-artifact-sha256"] == hashlib.sha256(content).hexdigest()
    finally:
        client.close()
