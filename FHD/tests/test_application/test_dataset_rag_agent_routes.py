from __future__ import annotations

from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def dataset_actor(trusted_actor):
    return trusted_actor(tenant_id=7, permissions=["dataset.read", "dataset.write"])


@pytest.fixture(autouse=True)
def _explicit_gateway_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_TRUST_DATASET_ACCESS_HEADERS", "1")


def _client() -> TestClient:
    from app.fastapi_routes.knowledge_v1 import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def _patch_agent_repo(repo: InMemoryAgentRunRepository):
    return patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    )


def _configure_billing(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "tool-claims.sqlite"))
    monkeypatch.setenv("DATASET_RAG_STORE_PATH", str(tmp_path / "dataset-store.json"))
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)


def _dataset_headers(dataset_actor) -> dict[str, str]:
    return {
        **dataset_actor.headers,
        "X-User-Id": str(dataset_actor.user_id),
        "X-Dataset-Tenant-ID": "7",
        "X-Dataset-Permissions": "dataset.read,dataset.write",
    }


def _assert_mock_write_needs_readback(run, payload, *, code="result_verifier_unavailable"):
    # The mocked service supplies a receipt but persists no independently readable effect.
    assert payload["agent_status"] == run.status == "blocked"
    assert payload["success"] is False
    assert payload["error_code"] == "result_verification_inconclusive"
    assert payload["retryable"] is False and payload["reconciliation_required"] is True
    assert payload["verification_code"] == code
    receipt = run.tool_calls[0].metadata["verification"]
    assert receipt["status"] == "inconclusive" and receipt["accepted"] is False
    assert receipt["code"] == code
    assert receipt["checks"] and all(
        check["status"] == "unavailable" and not check["evidence"] for check in receipt["checks"]
    )
    assert run.tool_calls[0].output["success"] is True
    assert run.final_output.get("business_result", {}).get("success") is not True
    events = {event.event_type for event in run.events}
    assert {"tool.started", "verification.inconclusive"} <= events
    assert not {"tool.completed", "run.completed"} & events


def test_dataset_query_route_executes_dataset_rag_tool_through_agent(
    tmp_path, monkeypatch: pytest.MonkeyPatch, local_tools, dataset_actor
) -> None:
    repo = InMemoryAgentRunRepository()
    _configure_billing(monkeypatch, tmp_path)
    service = MagicMock()
    service.answer.return_value = {
        "success": True,
        "dataset_id": "platform-docs",
        "query": "agent route?",
        "answer": "Use AgentOrchestrator [1].",
        "chunks": [{"text": "Use AgentOrchestrator.", "source": "policy.pdf"}],
        "citations": [{"index": 1, "source": "policy.pdf"}],
    }

    with (
        _patch_agent_repo(repo),
        patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=service,
        ),
    ):
        response = _client().post(
            "/api/knowledge/v1/datasets/platform-docs/query",
            json={"query": "agent route?", "tenant_id": "7", "include_answer": True},
            headers=_dataset_headers(dataset_actor),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["agent_run_id"] == payload["run_id"]
    assert payload["agent_status"] == "completed"
    assert payload["answer"] == "Use AgentOrchestrator [1]."

    service.answer.assert_called_once()
    call_kwargs = service.answer.call_args.kwargs
    assert call_kwargs["dataset_id"] == "platform-docs"
    assert call_kwargs["query"] == "agent route?"
    assert call_kwargs["access_context"].tenant_id == "7"
    assert "dataset.read" in call_kwargs["access_context"].permissions

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.user_id == str(dataset_actor.user_id)
    assert run.status == "completed"
    assert run.intent == "dataset_rag_query"
    assert run.steps[0].risk == "low"
    assert run.tool_calls[0].tool_id == "dataset_rag"
    assert run.tool_calls[0].action == "query"
    assert run.tool_calls[0].permission == "dataset.read"
    assert run.tool_calls[0].cost_units == 1
    assert "tool.completed" in {event.event_type for event in run.events}


def test_identical_dataset_queries_read_fresh_results(
    tmp_path, monkeypatch, local_tools, dataset_actor
):
    repo = InMemoryAgentRunRepository()
    _configure_billing(monkeypatch, tmp_path)
    service = MagicMock()
    service.answer.side_effect = [
        {"success": True, "answer": "first", "chunks": [], "citations": []},
        {"success": True, "answer": "updated", "chunks": [], "citations": []},
    ]
    with (
        _patch_agent_repo(repo),
        patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=service,
        ),
    ):
        client = _client()
        args = {
            "json": {"query": "same question", "tenant_id": "7"},
            "headers": _dataset_headers(dataset_actor),
        }
        first = client.post("/api/knowledge/v1/datasets/platform-docs/query", **args).json()
        second = client.post("/api/knowledge/v1/datasets/platform-docs/query", **args).json()
    assert (first["answer"], second["answer"]) == ("first", "updated")
    assert first["run_id"] != second["run_id"]
    assert service.answer.call_count == 2


def test_multi_query_route_runs_read_only_tool_across_datasets(
    tmp_path, monkeypatch: pytest.MonkeyPatch, local_tools, dataset_actor
) -> None:
    repo = InMemoryAgentRunRepository()
    _configure_billing(monkeypatch, tmp_path)
    service = MagicMock()
    service.multi_answer.return_value = {
        "success": True,
        "dataset_ids": ["kb-a", "kb-b"],
        "query": "跨库问题",
        "answer": "跨库答案 [1].",
        "chunks": [{"text": "跨库答案", "source": "policy.pdf", "dataset_id": "kb-b"}],
        "citations": [{"index": 1, "source": "policy.pdf"}],
    }

    with (
        _patch_agent_repo(repo),
        patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=service,
        ),
    ):
        response = _client().post(
            "/api/knowledge/v1/datasets/multi-query",
            json={
                "dataset_ids": ["kb-a", "kb-b"],
                "query": "跨库问题",
                "tenant_id": "7",
                "include_answer": True,
            },
            headers=_dataset_headers(dataset_actor),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True

    call_kwargs = service.multi_answer.call_args.kwargs
    assert call_kwargs["dataset_ids"] == ["kb-a", "kb-b"]
    assert call_kwargs["query"] == "跨库问题"

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.intent == "dataset_rag_multi_query"
    assert run.steps[0].risk == "low"
    assert run.tool_calls[0].action == "multi_query"
    assert run.tool_calls[0].permission == "dataset.read"


def test_refresh_route_runs_write_tool_on_recorded_source(
    tmp_path, monkeypatch: pytest.MonkeyPatch, local_tools, dataset_actor
) -> None:
    repo = InMemoryAgentRunRepository()
    _configure_billing(monkeypatch, tmp_path)
    service = MagicMock()
    service.refresh_document.return_value = {
        "success": True,
        "dataset_id": "platform-docs",
        "document_id": "doc_1",
        "changed": True,
        "previous_version": 1,
        "document": {"document_id": "doc_1", "version": 2},
    }

    with (
        _patch_agent_repo(repo),
        patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=service,
        ),
    ):
        response = _client().post(
            "/api/knowledge/v1/datasets/platform-docs/documents/doc_1/refresh",
            headers=_dataset_headers(dataset_actor),
        )

    assert response.status_code == 202
    assert response.json()["changed"] is True
    service.refresh_document.assert_called_once()
    call_kwargs = service.refresh_document.call_args.kwargs
    assert call_kwargs["dataset_id"] == "platform-docs"
    assert call_kwargs["document_id"] == "doc_1"

    run = repo.get(response.json()["run_id"])
    assert run is not None
    _assert_mock_write_needs_readback(run, response.json())
    assert run.intent == "dataset_rag_refresh_document"
    assert run.tool_calls[0].action == "refresh_document"
    assert run.tool_calls[0].permission == "dataset.write"


def test_batch_refresh_route_syncs_visible_sources(
    tmp_path, monkeypatch: pytest.MonkeyPatch, local_tools, dataset_actor
) -> None:
    repo = InMemoryAgentRunRepository()
    _configure_billing(monkeypatch, tmp_path)
    service = MagicMock()
    service.refresh_documents.return_value = {
        "success": True,
        "dataset_id": "platform-docs",
        "total": 2,
        "processed": 2,
        "changed": 1,
        "unchanged": 1,
        "failed": 0,
        "skipped": 0,
        "truncated": False,
        "documents": [],
    }

    with (
        _patch_agent_repo(repo),
        patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=service,
        ),
    ):
        response = _client().post(
            "/api/knowledge/v1/datasets/platform-docs/documents/refresh?limit=500",
            headers=_dataset_headers(dataset_actor),
        )

    assert response.status_code == 202
    assert response.json()["changed"] == 1
    service.refresh_documents.assert_called_once()
    call_kwargs = service.refresh_documents.call_args.kwargs
    assert call_kwargs["dataset_id"] == "platform-docs"
    assert call_kwargs["limit"] == 200

    run = repo.get(response.json()["run_id"])
    assert run is not None
    _assert_mock_write_needs_readback(run, response.json())
    assert run.tool_calls[0].action == "refresh_documents"
    assert run.tool_calls[0].permission == "dataset.write"


def test_rebuild_explicit_idempotency_key_replays_and_rejects_changed_input(
    tmp_path, monkeypatch, local_tools, dataset_actor
):
    from app.application.agent_orchestrator.tool_permission import (
        clear_idempotent_replay_for_tests,
        drop_process_idempotency_memory,
    )

    repo = InMemoryAgentRunRepository()
    _configure_billing(monkeypatch, tmp_path)
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "claims.sqlite"))
    clear_idempotent_replay_for_tests()
    service = MagicMock()
    _configure_service_for_action(service, "rebuild_index")
    headers = {**_dataset_headers(dataset_actor), "Idempotency-Key": "same-attempt"}
    with (
        _patch_agent_repo(repo),
        patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=service,
        ),
    ):
        client = _client()
        path = "/api/knowledge/v1/datasets/platform-docs/index/rebuild"
        first = client.post(path, json={"background": True}, headers=headers)
        drop_process_idempotency_memory()
        repeat = client.post(path, json={"background": True}, headers=headers)
        conflict = client.post(path, json={"background": True, "max_attempts": 2}, headers=headers)
    assert first.status_code == 202
    assert repeat.status_code == 409
    assert first.json()["job"]["job_id"] == repeat.json()["job"]["job_id"]
    assert first.json()["run_id"] == repeat.json()["run_id"]
    assert repeat.json()["success"] is False
    assert repeat.json()["outcome"] == "unknown"
    assert repeat.json()["retryable"] is False
    assert repeat.json()["reconciliation_required"] is True
    _assert_mock_write_needs_readback(
        repo.get(first.json()["run_id"]),
        first.json(),
        code="result_rebuild_baseline_unavailable",
    )
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "idempotency_conflict"
    assert service.start_rebuild_index.call_count == 1


def _configure_service_for_action(service: MagicMock, action: str) -> None:
    if action == "ingest_document":
        service.ingest_document.return_value = {
            "success": True,
            "dataset_id": "platform-docs",
            "document": {"document_id": "doc_1", "source": "policy.pdf"},
            "chunk_count": 1,
        }
    elif action == "diff_versions":
        service.diff_versions.return_value = {
            "success": True,
            "dataset_id": "platform-docs",
            "source": "policy.pdf",
            "changed": True,
            "diff": ["--- v1", "+++ v2"],
        }
    elif action == "rollback_version":
        service.rollback_document_version.return_value = {
            "success": True,
            "dataset_id": "platform-docs",
            "document": {"document_id": "doc_rollback"},
            "chunk_count": 1,
            "rolled_back_from": {"document_id": "doc_1", "version": 1},
        }
    elif action == "rebuild_index":
        service.start_rebuild_index.return_value = {
            "success": True,
            "dataset_id": "platform-docs",
            "job": {"job_id": "rag_rebuild_1", "status": "queued"},
            "background": True,
        }
    elif action == "cancel_rebuild":
        service.cancel_rebuild_job.return_value = {
            "success": True,
            "dataset_id": "platform-docs",
            "job_id": "rag_rebuild_1",
            "job": {"job_id": "rag_rebuild_1", "status": "cancelled"},
        }
    elif action == "delete_document":
        service.delete_document.return_value = {
            "success": True,
            "dataset_id": "platform-docs",
            "document_id": "doc_1",
            "deleted_chunks": 1,
        }


@pytest.mark.parametrize(
    ("action", "request_factory", "service_call", "risk", "permission", "cost_units"),
    [
        (
            "ingest_document",
            lambda client, dataset_actor: client.post(
                "/api/knowledge/v1/datasets/platform-docs/documents",
                json={
                    "source": "policy.pdf",
                    "text": "Use AgentOrchestrator.",
                    "tenant_id": "7",
                },
                headers=_dataset_headers(dataset_actor),
            ),
            lambda service: service.ingest_document.call_args.kwargs,
            "medium",
            "dataset.write",
            2,
        ),
        (
            "diff_versions",
            lambda client, dataset_actor: client.post(
                "/api/knowledge/v1/datasets/platform-docs/versions/diff",
                json={
                    "source": "policy.pdf",
                    "tenant_id": "7",
                    "from_version": "v1",
                    "to_version": "latest",
                },
                headers=_dataset_headers(dataset_actor),
            ),
            lambda service: service.diff_versions.call_args.kwargs,
            "low",
            "dataset.read",
            1,
        ),
        (
            "rollback_version",
            lambda client, dataset_actor: client.post(
                "/api/knowledge/v1/datasets/platform-docs/versions/rollback",
                json={"source": "policy.pdf", "tenant_id": "7", "target_version": "v1"},
                headers=_dataset_headers(dataset_actor),
            ),
            lambda service: service.rollback_document_version.call_args.kwargs,
            "high",
            "dataset.write",
            2,
        ),
        (
            "rebuild_index",
            lambda client, dataset_actor: client.post(
                "/api/knowledge/v1/datasets/platform-docs/index/rebuild",
                json={"tenant_id": "7", "background": True},
                headers=_dataset_headers(dataset_actor),
            ),
            lambda service: service.start_rebuild_index.call_args.kwargs,
            "medium",
            "dataset.write",
            2,
        ),
        (
            "cancel_rebuild",
            lambda client, dataset_actor: client.post(
                "/api/knowledge/v1/datasets/platform-docs/index/rebuild/rag_rebuild_1/cancel",
                headers=_dataset_headers(dataset_actor),
            ),
            lambda service: service.cancel_rebuild_job.call_args.kwargs,
            "medium",
            "dataset.write",
            2,
        ),
        (
            "delete_document",
            lambda client, dataset_actor: client.delete(
                "/api/knowledge/v1/datasets/platform-docs/documents/doc_1",
                headers=_dataset_headers(dataset_actor),
            ),
            lambda service: service.delete_document.call_args.kwargs,
            "high",
            "dataset.write",
            2,
        ),
    ],
)
def test_dataset_mutation_routes_execute_dataset_rag_tools_through_agent(
    action: str,
    request_factory: Callable[[TestClient, object], object],
    service_call: Callable[[MagicMock], dict[str, object]],
    risk: str,
    permission: str,
    cost_units: int,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    local_tools,
    dataset_actor,
) -> None:
    repo = InMemoryAgentRunRepository()
    _configure_billing(monkeypatch, tmp_path)
    service = MagicMock()
    _configure_service_for_action(service, action)

    with (
        _patch_agent_repo(repo),
        patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=service,
        ),
    ):
        response = request_factory(_client(), dataset_actor)

    assert response.status_code == (200 if risk == "low" else 202)
    payload = response.json()
    assert payload["success"] is (risk == "low")
    assert payload["agent_run_id"] == payload["run_id"]
    assert payload["agent_status"] == ("completed" if risk == "low" else "blocked")

    call_kwargs = service_call(service)
    assert call_kwargs["access_context"].tenant_id == "7"
    assert permission in call_kwargs["access_context"].permissions

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.user_id == str(dataset_actor.user_id)
    if risk == "low":
        assert run.status == "completed"
    else:
        _assert_mock_write_needs_readback(
            run,
            payload,
            code={
                "ingest_document": "result_source_unavailable",
                "rollback_version": "result_source_unavailable",
                "rebuild_index": "result_rebuild_baseline_unavailable",
                "cancel_rebuild": "result_rebuild_baseline_unavailable",
            }.get(action, "result_verifier_unavailable"),
        )
    assert run.intent == f"dataset_rag_{action}"
    assert run.steps[0].risk == risk
    assert run.tool_calls[0].tool_id == "dataset_rag"
    assert run.tool_calls[0].action == action
    assert run.tool_calls[0].permission == permission
    assert run.tool_calls[0].cost_units == cost_units
    if risk != "low":
        assert {"step.waiting_user", "step.approved", "verification.inconclusive"} <= {
            event.event_type for event in run.events
        }
