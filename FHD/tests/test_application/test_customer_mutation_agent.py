from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.application.agent_orchestrator import (
    AgentOrchestrator,
    InMemoryAgentRunRepository,
)
from app.application.customer_mutation_agent import (
    classify_customer_delete_intent,
    try_start_customer_mutation_agent_run,
)


@pytest.fixture(autouse=True)
def _agent_usage_ledger(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)


def _customer_context() -> dict:
    return {
        "recent_messages": [
            {"role": "user", "content": "当前有哪些客户"},
            {"role": "ai", "content": "当前共有 1 位客户：候雪梅"},
            {"role": "user", "content": "去掉候雪梅"},
        ],
        "tool_execution_profile": "normal",
    }


def test_customer_delete_intent_uses_recent_customer_context() -> None:
    assert (
        classify_customer_delete_intent("去掉候雪梅", runtime_context=_customer_context())
        == "候雪梅"
    )
    assert classify_customer_delete_intent("去掉这句话", runtime_context={}) == ""


def test_customer_delete_intent_preserves_quoted_name_with_bounded_pattern() -> None:
    assert (
        classify_customer_delete_intent("删除客户“候雪梅”", runtime_context=_customer_context())
        == "候雪梅"
    )


def test_customer_delete_waits_then_executes_with_tool_receipt() -> None:
    repo = InMemoryAgentRunRepository()
    service = MagicMock()
    service.get_all.return_value = {
        "success": True,
        "data": [{"id": 7, "customer_name": "候雪梅", "contact_phone": "13900000000"}],
        "total": 1,
    }
    service.delete.return_value = {
        "success": True,
        "message": "客户删除成功",
        "deleted_count": 1,
    }

    with (
        patch("app.application.get_customer_app_service", return_value=service),
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
    ):
        payload = try_start_customer_mutation_agent_run(
            "去掉候雪梅",
            runtime_context=_customer_context(),
            user_id="u1",
            source="normal",
        )
        assert payload is not None
        run_id = payload["run_id"]
        waiting = repo.get(run_id)
        assert waiting is not None
        assert waiting.status == "waiting_user"
        assert [step.status for step in waiting.steps] == ["completed", "waiting_user"]
        assert [call.action for call in waiting.tool_calls] == ["query"]
        assert payload["data"]["action"] == "workflow_confirmation_required"
        assert "当前尚未删除任何数据" in payload["response"]

        completed = AgentOrchestrator(repository=repo).continue_run(
            run_id,
            approved_by="u1",
        )

    assert completed is not None
    assert completed.status == "completed"
    assert [call.action for call in completed.tool_calls] == ["query", "delete"]
    assert completed.tool_calls[-1].output["deleted_count"] == 1
    assert completed.metadata["tool_call_count"] == 2
    service.delete.assert_called_once_with(7, force=False)
    assert {"step.waiting_user", "step.approved", "tool.completed", "run.completed"} <= {
        event.event_type for event in completed.events
    }


def test_customer_delete_not_found_is_verified_and_does_not_write() -> None:
    repo = InMemoryAgentRunRepository()
    service = MagicMock()
    service.get_all.return_value = {"success": True, "data": [], "total": 0}

    with (
        patch("app.application.get_customer_app_service", return_value=service),
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
    ):
        payload = try_start_customer_mutation_agent_run(
            "删除客户候雪梅",
            runtime_context={},
            user_id="u1",
            source="normal",
        )

    assert payload is not None
    assert payload["execution_receipt"]["executed"] is False
    assert payload["execution_receipt"]["verified"] is True
    assert "未删除任何数据" in payload["response"]
    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.status == "completed"
    assert [call.action for call in run.tool_calls] == ["query"]
    service.delete.assert_not_called()
