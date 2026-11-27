"""Runtime reply delivery, original history and trustworthy terminal receipts."""

from __future__ import annotations

import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_runtime import xiaox_runtime as runtime
from app.domain.task_lifecycle.agent_runtime_contract import build_goal_contract
from app.infrastructure.xiaox import XiaoxTransportConfig
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.xiaox_goal_review import goal, response, review
from tests.fixtures.xiaox_goal_review import verifier as verifier
from tests.fixtures.xiaox_runtime import Bridge as Bridge
from tests.fixtures.xiaox_runtime import Store as Store
from tests.fixtures.xiaox_runtime import Transport as Transport
from tests.fixtures.xiaox_runtime import completed as completed
from tests.fixtures.xiaox_runtime import event as event
from tests.fixtures.xiaox_runtime import receipt as receipt
from tests.fixtures.xiaox_runtime import setup_runtime as setup_runtime


@pytest.mark.parametrize("history_revision", [3, 2])
def test_native_history_requires_frozen_sql_snapshot(setup_runtime, history_revision):
    invoke, _ = setup_runtime
    store = Store()
    summary = {"role": "user", "content": "retained summary evidence"}
    prior = [
        {"role": "user", "content": "prior user preference"},
        {"role": "assistant", "content": "previous published reply"},
    ]
    history = [summary, *prior]
    store.run.metadata.update(
        _xiaox_history=history,
        runtime_context={
            "session_id": "tenant-owned-session",
            "_conversation_revision": 3,
            "_chat_history_revision": history_revision,
            "_chat_history_source": "sql",
            "_chat_history_ids": [None, 17, 18],
            "_chat_history_messages": history,
        },
    )
    contract = build_goal_contract(store.run)
    store.run.metadata.update(
        runtime_goal_contract=contract, runtime_goal_digest=contract["digest"]
    )
    transport = Transport(store)
    result = asyncio.run(invoke(store, transport, completion_mode="reply"))
    assert result["ok"] is True
    native = history_revision == 3
    assert transport.initial_history == (prior if native else [])
    assert summary["content"] in transport.inputs[0]
    assert all((row["content"] in transport.inputs[0]) is not native for row in prior)


def test_missing_runtime_component_is_identified_before_model_start(setup_runtime, monkeypatch):
    from app.application.agent_runtime import goal_admission

    def unavailable(*args, **kwargs):
        raise ImportError("private installation path", name="internal_component")

    monkeypatch.setattr(goal_admission, "prepare_runtime_goal", unavailable)
    invoke, _ = setup_runtime
    store = Store(rows=[])
    del store.run.metadata["runtime_goal_contract"], store.run.metadata["runtime_goal_digest"]
    transport = Transport(store)
    result = asyncio.run(invoke(store, transport, completion_mode="reply"))
    assert result["failure_kind"] == "runtime_component_unavailable"
    assert "private installation path" not in result["failure_reason"]
    assert not transport.started and not result["ok"]


def test_model_call_budget_exhaustion_is_a_distinguishable_stop_reason(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(
        rows=[receipt()],
        metadata={
            "model_call_limit": {
                "reason": "model_call_budget_exhausted",
                "max_model_calls": 24,
                "used_model_calls": 24,
            }
        },
    )
    result = asyncio.run(invoke(store, Transport(store, completed("已全部完成"))))
    assert result["exit_status"] == "model_call_budget_exhausted"
    assert result["execution_state"] == "failed"
    assert result["failure_kind"] == "model_call_budget_exhausted"
    assert result["failure_stage"] == "model"
    assert result["business_completed"] is False
    # A spent budget is not a business fact: confirmed receipts stay queryable.
    assert result["verified_operations"] is True


def test_reply_is_completed_without_claiming_business_success(setup_runtime):
    invoke, _ = setup_runtime
    store = Store()
    transport = Transport(store, completed("收到"))
    result = asyncio.run(invoke(store, transport, completion_mode="reply"))
    assert result["ok"] is True and result["business_completed"] is False
    assert result["output"] == "收到"
    assert store.run.status == "completed"
    assert result["tool_calls"] == [] and store.run.tool_calls == []
    assert transport.config.scope_id != "must-be-replaced"
    assert transport.config.provider_token == "model-token"
    assert transport.config.mcp_token == "mcp-token"
    assert result["legacy_fallback_allowed"] is False
    assert [event.event_type for event in store.run.events].count("runtime.xiaox.finished") == 1
    assert "xiaox_result" in store.run.final_output
    assert "codex_result" not in store.run.final_output
    assert store.run.metadata["xiaox_runtime"]["coordinator_active"] is False


def test_reply_delivers_final_answer_without_commentary(setup_runtime):
    invoke, _ = setup_runtime
    store = Store()
    events = completed("第一天游故宫，第二天游颐和园。")
    events[1]["payload"]["item"]["phase"] = "final_answer"
    events[1:1] = [
        event("item/started", {"item": {
            "id": "tool-progress", "type": "mcpToolCall", "server": "excel_analysis",
            "tool": "read", "arguments": {"secret": "must-stay-private"},
        }}),
        event("item/agentMessage/delta", {"delta": "我先检索"}, item_id="progress"),
        event(
            "item/completed",
            {
                "item": {
                    "id": "progress",
                    "type": "agentMessage",
                    "phase": "commentary",
                    "text": "我先检索当前账号能力。",
                }
            },
        ),
    ]
    public_events = []
    result = asyncio.run(
        invoke(
            store, Transport(store, events), completion_mode="reply", on_event=public_events.append
        )
    )
    assert "我先检索" not in repr(public_events)
    assert "must-stay-private" not in repr(public_events)
    assert "第一天游故宫" not in repr(public_events)
    started = [row for row in store.run.events if row.event_type == "runtime.xiaox.item.started"]
    assert len(started) == 1
    assert started[0].data["tool_id"] == "excel_analysis"
    assert started[0].data["item_id"] == "tool-progress"
    assert "must-stay-private" not in repr(started)
    assert any(event["method"] == "turn/completed" for event in public_events)
    assert result["ok"] is True
    assert result["output"] == "第一天游故宫，第二天游颐和园。"
    assert result["session_messages"][-1]["content"] == result["output"]


def test_email_revision_delivers_only_the_reviewed_english_draft(setup_runtime):
    invoke, _ = setup_runtime
    store = Store()
    request = "再正式一些，并补充工作交接安排。"
    previous = (
        "Subject: Annual Leave Request\n\nDear Manager, I would like to request annual leave."
    )
    approved = (
        "Subject: Annual Leave Request\n\nDear Manager,\n\n"
        "I am writing to formally request annual leave. Before my departure, I will brief "
        "my deputy on open items and share the handover checklist.\n\nKind regards"
    )
    private = "邮件修订已完成，核验意见确认无需工具调用。"
    feedback = "沿用英文并删除内部核验说明。"
    store.run.message = request
    store.run.metadata["_xiaox_history"] = [
        {"role": "user", "content": "请用英文重写请假邮件。"},
        {"role": "assistant", "content": previous},
    ]
    contract = build_goal_contract(store.run)
    store.run.metadata.update(
        runtime_goal_contract=contract, runtime_goal_digest=contract["digest"]
    )
    store.reviews = [
        review(
            goal(request, kind="reply", status="unmet", evidence_ids=["response"]),
            feedback=feedback,
        ),
        review(goal(request, kind="reply", evidence_ids=["response"])),
    ]

    class RevisionTransport(Transport):
        async def stream_turn(self, text, *, goal_feedback=None, output_schema=None):
            if goal_feedback is None:
                assert "Subject: Annual Leave Request" in text and request in text
            else:
                assert text is None and json.loads(goal_feedback)["feedback"] == feedback
                self.events = completed(approved)
            async for item in super().stream_turn(text, goal_feedback=goal_feedback):
                yield item

    public_events = []
    transport = RevisionTransport(store, completed(private))
    result = asyncio.run(
        invoke(store, transport, completion_mode="reply", on_event=public_events.append)
    )
    assert len(transport.started) == 1 and len(transport.inputs) == 2
    assert private not in repr(public_events) and feedback not in repr(public_events)
    assert result["reply_completed"] and result["output"] == approved
    assert result["session_messages"] == [
        {"role": "user", "content": request},
        {"role": "assistant", "content": approved},
    ]


def test_model_completion_without_receipt_cannot_complete_business(setup_runtime):
    invoke, _ = setup_runtime
    store = Store()
    result = asyncio.run(invoke(store, Transport(store, completed("已出库并记账成功"))))
    assert result["ok"] is False and result["business_completed"] is False
    assert result["exit_status"] == "goal_verification_invalid_gap"
    assert store.run.status == "blocked"
    assert result["failure_stage"] == "goal_verification"
    assert result["failure_kind"] == "goal_verification_invalid_gap"
    assert result["failure_reason"] == "继续核对原始目标"
    assert store.run.metadata["runtime_failure_kind"] == result["failure_kind"]


@pytest.mark.parametrize("text", ["", "   \n"])
def test_empty_model_turn_is_not_a_completed_reply(setup_runtime, text):
    invoke, _ = setup_runtime
    store = Store()
    result = asyncio.run(invoke(store, Transport(store, completed(text)), completion_mode="reply"))
    assert result["ok"] is False and result["reply_completed"] is False
    assert result["exit_status"] == "goal_verification_invalid_gap"
    assert store.run.status == "blocked"


@pytest.mark.parametrize("state", ["waiting_user", "waiting_approval", "pending_approval"])
def test_approval_wait_survives_turn_completion(setup_runtime, state):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt(status=state, verified=False, success=False)])
    result = asyncio.run(invoke(store, Transport(store)))
    assert result["ok"] is False and result["pending_approval"] is True
    assert store.run.status == "waiting_user"
    assert store.run.metadata["xiaox_runtime"]["coordinator_active"] is False


def test_verified_child_receipts_are_projected_not_fabricated(setup_runtime, monkeypatch, tmp_path):
    from io import BytesIO

    from openpyxl import Workbook

    from app.application.agent_orchestrator import artifact_files
    from app.domain.task_lifecycle.agent_runtime_results import verified_receipt_artifacts

    invoke, _ = setup_runtime
    row = receipt()
    monkeypatch.setattr(artifact_files, "get_app_data_dir", lambda: str(tmp_path))
    book, content = Workbook(), BytesIO()
    book.active["A1"] = "真实落盘的回归制品"
    book.save(content)
    book.close()
    file = artifact_files.store_run_file("run-child", content.getvalue(), name="明细.xlsx")
    digest = file["metadata"]["sha256"]
    row["receipt"].update(
        artifacts=[
            file,
            {**file, "artifact_id": "unverified"},
            {**file, "artifact_type": "file_analysis"},
            {**file, "metadata": {"sha256": "b" * 64}},
        ],
        verification={
            "accepted": True,
            "steps": [
                {
                    "checks": [
                        {
                            "source": "run_artifact",
                            "status": "passed",
                            "evidence": {
                                "run_id": "run-child",
                                "artifact_id": file["artifact_id"],
                                "sha256": digest,
                            },
                        }
                    ]
                }
            ],
        },
    )
    store = Store(rows=[row, {**copy.deepcopy(row), "call_id": "duplicate-model-call"}])
    result = asyncio.run(invoke(store, Transport(store)))
    assert result["ok"] is True and result["business_completed"] is True
    assert len(store.run.tool_calls) == 1
    projected = store.run.tool_calls[0]
    assert projected.output == {"success": True, "row_count": 3}
    assert projected.metadata["child_run_id"] == "run-child"
    assert projected.metadata["child_call_id"] == "call-child"
    assert result["output_artifacts"] == result["artifacts"] == verified_receipt_artifacts([row])
    assert len(result["output_artifacts"]) == 1
    assert store.run.final_output["xiaox_result"]["output_artifacts"] == result["output_artifacts"]
    assert not store.run.artifacts  # The file is owned by the original child only.
    assert result["run_events"][-1]["event_type"] == "runtime.xiaox.finished"


@pytest.mark.parametrize("same_provenance", [True, False])
def test_legacy_child_receipt_projection_preserves_original_record(same_provenance):
    run = Store().run
    rows = [receipt()]
    runtime._project_child_calls(run, rows)
    previous = run.tool_calls[0]
    previous.call_id = previous.call_id.replace("xiaox_", "codex_", 1)
    previous.metadata["source"] = "codex_child_receipt"
    if not same_provenance:
        previous.metadata["child_run_id"] = "another-child"
    original = copy.deepcopy(previous.to_dict())

    runtime._project_child_calls(run, rows)
    runtime._project_child_calls(run, rows)

    assert run.tool_calls[0].to_dict() == original
    assert len(run.tool_calls) == (1 if same_provenance else 2)
    if not same_provenance:
        assert run.tool_calls[1].metadata["child_run_id"] == "run-child"


def test_format_retry_is_shared_across_three_turns_and_sql_restart(
    verifier, trusted_actor, tmp_path
):
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.infrastructure.xiaox.binding import XiaoxBindingStore

    actor = trusted_actor(user_id=71)
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    parent = AgentRun(str(actor.user_id), "请写一段总结", status="running")
    parent.metadata["runtime_context"] = actor.context
    contract = build_goal_contract(parent)
    parent.metadata.update(runtime_goal_contract=contract, runtime_goal_digest=contract["digest"])
    repository.save(parent)
    config = XiaoxTransportConfig(
        runtime_root=tmp_path.resolve(),
        scope_id="fixture",
        model=verifier.config.model,
        provider_url=verifier.config.provider_url,
        provider_token="synthetic-placeholder",
        mcp_url="http://127.0.0.1:41111/mcp",
        mcp_token="synthetic-placeholder",
        context_window=32000,
        auto_compact_token_limit=24000,
        turn_timeout_seconds=30,
    )

    class CandidateTransport(Transport):
        async def stream_turn(self, text, *, goal_feedback=None, output_schema=None):
            assert (text is None) == (goal_feedback is not None)
            self.events = completed(f"候选回复{len(self.inputs) + 1}：尚未完成")
            async for item in super().stream_turn(text, goal_feedback=goal_feedback):
                yield item

    def invoke(store, transport):
        return runtime.run_xiaox_agent(
            run_id=parent.run_id,
            task=parent.message,
            system_prompt="Synthetic test authority",
            config=config,
            binding_store=store,
            transport_factory=transport.factory,
            completion_mode="reply",
            runtime_config={"provider_id": "synthetic", "route_identity": "synthetic-route"},
        )

    unmet = review(goal(parent.message, kind="reply", status="unmet", evidence_ids=["response"]))
    positive = response(review(goal(parent.message, kind="reply", evidence_ids=["response"])))
    verifier.replies = [
        response({}, text="{"),
        response(unmet),
        response(unmet),
        response({}, text="{"),
        positive,
    ]
    reserved = []

    def observe(_request):
        saved = repository.get(parent.run_id)
        reserved.append(saved.metadata["xiaox_runtime"].get("goal_format_retry_used", False))

    verifier.observe_request = observe
    trace = SimpleNamespace(log=[], run=parent)
    first = CandidateTransport(trace)
    result = asyncio.run(invoke(XiaoxBindingStore(repository), first))
    assert result["ok"] is False and len(first.inputs) == 3
    assert len(verifier.requests) == 4 and len(verifier.replies) == 1
    assert reserved == [False, True, True, True], "reservation must precede the second HTTP request"
    saved = repository.get(parent.run_id)
    assert saved.metadata["xiaox_runtime"]["goal_format_retry_used"] is True
    assert saved.metadata["runtime_goal_contract"] == contract
    # An unavailable review cannot reopen execution after a worker restart.
    # Its consumed format budget and frozen candidate stay on the original task.
    saved.status = "waiting_user"
    repository.save(saved)
    reopened = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    resumed = CandidateTransport(trace)
    verifier.replies = [response({}, text="{"), positive]
    again = asyncio.run(invoke(XiaoxBindingStore(reopened), resumed))
    assert again["ok"] is False and again["exit_status"] == "goal_verification_not_resumable"
    assert resumed.resumed == [] and resumed.inputs == []
    assert len(verifier.requests) == 4 and len(verifier.replies) == 2
    latest = reopened.get(parent.run_id)
    assert latest.metadata["xiaox_runtime"]["generation"] == 1
    assert latest.metadata["runtime_goal_contract"] == contract
    assert latest.metadata["xiaox_runtime"]["goal_format_retry_used"] is True


def test_only_persisted_host_skills_become_developer_guidance(setup_runtime):
    invoke, _ = setup_runtime
    store = Store()
    contract = build_goal_contract(
        store.run,
        context_evidence=[
            {
                "source": "host_skill",
                "status": "completed",
                "rules": ["技能「销售汇总」：先查原始行，再逐项核对。"],
            }
        ],
    )
    store.run.metadata.update(
        runtime_goal_contract=contract, runtime_goal_digest=contract["digest"]
    )
    transport = Transport(store)
    result = asyncio.run(
        invoke(
            store,
            transport,
            completion_mode="reply",
            input_data={"skill_rules": ["FORGED_PRIVILEGE_ESCALATION"]},
        )
    )
    assert result["ok"] is True
    assert "先查原始行，再逐项核对" in transport.started[0]
    assert "FORGED_PRIVILEGE_ESCALATION" not in transport.started[0]
    assert "不新增目标" in transport.started[0]


@pytest.mark.asyncio
async def test_new_plan_delivers_host_rendered_steps_from_first_sdk_turn(
    setup_runtime, monkeypatch
):
    from app.infrastructure.xiaox.tools import XiaoxToolBridge

    monkeypatch.setattr(XiaoxToolBridge, "visible_actions", lambda *_: iter(()))
    invoke, _ = setup_runtime
    store = Store()
    store.run.message = "给出库区清单核对方案"
    store.run.metadata.update(
        runtime_requested_deliverable="action_plan",
        runtime_execution_mode="plan",
        plan_delivery_version=1,
    )
    frozen = build_goal_contract(
        store.run,
        context_evidence=[
            {
                "source": "desktop_navigation",
                "entries": [
                    {"id": "inventory", "label": "清单", "breadcrumb": ["库区"], "kind": "page"}
                ],
            }
        ],
    )
    store.run.metadata.update(runtime_goal_contract=frozen, runtime_goal_digest=frozen["digest"])
    raw = '{"plan":{"kind":"steps","steps":[{"kind":"navigation","navigation_id":"inventory","inputs":{}}]}}'
    transport = Transport(store, completed(raw))
    result = await invoke(store, transport, completion_mode="reply")
    assert result["ok"] and result["reply_completed"] and not result["business_completed"]
    assert not result["tool_calls"] and "库区 → 清单" in result["output"]
    assert raw not in result["output"] and len(transport.schemas) == 1
    assert transport.schemas[0]["properties"]["plan"]
    assert '"requested_deliverable": "action_plan"' in transport.inputs[0]


@pytest.mark.asyncio
async def test_unavailable_plan_delivers_safe_observation_without_model_review(
    setup_runtime,
    monkeypatch,
):
    from app.application.agent_runtime.goal_verifier import verify_runtime_goal
    from app.infrastructure.xiaox.tools import XiaoxToolBridge

    # Restore the real early verdict, which must never call a second model on this branch.
    from tests.test_application.test_xiaox_goal_verifier import verify_runtime_goal as actual_review

    assert verify_runtime_goal is not actual_review
    monkeypatch.setattr(
        "app.application.agent_runtime.goal_verifier.verify_runtime_goal", actual_review
    )
    monkeypatch.setattr(XiaoxToolBridge, "visible_actions", lambda *_: iter(()))
    invoke, _ = setup_runtime
    store = Store()
    store.run.message = "给出核对方案"
    store.run.metadata.update(
        runtime_requested_deliverable="action_plan",
        runtime_execution_mode="plan",
        plan_delivery_version=1,
    )
    frozen = build_goal_contract(store.run)
    store.run.metadata.update(runtime_goal_contract=frozen, runtime_goal_digest=frozen["digest"])
    transport = Transport(
        store, completed('{"plan":{"kind":"unavailable","reason":"missing_input"}}')
    )
    result = await invoke(store, transport)
    assert result["execution_state"] == "blocked" and not result["ok"]
    assert "现有资料不足" in result["output"] and not result["tool_calls"]
    assert len(transport.schemas) == 1
