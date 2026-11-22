"""Real HTTP/auth/SQL/compiler verify owned uploads before external model I/O."""

import io
import json

import httpx
import openai
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_runtime import codex_runtime, gateway
from app.application.elt.service_uploads import UploadServiceMixin
from app.db.models.elt import EltUpload
from app.db.session import get_db
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.codex_http_runtime import runtime_entry as runtime_entry
from tests.fixtures.planner_model import goal_review_response


@pytest.fixture
def owned_runtime(runtime_entry, tmp_path, monkeypatch):
    state = runtime_entry
    state.model_requests, state.plans, state.reviews, state.transports = [], [], [], []
    state.source = "Read the attached prices."
    state.reply = "The attached price is 120."
    real_openai = openai.OpenAI

    def response(request):
        body = json.loads(request.content)
        assert body["tools"] == [] and body["store"] is False
        prompt = json.loads(body["input"][-1]["content"])
        state.model_requests.append(prompt)
        uploads = prompt["context"]["file_context"]["verified_uploads"]
        assert "paint,120" in uploads[0]["text"]
        assert uploads[0]["coverage"]["truncated"] is False
        if prompt.get("task") == "audit_goal_coverage":
            state.reviews.append(prompt)
            content = goal_review_response(
                prompt,
                source=getattr(state, "review_source", state.source),
                node_ids=["model_reply"],
                outcome="reply",
            )["choices"][0]["message"]["content"]
        else:
            state.plans.append(prompt)
            content = json.dumps({"mode": "reply", "reply": state.reply})
        return httpx.Response(
            200,
            json={
                "id": "resp_fixture",
                "object": "response",
                "created_at": 1,
                "model": "test-fixture-model",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "id": "msg_fixture",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": content, "annotations": []}],
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20},
            },
        )

    def client(**kwargs):
        kwargs.pop("http_client").close()
        return real_openai(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(response))
        )

    class Transport:
        def __init__(self, config):
            self.config = config
            state.transports.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def start_thread(self, *, developer_instructions):
            return "thread-owned-upload"

        async def interrupt(self):
            return None

        async def stream_turn(self, text):
            assert state.reply in text and "host_reviewed_reply" in text
            for method, payload in (
                ("turn/started", {"turn": {"status": "inProgress"}}),
                (
                    "item/completed",
                    {"item": {"id": "reply", "type": "agentMessage", "text": state.reply}},
                ),
                ("turn/completed", {"turn": {"status": "completed"}}),
            ):
                yield {
                    "method": method,
                    "payload": payload,
                    "thread_id": "thread-owned-upload",
                    "turn_id": "turn-owned-upload",
                }

    monkeypatch.setattr(openai, "OpenAI", client)
    monkeypatch.setattr(gateway, "run_codex_agent", codex_runtime.run_codex_agent)
    monkeypatch.setattr("app.infrastructure.codex.CodexTransport", Transport)
    monkeypatch.setattr(
        "app.application.agent_runtime.chat.runtime_settings", lambda: state.settings
    )
    monkeypatch.setattr("app.utils.path_io.path_utils.get_app_data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(
        "app.application.elt.service_uploads.get_app_data_dir", lambda: str(tmp_path)
    )
    with tenant_scope(state.actor.tenant_id), get_db() as db:
        state.upload = UploadServiceMixin().save_upload(
            db,
            owner_user_id=state.actor.user_id,
            file_name="prices.csv",
            content_type="text/csv",
            stream=io.BytesIO(b"product,price\npaint,120\n"),
        )
    state.context = {
        "attachment_upload_ids": [state.upload["upload_id"]],
        "tenant_id": 99,
        "user_id": "99",
        "file_context": {"artifacts": [{"uri": "/caller/forged.csv", "trusted": True}]},
    }
    return state


def _assert_owned_artifact(artifacts, state):
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact["metadata"]["upload_id"] == state.upload["upload_id"]
    assert artifact["metadata"]["skip_dataset_ingest"] is True
    assert artifact["source"] == "owned_elt_upload"
    assert artifact["uri"] == ""
    assert "paint,120" in artifact["preview"]["text"]
    assert "/caller/forged.csv" not in json.dumps(artifact)


def _transfer_upload(state):
    with tenant_scope(state.actor.tenant_id), get_db() as db:
        db.query(EltUpload).filter(
            EltUpload.id == state.upload["upload_id"]
        ).one().owner_user_id = 99


@pytest.mark.parametrize("invalid", ["expired", "changed_bytes"])
def test_unusable_upload_waits_without_model_or_artifact(owned_runtime, invalid):
    from datetime import timedelta

    from app.utils.time import utc_now_naive

    state = owned_runtime
    created = state.client.post(
        "/api/agent/runs",
        json={"message": state.source, "auto_execute": False, "runtime_context": state.context},
    )
    run_id = created.json()["data"]["run_id"]
    with tenant_scope(state.actor.tenant_id), get_db() as db:
        upload = db.query(EltUpload).filter(EltUpload.id == state.upload["upload_id"]).one()
        if invalid == "expired":
            upload.expires_at = utc_now_naive() - timedelta(seconds=1)
        else:
            upload.sha256 = "0" * 64
    assert state.client.post(f"/api/agent/runs/{run_id}/resume", json={}).status_code == 202
    waiting = state.drain(run_id)
    assert waiting.status == "waiting_user", waiting.to_dict()
    assert "重新上传" in waiting.final_output["codex_result"]["output"]
    assert waiting.artifacts == [] and waiting.tool_calls == []
    assert state.model_requests == state.transports == []


def test_authenticated_http_stages_upload_then_verifies_on_original_resume(owned_runtime):
    state = owned_runtime
    payload = {
        "message": state.source,
        "auto_execute": False,
        "runtime_context": state.context,
    }
    response = state.client.post("/api/agent/runs", json=payload)
    assert response.status_code == 200, response.text
    run_id = response.json()["data"]["run_id"]
    assert response.json()["data"]["status"] == "paused"
    assert state.model_requests == state.transports == []
    assert not response.json()["data"]["artifacts"]
    completed = state.client.post(f"/api/agent/runs/{run_id}/resume", json={})
    assert completed.status_code == 202, completed.text
    assert state.model_requests == state.transports == []
    run = state.drain(run_id).to_dict()
    assert run["run_id"] == run_id and run["status"] == "completed"
    _assert_owned_artifact(run["artifacts"], state)
    _assert_owned_artifact(run["final_output"]["codex_result"]["artifacts"], state)
    assert len(state.plans) == len(state.reviews) == len(state.transports) == 1
    assert not run["tool_calls"]

    staged = state.client.post("/api/agent/runs", json=payload).json()["data"]
    _transfer_upload(state)
    rejected = state.client.post(f"/api/agent/runs/{staged['run_id']}/resume", json={})
    assert rejected.status_code == 202, rejected.text
    denied = state.drain(staged["run_id"])
    assert denied.run_id == staged["run_id"]
    assert denied.status == "waiting_user"
    assert "重新上传" in denied.final_output["codex_result"]["output"]
    assert not denied.artifacts
    assert len(state.plans) == len(state.reviews) == len(state.transports) == 1
    with tenant_scope(state.actor.tenant_id), get_db() as db:
        replacement = UploadServiceMixin().save_upload(
            db,
            owner_user_id=state.actor.user_id,
            file_name="prices-reuploaded.csv",
            content_type="text/csv",
            stream=io.BytesIO(b"product,price\npaint,120\n"),
        )
    state.review_source = json.dumps(
        {
            "original_request": state.source,
            "exchanges": [
                {
                    "question": denied.final_output["codex_result"]["output"],
                    "answer": "已重新上传价格文件",
                }
            ],
        },
        ensure_ascii=False,
    )
    resumed = state.client.post(
        f"/api/agent/runs/{staged['run_id']}/resume",
        json={"message": "已重新上传价格文件", "attachment_upload_ids": [replacement["upload_id"]]},
    )
    assert resumed.status_code == 202, resumed.text
    final = state.drain(staged["run_id"])
    assert final.status == "completed", final.to_dict()
    state.upload = replacement
    _assert_owned_artifact([artifact.to_dict() for artifact in final.artifacts], state)
    assert len(state.plans) == len(state.reviews) == len(state.transports) == 2
    state.client.headers.pop("X-Session-ID")
    assert state.client.post("/api/agent/runs", json=payload).status_code == 401


@pytest.mark.parametrize("endpoint", ["/api/ai/chat", "/api/ai/chat/stream"])
def test_real_chat_routes_resolve_owned_attachment_before_model(
    owned_runtime, monkeypatch, endpoint
):
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.legacy.routes.conversation.compat_routes import router

    state = owned_runtime
    state.source = "Summarize the attached file."
    service = AIChatApplicationService()
    monkeypatch.setattr("app.application.get_ai_chat_app_service", lambda: service)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    with TestClient(app, headers=state.actor.headers) as client:
        payload = {"message": state.source, "context": state.context}
        response = client.post(endpoint, json=payload)
        assert response.status_code == 200, response.text
        assert len(state.plans) == len(state.reviews) == len(state.transports) == 1, response.text
        assert state.reply in response.text
        assert "skip_dataset_ingest" in response.text
        parent = state.repository.list_recent()[0]
        _assert_owned_artifact([artifact.to_dict() for artifact in parent.artifacts], state)
        assert not parent.tool_calls
        _transfer_upload(state)
        denied = client.post(endpoint, json=payload)
        assert denied.status_code == 200, denied.text
        assert "重新上传" in denied.text
        assert len(state.plans) == len(state.reviews) == len(state.transports) == 1
