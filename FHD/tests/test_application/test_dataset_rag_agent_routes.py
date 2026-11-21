"""Dataset reads and writes use the same bound actor and durable task contract."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.fastapi_routes.knowledge_v1 import router
from app.fastapi_routes.tools_execute import router as tools_router
from app.infrastructure.document_parsing.object_store import FetchedObject
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def setup(tmp_path, monkeypatch, local_tools):
    repo = InMemoryAgentRunRepository()
    service = Mock()
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository", lambda: repo
    )
    monkeypatch.setattr(
        "app.application.dataset_rag_app_service.get_dataset_rag_app_service", lambda: service
    )
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    app = FastAPI()
    app.include_router(router)
    app.include_router(tools_router)
    return repo, service, app


@pytest.mark.parametrize(
    "path,body,action,method,result",
    [
        (
            "/datasets/docs/query",
            {"query": "policy?", "include_answer": True},
            "query",
            "answer",
            {"success": True, "answer": "Use the approved path.", "chunks": [], "citations": []},
        ),
        (
            "/datasets/multi-query",
            {"dataset_ids": ["a", "b"], "query": "policy?"},
            "multi_query",
            "multi_answer",
            {"success": True, "answer": "Shared policy.", "chunks": [], "citations": []},
        ),
        (
            "/datasets/docs/versions/diff",
            {"source": "policy.txt", "from_version": "v1", "to_version": "v2"},
            "diff_versions",
            "diff_versions",
            {"success": True, "diff": ["+ new policy"], "added_lines": ["new policy"]},
        ),
    ],
)
def test_dataset_reads_use_bound_session_acl(
    setup, trusted_actor, path, body, action, method, result
):
    repo, service, app = setup
    actor = trusted_actor(user_id=7, permissions=["dataset.read"])
    getattr(service, method).return_value = result
    with TestClient(
        app, headers={**actor.headers, "X-Dataset-Admin": "true", "X-Dataset-Tenant-ID": "999"}
    ) as client:
        response = client.post("/api/knowledge/v1" + path, json=body)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["success"] is True and payload["execution_state"] == "completed"
    call = getattr(service, method).call_args.kwargs
    assert call["access_context"].actor_id == "7"
    assert call["access_context"].tenant_id == "7"
    assert call["access_context"].permissions == frozenset({"dataset.read"})
    assert call["access_context"].is_admin is False
    run = repo.get(payload["run_id"])
    assert run.user_id == "7"
    assert run.tool_calls[0].tool_id == "dataset_rag" and run.tool_calls[0].action == action
    getattr(service, method).assert_called_once()


def test_identical_dataset_queries_read_fresh_results(setup, trusted_actor):
    _, service, app = setup
    actor = trusted_actor(user_id=7, permissions=["dataset.read"])
    service.answer.side_effect = [
        {"success": True, "answer": "first", "chunks": [], "citations": []},
        {"success": True, "answer": "updated", "chunks": [], "citations": []},
    ]
    with TestClient(app, headers=actor.headers) as client:
        first = client.post(
            "/api/knowledge/v1/datasets/docs/query", json={"query": "same question"}
        ).json()
        second = client.post(
            "/api/knowledge/v1/datasets/docs/query", json={"query": "same question"}
        ).json()
    assert (first["answer"], second["answer"]) == ("first", "updated")
    assert first["run_id"] != second["run_id"] and service.answer.call_count == 2


def test_dataset_write_conflict_does_not_create_another_approval(setup, trusted_actor):
    repo, service, app = setup
    actor = trusted_actor(user_id=7, permissions=["dataset.write"])
    with TestClient(app, headers={**actor.headers, "Idempotency-Key": "dataset-rebuild"}) as client:
        first = client.post(
            "/api/knowledge/v1/datasets/docs/index/rebuild", json={"background": True}
        )
        assert first.status_code == 202, first.text
        receipt = first.json()
        run = repo.get(receipt["run_id"])
        replay = client.post(
            "/api/tools/execute",
            json={
                "tool_id": "dataset_rag",
                "action": "rebuild_index",
                "params": run.steps[0].params,
            },
        )
        conflict = client.post(
            "/api/knowledge/v1/datasets/docs/index/rebuild",
            json={"background": True, "max_attempts": 2},
        )
    assert (
        replay.status_code == 202
        and replay.json()["approval_request_id"] == receipt["approval_request_id"]
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error_code"] == "task_idempotency_conflict"
    assert service.mock_calls == []


def test_dataset_headers_cannot_authorize_missing_session(setup):
    _, service, app = setup
    with TestClient(app) as client:
        response = client.post(
            "/api/knowledge/v1/datasets/docs/query",
            json={"query": "secret"},
            headers={
                "X-User-Id": "7",
                "X-Dataset-Tenant-ID": "7",
                "X-Dataset-Permissions": "dataset.read,dataset.admin",
            },
        )
    assert response.status_code == 401
    assert service.mock_calls == []


@pytest.fixture(params=["multipart", "s3"])
def document_source(request, tmp_path, monkeypatch):
    upload_root = tmp_path / "uploads"
    monkeypatch.setattr("app.utils.path_io.upload_helpers.get_upload_dir", lambda: upload_root)
    fetch = Mock()
    monkeypatch.setattr("app.infrastructure.document_parsing.object_store.fetch_object", fetch)

    def post(client, content=b"private document"):
        if request.param == "multipart":
            return client.post(
                "/api/knowledge/v1/datasets/docs/documents/upload",
                files={"file": ("document.txt", content)},
            )
        fetch.return_value = FetchedObject(
            bucket="kb", key="document.txt", filename="document.txt", data=content
        )
        return client.post(
            "/api/knowledge/v1/datasets/docs/documents", json={"s3_uri": "s3://kb/document.txt"}
        )

    return post, upload_root, fetch


def test_document_retry_preserves_task_approval_and_frozen_input(
    setup, trusted_actor, document_source
):
    repo, service, app = setup
    post, upload_root, _ = document_source
    actor = trusted_actor(user_id=7, permissions=["dataset.write"])
    with TestClient(
        app, headers={**actor.headers, "Idempotency-Key": "knowledge-import"}
    ) as client:
        first = post(client)
        assert first.status_code == 202, first.text
        receipt = first.json()
        run = repo.get(receipt["run_id"])
        original_params = dict(run.steps[0].params)
        staged_path = Path(original_params["file_path"])
        assert staged_path.read_bytes() == b"private document"
        assert staged_path.name == hashlib.sha256(b"private document").hexdigest() + ".txt"
        assert staged_path.is_relative_to(upload_root / "capability-inputs" / "knowledge")

        retry = post(client)
        assert retry.status_code == 202, retry.text
        replay = client.post(
            "/api/tools/execute",
            json={"tool_id": "dataset_rag", "action": "ingest_document", "params": original_params},
        )
        assert replay.status_code == 202, replay.text
        for response in (retry, replay):
            result = response.json()
            for key in ("run_id", "task_id", "approval_request_id"):
                assert result[key] == receipt[key]
            assert result["success"] is False

        changed = post(client, content=b"changed document")
        assert changed.status_code == 409, changed.text
        assert changed.json()["error_code"] == "task_idempotency_conflict"

    assert repo.get(receipt["run_id"]).steps[0].params == original_params
    assert staged_path.read_bytes() == b"private document"
    assert service.mock_calls == []


def test_document_staging_and_task_ownership_follow_real_account(
    setup, trusted_actor, document_source
):
    repo, service, app = setup
    post, _, _ = document_source
    actors = [
        trusted_actor(user_id=7, tenant_id=7, permissions=["dataset.write"]),
        trusted_actor(user_id=8, tenant_id=8, permissions=["dataset.write"]),
    ]
    receipts = []
    paths = []
    for actor in actors:
        with TestClient(
            app,
            headers={
                **actor.headers,
                "Idempotency-Key": "shared-request-key",
                "X-User-Id": "7",
                "X-Dataset-Tenant-ID": "7",
            },
        ) as client:
            response = post(client)
        assert response.status_code == 202, response.text
        receipt = response.json()
        run = repo.get(receipt["run_id"])
        assert run.user_id == str(actor.user_id)
        receipts.append(receipt)
        paths.append(Path(run.steps[0].params["file_path"]))
    assert paths[0] != paths[1]
    assert paths[0].name == paths[1].name
    assert paths[0].read_bytes() == paths[1].read_bytes() == b"private document"
    assert receipts[0]["task_id"] != receipts[1]["task_id"]
    assert receipts[0]["approval_request_id"] != receipts[1]["approval_request_id"]
    assert service.mock_calls == []


def test_unauthenticated_document_request_cannot_fetch_or_stage_input(setup, document_source):
    _, service, app = setup
    post, upload_root, fetch = document_source
    with TestClient(
        app, headers={"X-User-Id": "7", "X-Dataset-Admin": "true", "Idempotency-Key": "forged"}
    ) as client:
        response = post(client)
    assert response.status_code == 401
    assert not upload_root.exists()
    fetch.assert_not_called()
    assert service.mock_calls == []
