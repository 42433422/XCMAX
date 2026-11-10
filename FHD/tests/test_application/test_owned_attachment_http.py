"""Real HTTP principal resolution cannot promote caller paths to attachment evidence."""

import io
import json
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.application.elt.service_uploads import UploadServiceMixin
from app.db.models.elt import EltUpload
from app.db.session import get_db
from app.fastapi_routes.domains.agent import agent_routes
from app.infrastructure.tenant_scope import tenant_scope
from evals.run_agent_eval import _authenticated_route_fixture, _isolated_task_execution_queue


def test_authenticated_http_resolves_owned_upload_and_rejects_changed_owner(tmp_path):
    app = FastAPI()
    app.include_router(agent_routes.router)
    repo = InMemoryAgentRunRepository()
    seen = []

    def completion(**kwargs):
        seen.append(kwargs["context"]["file_context"]["verified_uploads"])
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"mode": "reply", "reply": "The price is 120."})
                    }
                }
            ]
        }

    with (
        TestClient(app) as client,
        _authenticated_route_fixture(client, role_name="admin"),
        _isolated_task_execution_queue(tmp_path),
        patch("app.utils.path_io.path_utils.get_app_data_dir", return_value=str(tmp_path)),
        patch("app.application.elt.service_uploads.get_app_data_dir", return_value=str(tmp_path)),
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch(
            "app.application.workflow.planner.request_planner_completion", side_effect=completion
        ),
    ):
        with tenant_scope(7), get_db() as db:
            upload = UploadServiceMixin().save_upload(
                db,
                owner_user_id=1,
                file_name="prices.csv",
                content_type="text/csv",
                stream=io.BytesIO(b"product,price\npaint,120\n"),
            )
        payload = {
            "message": "Read the attached prices.",
            "auto_execute": False,
            "runtime_context": {
                "attachment_upload_ids": [upload["upload_id"]],
                "tenant_id": 99,
                "user_id": "99",
            },
        }
        response = client.post("/api/agent/runs", json=payload)
        assert response.status_code == 200, response.text
        run = response.json()["data"]
        assert "paint" in seen[0][0]["text"]
        assert run["artifacts"][0]["metadata"]["skip_dataset_ingest"] is True
        assert run["artifacts"][0]["uri"] == ""
        assert not run["tool_calls"]
        with tenant_scope(7), get_db() as db:
            db.query(EltUpload).filter(EltUpload.id == upload["upload_id"]).one().owner_user_id = 99
        rejected = client.post("/api/agent/runs", json=payload)
        assert rejected.status_code == 200, rejected.text
        denied = rejected.json()["data"]
        assert denied["intent"] == "attachment_reupload_required"
        assert not denied["artifacts"]
        assert len(seen) == 1
        client.headers.pop("X-Session-ID")
        assert client.post("/api/agent/runs", json=payload).status_code == 401


@pytest.mark.parametrize("endpoint", ["/api/ai/chat", "/api/ai/chat/stream"])
def test_real_chat_routes_resolve_owned_attachment_before_model(tmp_path, endpoint):
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.application.workflow.planner import LLMWorkflowPlanner
    from app.legacy.routes.conversation.compat_routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    seen = []

    def completion(**kwargs):
        seen.append(kwargs["context"]["file_context"]["verified_uploads"])
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"mode": "reply", "reply": "The attached price is 120."}
                        )
                    }
                }
            ]
        }

    service = AIChatApplicationService()
    service.workflow_planner = LLMWorkflowPlanner(completion=completion)
    with (
        TestClient(app) as client,
        _authenticated_route_fixture(client, role_name="admin"),
        _isolated_task_execution_queue(tmp_path),
        patch("app.utils.path_io.path_utils.get_app_data_dir", return_value=str(tmp_path)),
        patch("app.application.elt.service_uploads.get_app_data_dir", return_value=str(tmp_path)),
        patch("app.application.get_ai_chat_app_service", return_value=service),
    ):
        with tenant_scope(7), get_db() as db:
            upload = UploadServiceMixin().save_upload(
                db,
                owner_user_id=1,
                file_name="prices.csv",
                content_type="text/csv",
                stream=io.BytesIO(b"product,price\npaint,120\n"),
            )
        payload = {
            "message": "Summarize the attached file.",
            "context": {
                "attachment_upload_ids": [upload["upload_id"]],
                "tenant_id": 99,
                "user_id": "99",
            },
        }
        response = client.post(endpoint, json=payload)
        assert response.status_code == 200, response.text
        assert len(seen) == 1, response.text
        assert "paint" in seen[0][0]["text"]
        assert seen[0][0]["coverage"]["truncated"] is False
        assert "The attached price is 120." in response.text
        assert "skip_dataset_ingest" in response.text
        with tenant_scope(7), get_db() as db:
            db.query(EltUpload).filter(EltUpload.id == upload["upload_id"]).one().owner_user_id = 99
        denied = client.post(endpoint, json=payload)
        assert denied.status_code == 200, denied.text
        assert "attachment_reupload_required" in denied.text
        assert len(seen) == 1
