"""Read-only recovery of original chat turns and their scoped run receipts."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.task_conversation_store import TaskConversationStore


@pytest.fixture
def store(dialogue_db, monkeypatch):
    from app.application.task_conversation_store import get_db

    monkeypatch.setattr("app.domain.shared_services.conversation_service.get_db", get_db)
    monkeypatch.setattr(
        "app.domain.shared_services.conversation_service.notify_user", lambda **kwargs: None
    )
    return TaskConversationStore()


@pytest.fixture
def turn_history(store, monkeypatch, tmp_path):
    from types import SimpleNamespace

    from app.application.ai_chat import dialogue_memory

    monkeypatch.setenv("XCAGI_DIALOGUE_MEMORY_DIR", str(tmp_path / "turn-memory"))
    monkeypatch.setattr(dialogue_memory, "task_conversation_store", store)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.AgentOrchestrator",
        lambda: SimpleNamespace(list_runs=lambda **_: []),
    )
    context = {
        "local_user_id": 41,
        "tenant_id": "12",
        "mod_id": "employee-mod",
        "conversation_id": "employee-history",
        "session_id": "employee-history",
        "turn_id": "original-turn",
    }
    yield context
    dialogue_memory._release_turn(dialogue_memory.conversation_key(context), "original-turn")


@pytest.mark.parametrize("sql_only", [False, True])
def test_history_reads_original_text_turn_with_scoped_sql_recovery(store, turn_history, sql_only):
    from app.application.ai_chat import dialogue_memory as memory
    from app.application.ai_chat.conversation_history import persist_chat_turn
    from app.infrastructure.tenant_scope import tenant_scope

    assert memory.prepare_chat_turn("原问题", turn_history) is None
    payload = {"success": True, "response": "原来的完整回复。", "execution_state": "completed"}
    persist_chat_turn("41", "原问题", turn_history, payload)
    memory.settle_chat_turn("原问题", turn_history, payload, "completed")
    if sql_only:
        memory._path(memory.conversation_key(turn_history)).unlink()
    with tenant_scope(12):
        history = TaskConversationStore().get_history(
            session_id="employee-history",
            user_id=41,
            mod_id="employee-mod",
            turn_id="original-turn",
        )
        receipt = history["turn_receipt"]
        assert receipt["status"] == "completed"
        assert receipt["turn_id"] == "original-turn" and receipt["run_id"] == ""
        assert receipt["receipt_kind"] == "turn" and receipt["durable"] is True
        assert receipt["message"] == "原来的完整回复。"
        assert "turn_receipt" not in store.get_history(
            session_id="employee-history",
            user_id=42,
            mod_id="employee-mod",
            turn_id="original-turn",
        )
        assert "turn_receipt" not in store.get_history(
            session_id="employee-history", user_id=41, mod_id="another-mod", turn_id="original-turn"
        )
    with tenant_scope(13):
        assert "turn_receipt" not in store.get_history(
            session_id="employee-history",
            user_id=41,
            mod_id="employee-mod",
            turn_id="original-turn",
        )


def test_history_reads_unfinished_turn_without_settling_or_reexecuting(store, turn_history):
    from app.application.ai_chat import dialogue_memory as memory
    from app.infrastructure.tenant_scope import tenant_scope

    assert memory.prepare_chat_turn("原问题", turn_history) is None
    key = memory.conversation_key(turn_history)
    before = memory._path(key).read_bytes()
    with tenant_scope(12):
        history = store.get_history(
            session_id="employee-history",
            user_id=41,
            mod_id="employee-mod",
            turn_id="original-turn",
        )
        assert history["active_turn"]["status"] in {"processing", "running"}
        assert "turn_receipt" not in history
        assert memory._turn_is_live(key, "original-turn")
        memory._release_turn(key, "original-turn")
        abandoned = store.get_history(
            session_id="employee-history",
            user_id=41,
            mod_id="employee-mod",
            turn_id="original-turn",
        )["turn_receipt"]
        assert abandoned["status"] == "unknown" and abandoned["requires_reconciliation"] is True
    assert memory._path(key).read_bytes() == before


def test_client_metadata_cannot_claim_a_scoped_completed_receipt(store, turn_history):
    from app.application.ai_chat import dialogue_memory as memory
    from app.infrastructure.tenant_scope import tenant_scope

    metadata = json.dumps(
        {
            "business_harness": {
                "turn_id": "original-turn",
                "recall_bound": True,
                "conversation_key": memory.conversation_key(turn_history),
            },
            "summary": {"success": True, "status": "completed"},
        }
    )
    for role in ("user", "assistant"):
        store.save_message(
            session_id="employee-history",
            user_id=41,
            role=role,
            content="client claimed result",
            metadata=metadata,
        )
    assert memory.stored_turn_receipt(turn_history, "original-turn") is None
    with tenant_scope(12):
        history = store.get_history(
            session_id="employee-history",
            user_id=41,
            mod_id="employee-mod",
            turn_id="original-turn",
        )
    assert "turn_receipt" not in history


@pytest.mark.parametrize(
    "mismatch", ["", "missing", "owner", "tenant", "mod", "session", "turn", "revision"]
)
def test_history_refreshes_only_original_owned_run(
    store, turn_history, monkeypatch, tmp_path, mismatch
):
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.ai_chat import dialogue_memory as memory
    from app.infrastructure.tenant_scope import tenant_scope

    assert memory.prepare_chat_turn("原问题", turn_history) is None
    factory = sessionmaker(bind=create_engine(f"sqlite:///{tmp_path / 'runs.sqlite'}"))
    repository = SQLAlchemyAgentRunRepository(session_factory=factory)
    runtime = dict(turn_history)
    if mismatch in {"tenant", "mod", "session", "turn"}:
        runtime[f"{mismatch}_id"] = f"other-{mismatch}"
    if mismatch == "revision":
        runtime["_conversation_revision"] += 1
    original = AgentRun(
        run_id="original-run",
        user_id="42" if mismatch == "owner" else "41",
        message="原问题",
        status="completed",
        final_output={"chat_payload": {"success": True, "response": "已读回原执行结果。"}},
        metadata={"runtime_context": runtime},
    )
    if mismatch != "missing":
        repository.save(original)
    repository.save(
        AgentRun(run_id="unrelated-run", user_id="41", message="other", status="completed")
    )
    memory.settle_chat_turn(
        "原问题",
        turn_history,
        {"success": False, "response": "等待执行", "run_id": original.run_id},
        "running",
    )
    restarted_repository = SQLAlchemyAgentRunRepository(session_factory=factory)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.run_repository.get_agent_run_repository",
        lambda: restarted_repository,
    )
    before = memory._path(memory.conversation_key(turn_history)).read_bytes()
    with tenant_scope(12):
        receipt = store.get_history(
            session_id="employee-history",
            user_id=41,
            mod_id="employee-mod",
            turn_id="original-turn",
        )["turn_receipt"]
    assert receipt["run_id"] == original.run_id and receipt["receipt_kind"] == "run"
    assert receipt["status"] == ("unknown" if mismatch else "completed")
    assert receipt["requires_reconciliation"] is bool(mismatch)
    if mismatch:
        assert "已读回" not in receipt["message"]
    else:
        assert receipt["message"] == "已读回原执行结果。"
    assert memory._path(memory.conversation_key(turn_history)).read_bytes() == before
    assert len(repository.list_recent(user_id=None)) == (1 if mismatch == "missing" else 2)


@pytest.mark.parametrize(
    "state,extra,expected",
    [
        ("queued", {}, "queued"),
        ("running", {}, "running"),
        ("waiting_approval", {}, "waiting_approval"),
        ("waiting_auth", {}, "waiting_auth"),
        ("waiting_input", {}, "waiting_input"),
        ("paused", {}, "paused"),
        ("blocked", {}, "blocked"),
        ("completed", {"data": {"outcome_unknown": True}}, "unknown"),
        ("completed", {"result": {"status": "failed"}}, "failed"),
        ("completed", {"result": {"execution_accepted": True}}, "queued"),
    ],
)
def test_history_does_not_turn_acceptance_or_nested_failure_into_success(
    store, turn_history, state, extra, expected
):
    from app.application.ai_chat import dialogue_memory as memory
    from app.infrastructure.tenant_scope import tenant_scope

    memory.prepare_chat_turn("原问题", turn_history)
    memory.settle_chat_turn(
        "原问题",
        turn_history,
        {"success": True, "response": "不能单凭这句话确认成功", **extra},
        state,
    )
    with tenant_scope(12):
        history = store.get_history(
            session_id="employee-history",
            user_id=41,
            mod_id="employee-mod",
            turn_id="original-turn",
        )
    receipt = history.get("active_turn") or history["turn_receipt"]
    assert receipt["status"] == expected
    assert "不能单凭" not in receipt["message"]


@pytest.mark.parametrize(
    "run_state,tool_id,result,expected",
    [
        ("waiting_user", "products", {}, "waiting_approval"),
        ("waiting_user", "clarify", {}, "waiting_input"),
        ("completed", "products", {"status": "pending_approval"}, "waiting_approval"),
        ("completed", "products", {"status": "failed"}, "failed"),
        ("completed", "products", {"requires_reconciliation": True}, "unknown"),
        ("future_state", "products", {}, "unknown"),
    ],
)
def test_history_rechecks_original_run_approval_and_business_outcome(
    store, turn_history, monkeypatch, run_state, tool_id, result, expected
):
    from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.ai_chat import dialogue_memory as memory
    from app.infrastructure.tenant_scope import tenant_scope

    memory.prepare_chat_turn("原问题", turn_history)
    repository = InMemoryAgentRunRepository()
    original = repository.save(
        AgentRun(
            user_id="41",
            message="原问题",
            status=run_state,
            steps=[
                AgentStep(
                    node_id="step",
                    tool_id=tool_id,
                    action="execute",
                    status="waiting_user" if run_state == "waiting_user" else "completed",
                )
            ],
            final_output={"business_result": {"protocol": "xcagi.business-harness.v1", **result}},
            metadata={"runtime_context": dict(turn_history)},
        )
    )
    monkeypatch.setattr(
        "app.application.agent_orchestrator.run_repository.get_agent_run_repository",
        lambda: repository,
    )
    memory.settle_chat_turn(
        "原问题", turn_history, {"run_id": original.run_id, "response": "旧进度"}, "running"
    )
    with tenant_scope(12):
        history = store.get_history(
            session_id="employee-history",
            user_id=41,
            mod_id="employee-mod",
            turn_id="original-turn",
        )
    receipt = history.get("active_turn") or history["turn_receipt"]
    assert receipt["status"] == expected and receipt["run_id"] == original.run_id
