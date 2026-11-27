"""Durable Agent file downloads through real SQLite sessions and the registered router."""

import hashlib
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.artifact_files import artifact_path, store_spreadsheet
from app.application.agent_orchestrator.run_models import AgentRun, artifact_from_dict
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.db.models.user import Session, User
from app.fastapi_routes.domains.agent import artifact_routes
from tests.test_application.test_authenticated_principal_propagation import (
    sessions as sessions,
)


@pytest.fixture
def delivery(sessions, tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "0")
    repo = SQLAlchemyAgentRunRepository(session_factory=sessions)
    run = AgentRun("71", "deliver original workbook", status="completed")
    run.metadata["runtime_context"] = {"tenant_id": "7"}
    workbook = Workbook()
    workbook.active.append(["actual workbook bytes", 42])
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    content = output.getvalue()
    receipt = store_spreadsheet(
        run.run_id, content, name="result.xlsx", owner_user_id=71, tenant_id="7"
    )
    run.artifacts.append(artifact_from_dict(receipt))
    repo.save(run)
    # A new SQL engine/repository reads the saved receipt, never an in-memory run.
    original_engine = sessions.kw["bind"]
    original_engine.dispose()
    reopened_engine = create_engine(original_engine.url)
    reopened = SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=reopened_engine))
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        lambda: reopened,
    )
    app = FastAPI()
    app.include_router(artifact_routes.router)
    with TestClient(app) as client:
        yield client, reopened, run, receipt, content
    reopened_engine.dispose()


def test_original_verified_bytes_download_after_sql_repository_restart(delivery):
    client, _repo, _run, receipt, content = delivery
    response = client.get(receipt["uri"], headers={"X-Session-ID": "valid"})
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["x-artifact-sha256"] == hashlib.sha256(content).hexdigest()
    assert response.headers["x-artifact-size"] == str(len(content))
    assert response.headers["cache-control"] == "private, no-store"
    assert int(response.headers["content-length"]) == len(content)


@pytest.mark.parametrize("field", ["owner_user_id", "tenant_id", "run_id", "uri"])
def test_download_rejects_receipt_rebound_to_another_scope(delivery, field):
    client, repo, run, receipt, _content = delivery
    artifact = run.artifacts[0]
    if field == "uri":
        artifact.uri = "/api/agent/runs/another-run/artifacts/another-file"
    else:
        artifact.metadata[field] = {"owner_user_id": "81", "tenant_id": "8", "run_id": "other"}[
            field
        ]
    repo.save(run)
    response = client.get(receipt["uri"], headers={"X-Session-ID": "valid"})
    assert response.status_code == 410


@pytest.mark.parametrize("scope", ["anonymous", "owner", "tenant", "revoked"])
def test_download_revalidates_current_identity_and_authorization(delivery, sessions, scope):
    client, _repo, _run, receipt, _content = delivery
    assert client.get(receipt["uri"], headers={"X-Session-ID": "valid"}).status_code == 200
    session_id = "valid"
    if scope == "owner":
        with sessions.begin() as db:
            db.get(User, 81).tenant_id = 7
        session_id = "other"
    elif scope == "tenant":
        with sessions.begin() as db:
            db.get(User, 71).tenant_id = 8
    elif scope == "revoked":
        with sessions.begin() as db:
            db.delete(db.query(Session).filter_by(session_id="valid").one())
    response = client.get(
        receipt["uri"], headers={} if scope == "anonymous" else {"X-Session-ID": session_id}
    )
    assert response.status_code == (401 if scope in {"anonymous", "revoked"} else 403)
    assert "x-artifact-sha256" not in response.headers


def test_download_rechecks_revoked_mod_entitlement(delivery, sessions):
    from app.infrastructure.auth.agent_principal import require_agent_principal
    from tests.test_application.test_authenticated_principal_propagation import request

    client, repo, _original, _receipt, content = delivery
    principal = require_agent_principal(request("valid", "synthetic-mod"), x_user_id=None)
    run = AgentRun("71", "mod-owned file", status="completed")
    run.metadata["runtime_context"] = {
        "tenant_id": "7",
        "_mod_authorization": principal.mod_authorization,
    }
    receipt = store_spreadsheet(run.run_id, content, owner_user_id=71, tenant_id="7")
    run.artifacts.append(artifact_from_dict(receipt))
    repo.save(run)
    headers = {"X-Session-ID": "valid", "X-XCAGI-Active-Mod-ID": "synthetic-mod"}
    assert client.get(receipt["uri"], headers=headers).status_code == 200
    with sessions.begin() as db:
        db.query(Session).filter_by(session_id="valid").one().entitled_mod_ids_json = "[]"
    assert client.get(receipt["uri"], headers=headers).status_code == 403
    assert client.get(receipt["uri"], headers={"X-Session-ID": "valid"}).status_code == 403


def test_download_rejects_file_replaced_after_original_verification(delivery):
    client, _repo, run, receipt, _content = delivery
    artifact_path(run.run_id, receipt["artifact_id"]).write_bytes(b"wrong result")
    response = client.get(receipt["uri"], headers={"X-Session-ID": "valid"})
    assert response.status_code == 410
    assert "x-artifact-sha256" not in response.headers
