"""Shared SQL-backed chat fixture for planning clarification and waiting workflows."""

import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.application.agent_orchestrator import AgentOrchestrator, SQLAlchemyAgentRunRepository
from app.application.agent_task_context import scoped_conversation_user_id
from app.application.ai_chat_app_service import AIChatApplicationService
from app.application.workflow.approval_service import ApprovalService
from app.application.workflow.plan_store import WorkflowPlanStore
from app.application.workflow.planner import LLMWorkflowPlanner
from app.application.workflow.risk_gate import HybridRiskGate
from app.infrastructure.modstore_transport import MarketModelError
from tests.fixtures.backend_ci_isolation import provision_native_checkpoint_schema
from tests.fixtures.planner_model import goal_review_response
from tests.test_application.test_agent_user_decision_pause import native_preview as native_preview

ORIGINAL = "澜宇2026/9/30购货明细多少"
QUESTION = "A) 查询2026/9/27—10/24的澜宇购货明细；B) 补充具体分厂。请选择。"
QUERY = "澜宇2026/9/27—10/24购货明细"
ANSWER = "合成验收样本：澜宇2026/9/30购货2件，金额100元。"


def _model_response(payload):
    return {
        "choices": [
            {
                "message": {"content": json.dumps(payload, ensure_ascii=False)},
                "finish_reason": "stop",
            }
        ]
    }


def _planning_requests(requests):
    return [
        r
        for r in requests
        if r["task"] not in {"audit_goal_coverage", "audit_reply", "classify_clarification_turn"}
    ]


@pytest.fixture
def roundtrip(monkeypatch, tmp_path, trusted_actor, native_preview):
    actor = trusted_actor(user_id=17, role="admin")
    factory = actor.factory
    repository = SQLAlchemyAgentRunRepository(session_factory=factory)
    provision_native_checkpoint_schema(factory.kw["bind"])
    store = WorkflowPlanStore(session_factory=factory)
    monkeypatch.setattr("app.application.workflow.plan_store.WorkflowPlanStore", lambda: store)
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "idempotency.sqlite"))
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))

    executor = Mock()
    executor.execute_with_deadline.return_value = {
        "success": True,
        "dataset_id": "synthetic-purchases",
        "query": QUERY,
        "answer": ANSWER,
        "answer_grounded": True,
        "chunks": [{"text": ANSWER, "source_url": "synthetic-purchase-fixture.xlsx"}],
        "citations": [{"text": ANSWER, "source_url": "synthetic-purchase-fixture.xlsx"}],
    }

    def new_orchestrator():
        return AgentOrchestrator(
            repository=SQLAlchemyAgentRunRepository(session_factory=factory, auto_create=False),
            tool_executor=executor,
        )

    monkeypatch.setattr("app.application.agent_orchestrator.AgentOrchestrator", new_orchestrator)
    requests = []
    state = SimpleNamespace(
        write=False,
        query=QUERY,
        question=QUESTION,
        fail_once=False,
        questions=[],
        classification={"turn_kind": "answer", "resolved": True, "parameters": {}},
        classification_error=None,
        reply=None,
    )

    def complete(**kwargs):
        request = json.loads(kwargs["messages"][-1]["content"])
        requests.append(request)
        if request["task"] == "classify_clarification_turn":
            if state.classification_error:
                raise state.classification_error
            return _model_response(state.classification)
        if request["task"] == "audit_reply":
            return _model_response({"violations": [], "clarification_question": None})
        if request["task"] == "audit_goal_coverage":
            if all(n["tool_id"] == "conversation" for n in request["plan"]["nodes"]):
                return goal_review_response(
                    request,
                    source=request["user_message"],
                    node_ids=[n["node_id"] for n in request["plan"]["nodes"]],
                    outcome="reply",
                )
            assert [node["node_id"] for node in request["plan"]["nodes"]] == ["business"]
            if len(request["user_message"]) > 2000:
                # A real review cites bounded source spans, never the entire
                # long transcript in one GoalDisposition.source (max 2000).
                assert ORIGINAL in request["user_message"]
                return _model_response(
                    {
                        "goals": [
                            {
                                "goal_id": "purchase",
                                "source": ORIGINAL,
                                "outcome": "execute",
                                "node_ids": ["business"],
                            },
                            {
                                "goal_id": "no_write",
                                "source": "禁止写入",
                                "outcome": "negated",
                                "node_ids": [],
                            },
                        ],
                        "violations": [],
                    }
                )
            return goal_review_response(
                request, source=request["user_message"], node_ids=["business"], outcome="execute"
            )
        if state.fail_once:
            failure = state.fail_once
            state.fail_once = False
            if failure == "context":
                from app.application.agent_orchestrator.context_window_manager import (
                    ContextWindowExceeded,
                )

                raise ContextWindowExceeded("当前模型窗口不足，原任务范围不能裁剪")
            raise MarketModelError({"status": 402})
        if state.reply is not None:
            return _model_response({"mode": "reply", "reply": state.reply})
        if len(_planning_requests(requests)) == 1:
            node = {
                "node_id": "scope",
                "tool_id": "clarify",
                "action": "ask",
                "params": {"question": state.question},
            }
        elif state.questions:
            node = {
                "node_id": "scope",
                "tool_id": "clarify",
                "action": "ask",
                "params": {"question": state.questions.pop(0)},
            }
        elif state.write:
            node = {
                "node_id": "business",
                "tool_id": "customers",
                "action": "delete",
                "params": {"id": 42},
            }
        else:
            node = {
                "node_id": "business",
                "tool_id": "dataset_rag",
                "action": "query",
                "params": {"dataset_id": "synthetic-purchases", "query": state.query},
            }
        return _model_response({"mode": "workflow", "intent": "purchase_query", "nodes": [node]})

    def new_service():
        service = object.__new__(AIChatApplicationService)
        service._pending_workflows = {}
        service.workflow_planner = LLMWorkflowPlanner(
            ai_service=Mock(get_context=Mock(return_value=None)), completion=complete
        )
        service.risk_gate = HybridRiskGate()
        service.approval_service = ApprovalService()
        return service

    context = {
        **actor.context,
        "session_id": "purchase-query",
        "conversation_id": "purchase-query",
        "tool_execution_profile": "full",
        "chat_knowledge_dataset_ids": ["synthetic-purchases"],
    }

    def send(service, message, *, session="purchase-query", extra=None):
        current = {
            **context,
            "session_id": session,
            "conversation_id": session,
            "turn_id": uuid4().hex,
            **(extra or {}),
        }
        return service.process_chat("17", message, context=current, source="normal")

    return SimpleNamespace(
        actor=actor,
        repository=repository,
        store=store,
        executor=executor,
        requests=requests,
        state=state,
        service=new_service,
        send=send,
        chat_user=scoped_conversation_user_id("17", context),
        context=context,
        orchestrator=new_orchestrator,
        preview=native_preview,
    )
