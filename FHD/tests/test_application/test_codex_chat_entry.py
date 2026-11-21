"""Chat rollout preserves native work and keeps continuation/approval identities."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.application.agent_runtime import chat
from app.infrastructure.codex.policy import RuntimePolicyError, RuntimeSettings


@pytest.fixture
def entry(monkeypatch):
    selected = RuntimeSettings()
    monkeypatch.setattr(chat, "runtime_settings", lambda: selected)
    execute = Mock(return_value={"ok": True, "run_id": "parent", "exit_status": "reply_completed"})
    monkeypatch.setattr("app.application.agent_runtime.gateway.run_runtime_task", execute)
    service = SimpleNamespace(_pending_workflows={}, _hydrate_pending_workflow=Mock())

    def invoke(context=None, engine="native"):
        nonlocal selected
        selected = RuntimeSettings(engine=engine)
        return chat.try_runtime_chat(
            user_id="owner",
            message="补充原任务",
            context=context or {},
            file_context={},
            service=service,
        )

    return invoke, execute, service


def test_native_default_does_not_initialize_optional_runtime(entry):
    invoke, execute, service = entry
    assert invoke({"session_id": "original"}) is None
    execute.assert_not_called()
    service._hydrate_pending_workflow.assert_not_called()


def test_rollout_keeps_native_pending_plan_in_its_original_conversation(entry):
    invoke, execute, service = entry
    service._pending_workflows["owner"] = {"runtime_context": {"session_id": "original"}}
    assert invoke({"session_id": "original"}, "codex") is None
    execute.assert_not_called()
    assert invoke({"session_id": "another"}, "codex")["runtime"] == "codex"
    execute.assert_called_once()


def test_explicit_continuation_is_not_silently_replanned_after_switch_off(entry):
    invoke, execute, _ = entry
    execute.return_value = {"ok": False, "run_id": "parent", "exit_status": "runtime_not_selected"}
    reply = invoke({"agent_runtime_run_id": "parent", "session_id": "original"})
    assert reply["success"] is False
    assert reply["data"]["error_code"] == "runtime_not_selected"
    assert execute.call_args.kwargs["run_id"] == "parent"
    assert execute.call_args.kwargs["answer_to_waiting_input"] is True
    assert reply["execution_state"] == "blocked"
    assert reply["runtime_context_update"]["agent_runtime_run_id"] == "parent"
    assert reply["runtime_context_update"]["status"] == "waiting_user"


def test_invalid_qualification_never_falls_back_or_creates_an_approval(entry):
    invoke, execute, _ = entry
    execute.side_effect = RuntimePolicyError("qualification missing")
    reply = invoke({"session_id": "original"}, "codex")
    assert reply["success"] is False
    assert reply["data"]["error_code"] == "runtime_not_qualified"
    assert reply["requires_confirmation"] is False


def test_waiting_input_and_terminal_receipts_update_same_conversation(entry):
    invoke, execute, _ = entry
    execute.return_value = {
        "ok": False,
        "run_id": "parent",
        "execution_state": "waiting_user",
        "needs_user_input": True,
        "output": "请提供日期",
    }
    waiting = invoke({"session_id": "original"}, "codex")
    assert waiting["needs_user_input"] is True
    assert waiting["requires_confirmation"] is False
    assert waiting["runtime_context_update"] == {
        "agent_runtime_run_id": "parent",
        "conversation_id": "original",
        "status": "waiting_user",
    }
    execute.return_value = {"ok": True, "run_id": "parent", "execution_state": "completed"}
    terminal = invoke({"session_id": "original", "agent_runtime_run_id": "parent"}, "codex")
    assert terminal["runtime_context_update"]["agent_runtime_run_id"] is None
    assert terminal["business_completed"] is False


def test_approval_card_targets_frozen_child_not_coordinator():
    card = {"run_id": "child", "agent_run_id": "child", "kind": "approval_pending"}
    result = {
        "run_id": "parent",
        "pending_approval": True,
        "execution_state": "waiting_user",
        "business_receipts": [{"receipt": {"pending_approval": True, "approval_card": card}}],
    }
    payload = chat.runtime_chat_payload(result, conversation_id="original")
    assert payload["run_id"] == "parent"
    assert payload["runtime_context_update"]["agent_runtime_run_id"] == "parent"
    assert payload["data"]["action"] == "approval_pending"
    assert payload["data"]["data"]["approval_card"]["run_id"] == "child"
    result["business_receipts"] = []
    assert "data" not in chat.runtime_chat_payload(result)["data"]


@pytest.mark.parametrize("state,run_id", [("waiting_user", "parent"), ("completed", None)])
def test_server_history_retains_continuation_and_terminal_clear(monkeypatch, state, run_id):
    from app.application.ai_chat.conversation_history import persist_chat_turn

    monkeypatch.setattr(
        "app.application.ai_chat.active_conversation.remember_active_conversation", Mock()
    )
    store = SimpleNamespace(save_turn=Mock(return_value=[1, 2]))
    payload = chat.runtime_chat_payload(
        {
            "run_id": "parent",
            "execution_state": state,
            "output": "reply",
            "ok": state == "completed",
        },
        conversation_id="original",
    )
    result = persist_chat_turn(
        "owner", "question", {"local_user_id": 71, "session_id": "original"}, payload, store=store
    )
    assert result["status"] == "saved"
    metadata = json.loads(store.save_turn.call_args.kwargs["messages"][1]["metadata"])
    assert metadata["ui"]["runtimeContinuation"] == {
        "runId": run_id,
        "status": state,
        "sessionId": "original",
    }
