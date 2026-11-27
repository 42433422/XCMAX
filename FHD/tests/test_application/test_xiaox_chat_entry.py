"""Fixed chat admission preserves historical work and continuation identities."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.application.agent_runtime import chat
from app.infrastructure.xiaox.policy import RuntimePolicyError


@pytest.fixture
def entry(monkeypatch):
    execute = Mock(return_value={"ok": True, "run_id": "parent", "exit_status": "reply_completed"})
    monkeypatch.setattr("app.application.agent_runtime.gateway.run_runtime_task", execute)
    service = SimpleNamespace(_pending_workflows={}, _hydrate_pending_workflow=Mock())

    def invoke(context=None):
        return chat.run_runtime_chat(
            user_id="owner",
            message="补充原任务",
            context=context or {},
            file_context={},
        )

    return invoke, execute, service


def test_new_chat_uses_fixed_executor_and_host_goal_admission(entry):
    invoke, execute, service = entry
    assert invoke({"session_id": "original"})["runtime"] == "xiaox"
    execute.assert_called_once()
    assert execute.call_args.kwargs["completion_mode"] == "auto"
    assert "admit_goal" not in execute.call_args.kwargs
    assert "settings" not in execute.call_args.kwargs


def test_new_chat_is_queued_while_a_resume_keeps_its_binding(entry):
    invoke, execute, _ = entry
    invoke({"session_id": "original"})
    assert execute.call_args.kwargs["start_queued"] is True
    invoke({"session_id": "original", "agent_runtime_run_id": "parent"})
    assert execute.call_args.kwargs["start_queued"] is False


def test_queued_result_keeps_the_run_pointer_for_event_following(entry):
    invoke, execute, _ = entry
    execute.return_value = {
        "ok": False,
        "run_id": "parent",
        "execution_state": "queued",
        "resume_required": True,
        "output": "任务已受理，正在等待后台执行。",
    }
    payload = invoke({"session_id": "original"})
    assert payload["execution_state"] == "queued"
    assert payload["response"] == "任务已受理，正在等待后台执行。"
    assert payload["requires_confirmation"] is False
    assert payload["runtime_context_update"] == {
        "agent_runtime_run_id": "parent",
        "conversation_id": "original",
        "status": "queued",
    }


def test_retired_pending_plan_cannot_select_another_executor(entry):
    invoke, execute, service = entry
    service._pending_workflows["owner"] = {"runtime_context": {"session_id": "original"}}
    assert invoke({"session_id": "original"})["runtime"] == "xiaox"
    execute.assert_called_once()
    service._hydrate_pending_workflow.assert_not_called()


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
    reply = invoke({"session_id": "original"})
    assert reply["success"] is False
    assert reply["data"]["error_code"] == "runtime_not_qualified"
    assert reply["requires_confirmation"] is False


@pytest.mark.parametrize(
    "code",
    [
        "runtime_login_required",
        "runtime_account_model_required",
        "runtime_configuration_required",
        "runtime_qualification_unavailable",
        "runtime_storage_invalid",
    ],
)
@pytest.mark.parametrize("resume", [False, True])
def test_setup_failure_keeps_safe_specific_error_and_original_run(entry, code, resume):
    from app.application.agent_runtime.configuration import (
        RuntimeSetupError,
        public_runtime_failure,
    )

    invoke, execute, _ = entry
    original = RuntimeSetupError(code, "PRIVATE diagnostic must never reach the chat")
    execute.side_effect = original
    context = {"session_id": "original"}
    if resume:
        context["agent_runtime_run_id"] = "original-run"
    reply = invoke(context)
    assert reply["success"] is False
    assert reply["execution_state"] == "blocked"
    assert reply["data"]["error_code"] == code
    assert reply["response"] == public_runtime_failure(original)["message"]
    assert "PRIVATE diagnostic" not in str(reply)
    assert reply["requires_confirmation"] is False
    assert reply["data"]["failure_stage"] == "runtime_setup"
    assert reply["runtime_context_update"]["agent_runtime_run_id"] == (
        "original-run" if resume else None
    )
    assert execute.call_count == 1


def test_waiting_input_and_terminal_receipts_update_same_conversation(entry):
    invoke, execute, _ = entry
    execute.return_value = {
        "ok": False,
        "run_id": "parent",
        "execution_state": "waiting_user",
        "needs_user_input": True,
        "output": "请提供日期",
    }
    waiting = invoke({"session_id": "original"})
    assert waiting["needs_user_input"] is True
    assert waiting["requires_confirmation"] is False
    assert waiting["runtime_context_update"] == {
        "agent_runtime_run_id": "parent",
        "conversation_id": "original",
        "status": "waiting_user",
    }
    execute.return_value = {"ok": True, "run_id": "parent", "execution_state": "completed"}
    terminal = invoke({"session_id": "original", "agent_runtime_run_id": "parent"})
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


@pytest.mark.parametrize("mode", ["auto", "business", "reply"])
def test_unverified_candidate_is_not_streamed_but_progress_is(monkeypatch, mode):
    delta, note, tool, activity = Mock(), Mock(), Mock(), Mock()
    monkeypatch.setattr("app.infrastructure.chat_stream_lifetime.publish_stream_delta", delta)
    monkeypatch.setattr("app.infrastructure.chat_stream_lifetime.publish_stream_note", note)
    monkeypatch.setattr("app.infrastructure.chat_stream_lifetime.publish_stream_tool_record", tool)
    monkeypatch.setattr(
        "app.infrastructure.chat_stream_lifetime.publish_stream_model_activity", activity
    )
    chat.stream_runtime_event(
        {
            "method": "item/agentMessage/delta",
            "runtime_goal_mode": mode,
            "payload": {"delta": "private-candidate"},
        }
    )
    delta.assert_not_called()
    chat.stream_runtime_event(
        {
            "method": "item/started",
            "payload": {"item": {"type": "mcpToolCall"}},
        }
    )
    tool.assert_called_once_with(
        {
            "phase": "progress",
            "node_id": "",
            "tool_id": "",
            "action": "",
            "label": "正在通过授权工具处理任务…",
        }
    )
    note.assert_not_called()
    chat.stream_runtime_event(
        {"method": "turn/started", "payload": {"turn": {"status": "inProgress"}}}
    )
    activity.assert_called_once()


@pytest.mark.parametrize(
    "result_state",
    [
        {"execution_state": "unknown"},
        {"execution_state": "unknown", "reconciliation_required": True},
        {"execution_state": "blocked", "exit_status": "reconciliation_required"},
        {
            "execution_state": "waiting_user",
            "resume_required": True,
            "reconciliation_required": True,
        },
    ],
)
def test_reconciliation_preserves_receipt_without_a_continuation(result_state):
    result = chat.runtime_chat_payload(
        {
            "run_id": "original",
            **result_state,
        },
        conversation_id="session",
    )
    assert result["run_id"] == result["data"]["run_id"] == "original"
    assert result["requires_reconciliation"] is True
    assert result["runtime_context_update"] == {
        "agent_runtime_run_id": None,
        "status": "reconciliation_required",
        "conversation_id": "session",
    }
    assert result["success"] is False


def test_incomplete_retryable_goal_keeps_chat_on_original_task():
    result = chat.runtime_chat_payload(
        {
            "run_id": "original",
            "execution_state": "blocked",
            "exit_status": "goal_verification_required",
            "retryable": True,
        },
        conversation_id="session",
    )
    assert result["runtime_context_update"]["agent_runtime_run_id"] == "original"
    assert result["runtime_context_update"]["status"] == "waiting_user"


def test_no_retired_planner_compatibility_entry_is_exposed():
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.ai_chat_app_service import AIChatApplicationService

    assert not hasattr(AIChatApplicationService, "_try_handle_dynamic_workflow")
    assert not hasattr(AgentOrchestrator, "start_run")


@pytest.mark.parametrize(
    "state,run_id,continuation_status",
    [
        ("waiting_user", "parent", "waiting_user"),
        ("waiting_approval", "parent", "waiting_approval"),
        ("queued", "parent", "queued"),
        ("completed", None, "completed"),
        ("unknown", None, "reconciliation_required"),
    ],
)
def test_server_history_retains_continuation_and_terminal_clear(
    monkeypatch, state, run_id, continuation_status
):
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
    assert metadata["summary"]["run_id"] == "parent"
    assert metadata["ui"]["runtimeContinuation"] == {
        "runId": run_id,
        "status": continuation_status,
        "sessionId": "original",
    }


def test_verified_child_download_survives_chat_history_and_legacy_replay(monkeypatch):
    from app.application.ai_chat.conversation_history import (
        persist_chat_turn,
        restore_runtime_history_files,
    )
    from app.domain.conversation.client_metadata import strip_client_recall_binding
    from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest

    context = {
        "local_user_id": 71,
        "tenant_id": "12",
        "mod_id": "office",
        "session_id": "original",
        "turn_id": "turn",
        "_conversation_revision": 4,
    }
    artifact = {
        "artifact_type": "file",
        "name": "报表.xlsx",
        "artifact_id": "xlsx-1",
        "uri": "/api/agent/runs/child/artifacts/xlsx-1",
        "metadata": {"sha256": "c" * 64},
    }
    operation = {"tool_id": "employee", "action": "execute", "params": {}}
    child = {
        "run_id": "child",
        "task_id": "child-task",
        "status": "completed",
        "success": True,
        "verified": True,
        "artifacts": [artifact],
        "verification": {
            "accepted": True,
            "steps": [
                {
                    "checks": [
                        {
                            "source": "run_artifact",
                            "status": "passed",
                            "evidence": {
                                "run_id": "child",
                                "artifact_id": "xlsx-1",
                                "sha256": "c" * 64,
                            },
                        }
                    ]
                }
            ],
        },
    }
    result = {
        "run_id": "parent",
        "ok": True,
        "execution_state": "completed",
        "output": "报表.xlsx",
        "business_receipts": [
            {
                **operation,
                "fingerprint": canonical_digest(operation),
                "state": "completed",
                "child_run_id": "child",
                "child_task_id": "child-task",
                "receipt": child,
            }
        ],
    }
    expected = [{**artifact, "run_id": "child"}]
    payload = chat.runtime_chat_payload(result, conversation_id="original")
    assert payload["data"]["output_artifacts"] == expected
    monkeypatch.setattr(
        "app.application.ai_chat.active_conversation.remember_active_conversation", Mock()
    )
    store = SimpleNamespace(save_turn=Mock(return_value=[1, 2]))
    assert persist_chat_turn("71", "生成", context, payload, store=store)["status"] == "saved"
    metadata = json.loads(store.save_turn.call_args.kwargs["messages"][1]["metadata"])
    assert metadata["ui"]["outputArtifacts"] == expected
    assert (
        "outputArtifacts" not in json.loads(strip_client_recall_binding(json.dumps(metadata)))["ui"]
    )

    metadata["ui"].pop("outputArtifacts")
    original = json.dumps(metadata)
    archive = SimpleNamespace(
        status="completed",
        user_id="71",
        metadata={
            "runtime_type": "xiaox",
            "runtime_context": context,
            "runtime_requests": {
                canonical_digest({"turn_id": "turn", "owner": "71"}): {
                    "state": "returned",
                    "turn_id": "turn",
                    "result": result,
                }
            },
        },
    )
    repository = SimpleNamespace(get=Mock(return_value=archive))
    monkeypatch.setattr(
        "app.application.agent_orchestrator.run_repository.get_agent_run_repository",
        lambda: repository,
    )
    page = {"messages": [{"role": "assistant", "metadata": original}]}
    restore_runtime_history_files(page, {**context, "tenant_id": "34"})
    assert page["messages"][0]["metadata"] == original
    restore_runtime_history_files(page, context)
    assert json.loads(page["messages"][0]["metadata"])["ui"]["outputArtifacts"] == expected
    child["verified"] = False
    assert "output_artifacts" not in chat.runtime_chat_payload(result)["data"]


def test_reconfiguration_resumes_original_run_without_new_dispatch(entry):
    from app.application.agent_runtime.configuration import RuntimeSetupError

    invoke, execute, _ = entry
    context = {"session_id": "original", "agent_runtime_run_id": "run-existing"}
    execute.side_effect = RuntimeSetupError(
        "runtime_configuration_required", "private route configuration"
    )
    failed = invoke(context)
    assert failed["success"] is False
    assert failed["data"]["error_code"] == "runtime_configuration_required"
    assert failed["runtime_context_update"]["agent_runtime_run_id"] == "run-existing"
    execute.side_effect = None
    execute.return_value = {
        "ok": True,
        "run_id": "run-existing",
        "execution_state": "completed",
        "output": "原任务已核对",
    }
    resumed = invoke(context)
    assert resumed["success"] is True
    assert resumed["run_id"] == "run-existing"
    assert resumed["runtime_context_update"]["conversation_id"] == "original"
    assert resumed["runtime_context_update"]["agent_runtime_run_id"] is None
    assert [call.kwargs["run_id"] for call in execute.call_args_list] == [
        "run-existing",
        "run-existing",
    ]
    assert all(call.kwargs["answer_to_waiting_input"] for call in execute.call_args_list)


def test_stream_progress_and_setup_failure_never_emit_unverified_draft(monkeypatch, entry):
    from app.application.agent_runtime.configuration import RuntimeSetupError

    deltas = Mock()
    notes = Mock()
    tools = Mock()
    monkeypatch.setattr("app.infrastructure.chat_stream_lifetime.publish_stream_delta", deltas)
    monkeypatch.setattr("app.infrastructure.chat_stream_lifetime.publish_stream_note", notes)
    monkeypatch.setattr("app.infrastructure.chat_stream_lifetime.publish_stream_tool_record", tools)
    invoke, execute, _ = entry
    execute.side_effect = RuntimeSetupError("runtime_account_model_required", "private key")
    failed = invoke({"session_id": "original", "agent_runtime_run_id": "existing"})
    assert failed["data"]["error_code"] == "runtime_account_model_required"
    assert failed["execution_state"] == "blocked"
    chat.stream_runtime_event(
        {
            "method": "item/agentMessage/delta",
            "runtime_goal_mode": "reply",
            "payload": {"delta": "not-yet-verified"},
        }
    )
    deltas.assert_not_called()
    chat.stream_runtime_event(
        {
            "method": "item/started",
            "payload": {"item": {"type": "mcpToolCall"}},
        }
    )
    tools.assert_called_once()
    notes.assert_not_called()


@pytest.mark.parametrize(
    "setup_code",
    ["runtime_configuration_required", "runtime_account_model_required"],
)
@pytest.mark.parametrize("resume", [False, True])
def test_json_and_sse_done_share_actionable_setup_error_contract(entry, setup_code, resume):
    """Exercise the real stream serializer with the exact synchronous chat result."""
    from app.application.agent_runtime.configuration import RuntimeSetupError
    from app.fastapi_routes.xcagi_compat_chat_helpers import _sse_event_line

    invoke, execute, _service = entry
    execute.side_effect = RuntimeSetupError(setup_code, "PRIVATE backend credentials")
    context = {"session_id": "original-session"}
    if resume:
        context["agent_runtime_run_id"] = "same-old-run"
    ordinary = invoke(context)

    assert ordinary["success"] is False
    assert ordinary["execution_state"] == "blocked"
    assert ordinary["data"]["error_code"] == setup_code
    assert ordinary["runtime_context_update"]["conversation_id"] == "original-session"

    # Online streaming uses 'done' with the same response object, not an
    # unrelated synthetic success or a partially emitted model narrative.
    serialized = _sse_event_line({"type": "done", "result": ordinary})
    events = [
        json.loads(line.partition(":")[2].strip())
        for line in serialized.decode("utf-8").splitlines()
        if line.startswith("data:")
    ]
    assert len(events) == 1
    done = events[0]
    assert done["type"] == "done"
    assert done["result"]["success"] is False
    assert done["result"]["data"]["error_code"] == setup_code
    assert done["result"]["runtime_context_update"]["agent_runtime_run_id"] == (
        "same-old-run" if resume else None
    )
    assert "PRIVATE" not in serialized.decode("utf-8")

    execute.side_effect = None
    execute.return_value = {
        "ok": True,
        "run_id": "same-old-run" if resume else "new-run",
        "execution_state": "completed",
        "output": "原任务已恢复",
    }
    recovered = invoke(context)
    assert recovered["success"] is True
    assert recovered["runtime_context_update"]["conversation_id"] == "original-session"
    if resume:
        assert execute.call_args.kwargs["run_id"] == "same-old-run"
