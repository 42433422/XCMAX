"""Late outcome receipts use the real conversation transaction and dedupe contract."""

from __future__ import annotations

import copy
import json
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.business_harness import BUSINESS_HARNESS_PROTOCOL
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_context import apply_task_context
from app.application.business_harness_projection import (
    project_enterprise_outcome_to_conversation,
    project_terminal_run_to_conversation,
)
from app.application.enterprise_cognition.outcomes import observe_terminal_run
from app.db.models import AIConversation, AIConversationSession, User
from app.domain.shared_services.conversation_service import ConversationService


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'receipts.sqlite'}")
    for model in (User, AIConversationSession, AIConversation):
        model.__table__.create(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions.begin() as db:
        db.add(User(id=7, username="receipt-owner", password="test"))

    @contextmanager
    def isolated_db():
        with sessions() as db:
            yield db

    monkeypatch.setattr("app.domain.shared_services.conversation_service.get_db", isolated_db)
    monkeypatch.setattr("app.domain.shared_services.conversation_service.notify_user", Mock())
    conversation = ConversationService()
    monkeypatch.setattr("app.services.get_conversation_service", lambda: conversation)
    repository = SQLAlchemyAgentRunRepository(session_factory=sessions)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.AgentOrchestrator",
        lambda: SimpleNamespace(get_run=repository.get),
    )
    run = AgentRun(user_id="7", message="订单目标任务", status="completed")
    context = {
        "user_id": "7",
        "tenant_id": "2",
        "mod_id": "sales",
        "task_id": "task-17",
        "conversation_id": "session-17",
        "_conversation_revision": 0,
        "enterprise_cognition": {"goal": {"goal_id": "goal-17"}},
    }
    run.metadata["runtime_context"] = context
    apply_task_context(run, context)
    step = AgentStep(
        node_id="delivery",
        tool_id="sales",
        action="deliver",
        status="completed",
        params={"order_id": 17},
        output={"success": True, "order_id": 17},
    )
    run.steps = [step]
    run.tool_calls = [
        ToolCall(
            step_id=step.step_id,
            node_id=step.node_id,
            tool_id=step.tool_id,
            action=step.action,
            params=step.params,
            status="completed",
            output=step.output,
        )
    ]
    repository.save(run)
    yield SimpleNamespace(run=run, repo=repository, conversation=conversation, sessions=sessions)
    engine.dispose()


def freeze(runtime, *, evidence_size=1):
    run = runtime.repo.get(runtime.run.run_id)
    previous = copy.deepcopy(run)
    body = {
        "protocol": "xcagi.enterprise-outcome.v1",
        "run_id": run.run_id,
        "task_id": "task-17",
        "actor_id": "7",
        "tenant_id": "2",
        "mod_id": "sales",
        "goal_id": "goal-17",
        "entity_type": "order",
        "entity_id": "17",
        "metric": "remaining_quantity",
        "unit": "箱",
        "status": "improved",
        "observation_verified": True,
        "business_success": None,
        "attribution": "unproven",
        "target_met": False,
        "delta": "-8",
        "before": {
            "value": "10",
            "unit": "箱",
            "source": "sales_orders",
            "source_version": "sha256:" + "a" * 64,
            "observed_at": "2026-11-21T12:00:00+00:00",
            "expires_at": "2026-11-21T12:01:00+00:00",
        },
        "after": {
            "value": "2",
            "unit": "箱",
            "source": "sales_orders",
            "source_version": "sha256:" + "b" * 64,
            "observed_at": "2026-11-21T12:00:30+00:00",
            "expires_at": "2026-11-21T12:01:30+00:00",
        },
        "actions": [
            {"call_id": f"call-{index}", "params": "private raw execution evidence" * 100}
            for index in range(evidence_size)
        ],
        "evidence": [
            {"source": "authority", "raw": "敏感原始资料" * 100} for _ in range(evidence_size)
        ],
    }
    body["observation_id"] = canonical_hash(body)
    event = run.add_event("enterprise.outcome_observed", "已核验", {"observation": body})
    assert runtime.repo.save_if_unchanged(run, previous)
    return {
        **copy.deepcopy(body),
        "memory_status": "pending",
        "memory_id": "mem-17",
        "memory_scope": "personal",
    }, event.event_id


def messages(runtime):
    with runtime.sessions() as db:
        return [
            SimpleNamespace(
                id=row.id,
                content=row.content,
                metadata=json.loads(row.conversation_metadata),
                intent=row.intent,
            )
            for row in db.query(AIConversation).order_by(AIConversation.id)
        ]


def test_large_observation_is_summarized_with_valid_json_and_original_evidence_ref(runtime):
    report, event_id = freeze(runtime, evidence_size=50)
    message_id = project_enterprise_outcome_to_conversation(
        runtime.run.run_id, report, repository=runtime.repo
    )
    row = messages(runtime)[0]
    assert row.id == message_id
    encoded = json.dumps(row.metadata, ensure_ascii=False)
    assert len(encoded) <= 12000 and "敏感原始资料" not in encoded and "private raw" not in encoded
    summary = row.metadata["ui"]["enterpriseOutcome"]
    assert summary["observation_id"] == report["observation_id"]
    assert summary["task_id"] == "task-17" and summary["run_id"] == runtime.run.run_id
    assert summary["before"]["value"] == "10" and summary["after"]["value"] == "2"
    assert summary["after"]["source_version"] == report["after"]["source_version"]
    assert summary["evidence_ref"]["event_id"] == event_id and summary["action_count"] == 50
    assert "因果关系仍未证实" in row.content and "待确认" in row.content


def test_unknown_terminal_then_late_measurement_remains_visible_and_deduplicated(
    runtime, monkeypatch
):
    monkeypatch.setattr(
        "app.application.enterprise_cognition.outcomes.observe_terminal_run",
        lambda run_id: {"status": "unknown", "observation_verified": False},
    )
    terminal_id = project_terminal_run_to_conversation(
        runtime.run.run_id, approval_request_id="approval-17"
    )
    terminal_before = messages(runtime)[0]
    report, _ = freeze(runtime)
    outcome_id = project_enterprise_outcome_to_conversation(
        runtime.run.run_id, report, repository=runtime.repo
    )
    assert outcome_id != terminal_id
    assert (
        project_terminal_run_to_conversation(runtime.run.run_id, approval_request_id="approval-17")
        == terminal_id
    )
    assert (
        project_enterprise_outcome_to_conversation(
            runtime.run.run_id, report, repository=runtime.repo
        )
        == outcome_id
    )
    rows = messages(runtime)
    assert len(rows) == 2 and rows[0].content == terminal_before.content
    assert rows[1].intent == "enterprise_outcome" and "从 10 变为 2" in rows[1].content
    assert rows[0].metadata["idempotency_key"] != rows[1].metadata["idempotency_key"]
    assert runtime.repo.get(runtime.run.run_id).status == "completed"


def test_memory_write_recovery_updates_a_separate_idempotent_receipt(runtime):
    report, _ = freeze(runtime)
    waiting = {**report, "memory_status": "retry_required", "memory_id": ""}
    first = project_enterprise_outcome_to_conversation(
        runtime.run.run_id, waiting, repository=runtime.repo
    )
    second = project_enterprise_outcome_to_conversation(
        runtime.run.run_id, report, repository=runtime.repo
    )
    assert first != second
    assert (
        project_enterprise_outcome_to_conversation(
            runtime.run.run_id, report, repository=runtime.repo
        )
        == second
    )
    rows = messages(runtime)
    assert len(rows) == 2 and "写入待重试" in rows[0].content and "待确认" in rows[1].content
    assert all(
        row.metadata["ui"]["enterpriseOutcome"]["observation_id"] == report["observation_id"]
        for row in rows
    )


@pytest.mark.parametrize(
    "change",
    [
        {"actor_id": "8"},
        {"tenant_id": "3"},
        {"mod_id": "other"},
        {"delta": "-10"},
        {"observation_verified": False},
        {"task_id": "other"},
    ],
)
def test_unverified_mismatched_or_mutated_report_cannot_be_projected(runtime, change):
    report, _ = freeze(runtime)
    assert (
        project_enterprise_outcome_to_conversation(
            runtime.run.run_id, report | change, repository=runtime.repo
        )
        is None
    )
    assert messages(runtime) == []


def test_observation_without_durable_event_is_not_a_receipt(runtime):
    report = {
        "run_id": runtime.run.run_id,
        "task_id": "task-17",
        "actor_id": "7",
        "tenant_id": "2",
        "mod_id": "sales",
        "observation_verified": True,
        "observation_id": "uncommitted",
    }
    assert (
        project_enterprise_outcome_to_conversation(
            runtime.run.run_id, report, repository=runtime.repo
        )
        is None
    )
    assert messages(runtime) == []


def test_lost_chat_commit_ack_retries_without_duplicate(runtime, monkeypatch):
    report, _ = freeze(runtime)
    original = runtime.conversation.save_message
    failure = [True]

    def save_then_lose(*args, **kwargs):
        result = original(*args, **kwargs)
        if failure:
            failure.pop()
            raise OSError("lost chat commit ACK")
        return result

    monkeypatch.setattr(runtime.conversation, "save_message", save_then_lose)
    assert (
        project_enterprise_outcome_to_conversation(
            runtime.run.run_id, report, repository=runtime.repo
        )
        is None
    )
    receipt = project_enterprise_outcome_to_conversation(
        runtime.run.run_id, report, repository=runtime.repo
    )
    assert len(messages(runtime)) == 1 and messages(runtime)[0].id == receipt


def test_late_observation_cannot_repopulate_a_revised_conversation(runtime):
    report, _ = freeze(runtime)
    with runtime.sessions.begin() as db:
        db.add(
            AIConversationSession(session_id="session-17", user_id=7, revision=1, message_count=0)
        )
    previous = runtime.repo.get(runtime.run.run_id).to_dict()
    assert (
        project_enterprise_outcome_to_conversation(
            runtime.run.run_id, report, repository=runtime.repo
        )
        is None
    )
    assert messages(runtime) == [] and runtime.repo.get(runtime.run.run_id).to_dict() == previous


def test_oversized_legacy_terminal_metadata_stays_valid_json(runtime, monkeypatch):
    run = runtime.repo.get(runtime.run.run_id)
    previous = copy.deepcopy(run)
    run.metadata["runtime_context"].pop("enterprise_cognition")
    run.final_output["business_result"] = {
        "protocol": BUSINESS_HARNESS_PROTOCOL,
        "status": "completed",
        "success": True,
        "summary": '"\\\n超长摘要' * 5000,
        "facts": {"order_id": 17, "name": "客户名称" * 5000},
        "run_id": run.run_id,
        "task_id": "task-17",
        "conversation_id": "session-17",
        "projection_key": f"{BUSINESS_HARNESS_PROTOCOL}:{run.run_id}:completed",
        "evidence": {"artifact_ids": ["artifact-" + "x" * 90] * 100},
    }
    assert runtime.repo.save_if_unchanged(run, previous)
    message_id = project_terminal_run_to_conversation(run.run_id)
    row = messages(runtime)[0]
    assert row.id == message_id and row.metadata["metadata_truncated"] is True
    assert len(json.dumps(row.metadata, ensure_ascii=False)) <= 12000
    assert row.metadata["business_harness"]["task_id"] == "task-17"
    assert row.metadata["evidence_ref"]["run_id"] == run.run_id


def test_automatic_terminal_hook_projects_without_re_evaluating_or_losing_receipt(
    runtime, monkeypatch
):
    report, _ = freeze(runtime)
    evaluation = Mock(return_value=report)
    monkeypatch.setattr(
        "app.application.enterprise_cognition.outcomes.OutcomeService",
        lambda **kwargs: SimpleNamespace(evaluate=evaluation),
    )
    monkeypatch.setattr(
        "app.infrastructure.auth.agent_mod_scope.validate_actor_context", lambda context: None
    )
    monkeypatch.setattr(
        "app.infrastructure.auth.agent_mod_scope.agent_mod_execution_scope",
        lambda binding: nullcontext(),
    )
    assert observe_terminal_run(runtime.run.run_id, repository=runtime.repo) == report
    assert evaluation.call_count == 1 and len(messages(runtime)) == 1
    monkeypatch.setattr(
        runtime.conversation, "save_message", Mock(side_effect=OSError("chat unavailable"))
    )
    assert observe_terminal_run(runtime.run.run_id, repository=runtime.repo) == report
    assert runtime.repo.get(runtime.run.run_id).status == "completed"
