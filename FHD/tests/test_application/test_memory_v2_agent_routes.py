from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository


def _client() -> TestClient:
    from app.fastapi_routes.domains.misc.routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def _patch_agent_repo(repo: InMemoryAgentRunRepository):
    return patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    )


def _configure_runtime(monkeypatch, tmp_path) -> None:
    import app.services.user_memory_service as memory_mod

    memory_dir = tmp_path / "memory"
    monkeypatch.setattr(memory_mod, "MEMORY_DIR", str(memory_dir))
    monkeypatch.setattr(memory_mod, "JSON_MEMORY_PATH", str(memory_dir / "memory_store.json"))
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    memory_mod.reset_user_memory_service()


def _assert_memory_run(
    repo: InMemoryAgentRunRepository,
    run_id: str,
    *,
    action: str,
    risk: str,
) -> None:
    run = repo.get(run_id)
    assert run is not None
    assert run.user_id == "u-memory"
    assert run.status == "completed"
    assert run.intent == f"memory_v2_{action}"
    assert run.steps[0].risk == risk
    assert run.tool_calls[0].tool_id == "memory_v2"
    assert run.tool_calls[0].action == action
    assert run.tool_calls[0].permission == "memory_v2.write"
    assert run.tool_calls[0].cost_units == 2
    assert {"step.waiting_user", "step.approved", "tool.completed"} <= {
        event.event_type for event in run.events
    }


def test_memory_v2_lifecycle_routes_execute_through_agent(
    tmp_path,
    monkeypatch,
) -> None:
    import app.services.user_memory_service as memory_mod

    repo = InMemoryAgentRunRepository()
    _configure_runtime(monkeypatch, tmp_path)

    try:
        with _patch_agent_repo(repo):
            client = _client()
            created = client.post(
                "/memory/v2/candidates",
                json={
                    "user_id": "u-memory",
                    "memory_type": "preference",
                    "key": "default_customer",
                    "value": "七彩乐园",
                    "confidence": 0.8,
                    "source": "settings_ui",
                    "evidence": [{"message": "总是给七彩乐园开单"}],
                },
                headers={"X-User-Id": "u-memory"},
            )
            assert created.status_code == 200
            created_body = created.json()
            assert created_body["success"] is True
            assert created_body["agent_run_id"] == created_body["run_id"]
            assert created_body["agent_status"] == "completed"
            candidate = created_body["candidate"]
            memory_id = candidate["memory_id"]
            _assert_memory_run(repo, created_body["run_id"], action="propose_candidate", risk="medium")

            confirmed = client.post(
                f"/memory/v2/{memory_id}/confirm",
                json={"user_id": "u-memory"},
                headers={"X-User-Id": "u-memory"},
            )
            assert confirmed.status_code == 200
            confirmed_body = confirmed.json()
            assert confirmed_body["memory"]["status"] == "active"
            _assert_memory_run(repo, confirmed_body["run_id"], action="confirm", risk="high")

            svc = memory_mod.get_user_memory_service()
            assert svc.get_preference("u-memory", "default_customer") == "七彩乐园"

            corrected = client.patch(
                f"/memory/v2/{memory_id}",
                json={
                    "user_id": "u-memory",
                    "key": "favorite_customer",
                    "value": "彩虹乐园",
                    "reason": "用户纠正名称",
                },
                headers={"X-User-Id": "u-memory"},
            )
            assert corrected.status_code == 200
            corrected_body = corrected.json()
            assert corrected_body["memory"]["key"] == "favorite_customer"
            _assert_memory_run(repo, corrected_body["run_id"], action="correct", risk="high")
            assert svc.get_preference("u-memory", "default_customer") is None
            assert svc.get_preference("u-memory", "favorite_customer") == "彩虹乐园"

            deleted = client.delete(
                f"/memory/v2/{memory_id}",
                params={"user_id": "u-memory", "reason": "用户删除"},
                headers={"X-User-Id": "u-memory"},
            )
            assert deleted.status_code == 200
            deleted_body = deleted.json()
            assert deleted_body["memory"]["status"] == "deleted"
            _assert_memory_run(repo, deleted_body["run_id"], action="delete", risk="high")
            assert svc.get_preference("u-memory", "favorite_customer") is None
    finally:
        memory_mod.reset_user_memory_service()


def test_memory_v2_blocked_source_confirm_route_records_failed_agent_run(
    tmp_path,
    monkeypatch,
) -> None:
    import app.services.user_memory_service as memory_mod

    repo = InMemoryAgentRunRepository()
    _configure_runtime(monkeypatch, tmp_path)

    try:
        with _patch_agent_repo(repo):
            client = _client()
            created = client.post(
                "/memory/v2/candidates",
                json={
                    "user_id": "u-memory",
                    "memory_type": "preference",
                    "key": "favorite_customer",
                    "value": "污染客户",
                    "confidence": 0.95,
                    "source": "llm_guess",
                },
                headers={"X-User-Id": "u-memory"},
            )
            assert created.status_code == 200
            candidate = created.json()["candidate"]
            assert candidate["status"] == "rejected"
            assert candidate["source_policy"] == "blocked"

            confirm = client.post(
                f"/memory/v2/{candidate['memory_id']}/confirm",
                json={"user_id": "u-memory"},
                headers={"X-User-Id": "u-memory"},
            )
            assert confirm.status_code == 404
            body = confirm.json()
            assert body["success"] is False
            assert body["agent_run_id"] == body["run_id"]
            run = repo.get(body["run_id"])
            assert run is not None
            assert run.status == "failed"
            assert run.intent == "memory_v2_confirm"
            assert run.tool_calls[0].tool_id == "memory_v2"
            assert run.tool_calls[0].action == "confirm"
            assert run.tool_calls[0].permission == "memory_v2.write"
            assert "tool.failed" in {event.event_type for event in run.events}
    finally:
        memory_mod.reset_user_memory_service()
