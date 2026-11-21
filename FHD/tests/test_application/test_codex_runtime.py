"""Runtime/ledger boundary tests: model events cannot forge business outcomes."""

from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator.run_models import AgentRun, ToolCall
from app.application.agent_runtime import codex_runtime as runtime
from app.infrastructure.codex import CodexTransportConfig, CodexTransportError
from app.infrastructure.codex.binding import (
    CodexBinding,
    CodexBindingError,
    CodexGrant,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


class Store:
    """In-process substitute only for the durable, separately tested bridge API."""

    def __init__(self, *, rows=None, metadata=None):
        self.run = AgentRun(user_id="71", message="整理销售数据", run_id="run-runtime")
        self.rows = copy.deepcopy(rows or [])
        self.log = []
        self.auth_error = None
        self.child = None
        self.repository = SimpleNamespace(get=self.get_run)
        if metadata is not None:
            self.run.metadata["codex_runtime"] = copy.deepcopy(metadata)

    def get_run(self, run_id):
        return copy.deepcopy(self.run if run_id == self.run.run_id else self.child)

    def get(self, run_id):
        assert run_id == self.run.run_id
        if "codex_runtime" not in self.run.metadata:
            raise CodexBindingError("binding_missing", "no binding yet")
        return CodexBinding(copy.deepcopy(self.run))

    def create(self, run_id, *, runtime_config, **_options):
        self.log.append("create")
        if self.auth_error:
            raise CodexBindingError(self.auth_error, "authority unavailable")
        old = self.run.metadata.get("codex_runtime", {})
        if old.get("coordinator_active"):
            raise CodexBindingError("binding_conflict", "another coordinator owns the run")
        if old.get("runtime_config") and old["runtime_config"] != runtime_config:
            raise CodexBindingError("runtime_changed", "pinned route changed")
        self.run.metadata["codex_runtime"] = {
            **old,
            "generation": old.get("generation", 0) + 1,
            "coordinator_active": True,
            "runtime_config": runtime_config,
            "revoked": False,
        }
        return CodexGrant(self.get(run_id), "mcp-token", "model-token")

    def authenticate(self, token, audience="mcp"):
        assert (token, audience) == ("model-token", "model")
        if self.auth_error:
            raise CodexBindingError(self.auth_error, "authority revoked")
        return self.get(self.run.run_id)

    def record_thread(self, run_id, thread_id, *, generation=None):
        assert generation == self.run.metadata["codex_runtime"]["generation"]
        self.run.metadata["codex_runtime"]["thread_id"] = thread_id
        return self.get(run_id)

    def update(self, run_id, fn):
        current = copy.deepcopy(self.run)
        fn(current, current.metadata["codex_runtime"])
        self.run = current
        return self.get(run_id)

    def receipt_snapshot(self, _run_id):
        return copy.deepcopy(self.rows)

    def close(self, run_id, reason="cancelled", *, generation=None, release_coordinator=True):
        self.log.append("revoke")
        metadata = self.run.metadata["codex_runtime"]
        if generation == metadata["generation"]:
            metadata.update(revoked=True, close_reason=reason)
            if release_coordinator:
                metadata["coordinator_active"] = False
        return self.get(run_id)


def event(method, payload=None, *, thread_id="thread-one", turn_id="turn-one", item_id=None):
    return {
        "method": method,
        "payload": payload or {},
        "thread_id": thread_id,
        "turn_id": turn_id,
        "item_id": item_id,
    }


def completed(text="已整理"):
    return [
        event("turn/started", {"turn": {"id": "turn-one", "status": "inProgress"}}),
        event(
            "item/completed", {"item": {"id": "message-one", "type": "agentMessage", "text": text}}
        ),
        event("turn/completed", {"turn": {"id": "turn-one", "status": "completed"}}),
    ]


class Transport:
    def __init__(self, store, events=None, *, hang=False, error=None):
        self.store = store
        self.events = completed() if events is None else events
        self.hang = hang
        self.error = error
        self.inputs = []
        self.started = []
        self.resumed = []
        self.active = asyncio.Event()
        self.config = None

    def factory(self, config):
        self.config = config
        return self

    async def __aenter__(self):
        self.store.log.append("enter")
        return self

    async def __aexit__(self, *_exc):
        self.store.log.append("exit")

    async def start_thread(self, *, developer_instructions):
        self.started.append(developer_instructions)
        return "thread-one"

    async def resume_thread(self, thread_id, *, developer_instructions):
        self.resumed.append(thread_id)
        return thread_id

    async def stream_turn(self, text):
        self.inputs.append(text)
        self.active.set()
        for item in self.events:
            yield item
        if self.error:
            raise self.error
        if self.hang:
            await asyncio.Event().wait()

    async def interrupt(self):
        self.store.log.append("interrupt")
        assert self.store.run.metadata["codex_runtime"]["revoked"] is True


@pytest.fixture
def setup_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "continuation_conversation_error", lambda *_args: "")
    config = CodexTransportConfig(
        runtime_root=tmp_path.resolve(),
        scope_id="must-be-replaced",
        model="qualified-model",
        provider_url="http://127.0.0.1:41111/v1",
        provider_token="unused-placeholder",
        mcp_url="http://127.0.0.1:41111/mcp",
        mcp_token="unused-placeholder",
        context_window=32000,
        turn_timeout_seconds=30,
    )

    def invoke(store, transport, **kwargs):
        return runtime.run_codex_agent(
            run_id=store.run.run_id,
            task="整理销售数据",
            system_prompt="可信员工说明",
            config=config,
            binding_store=store,
            transport_factory=transport.factory,
            runtime_config={"provider_id": "qualified-provider", "route_identity": "route-v1"},
            **kwargs,
        )

    return invoke, config


def receipt(*, status="completed", verified=True, success=True):
    call = ToolCall(
        step_id="step-child",
        node_id="node-child",
        tool_id="sales",
        action="query",
        status="completed",
        output={"success": True, "row_count": 3},
        call_id="call-child",
    )
    return {
        "call_id": "model-call",
        "tool_id": "sales",
        "action": "query",
        "params": {},
        "state": status,
        "child_task_id": "task-child",
        "child_run_id": "run-child",
        "receipt": {
            "status": status,
            "verified": verified,
            "success": success,
            "tool_calls": [call.to_dict()] if status == "completed" else [],
        },
    }


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


def test_model_completion_without_receipt_cannot_complete_business(setup_runtime):
    invoke, _ = setup_runtime
    store = Store()
    result = asyncio.run(invoke(store, Transport(store, completed("已出库并记账成功"))))
    assert result["ok"] is False and result["business_completed"] is False
    assert result["exit_status"] == "no_business_receipt"
    assert store.run.status == "blocked"


@pytest.mark.parametrize("state", ["waiting_user", "waiting_approval", "pending_approval"])
def test_approval_wait_survives_turn_completion(setup_runtime, state):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt(status=state, verified=False, success=False)])
    result = asyncio.run(invoke(store, Transport(store)))
    assert result["ok"] is False and result["pending_approval"] is True
    assert store.run.status == "waiting_user"
    assert store.run.metadata["codex_runtime"]["coordinator_active"] is False


def test_verified_child_receipts_are_projected_not_fabricated(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt(), {**receipt(), "call_id": "duplicate-model-call"}])
    store.run.metadata["runtime_expected_operations"] = [
        {"tool_id": "sales", "action": "query", "params": {}}
    ]
    result = asyncio.run(invoke(store, Transport(store)))
    assert result["ok"] is True and result["business_completed"] is True
    assert len(store.run.tool_calls) == 1
    projected = store.run.tool_calls[0]
    assert projected.output == {"success": True, "row_count": 3}
    assert projected.metadata["child_run_id"] == "run-child"
    assert projected.metadata["child_call_id"] == "call-child"
    assert result["run_events"][-1]["event_type"] == "runtime.codex.finished"


def test_verified_operations_do_not_prove_an_unfrozen_multi_goal_task(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt()])
    result = asyncio.run(invoke(store, Transport(store, completed("已全部完成"))))
    assert result["verified_operations"] is True and result["business_completed"] is False
    assert result["exit_status"] == "goal_verification_required"
    assert result["output"] == "已核验 1 项操作，整体目标尚待核对。"
    assert result["session_messages"][-1]["content"] == result["output"]
    assert store.run.status == "blocked"


def test_reply_with_verified_actions_never_claims_business_completion(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt()])
    result = asyncio.run(invoke(store, Transport(store), completion_mode="reply"))
    assert result["ok"] is True and result["verified_operations"] is True
    assert result["exit_status"] == "reply_completed" and result["business_completed"] is False
    stored = store.run.final_output["codex_result"]
    assert stored["verified_operations"] is True and stored["business_completed"] is False
    assert stored["exit_status"] == "reply_completed"


@pytest.mark.parametrize("verified", [False, True])
@pytest.mark.parametrize("envelope", ["codex_result", "chat_payload"])
def test_sql_business_harness_preserves_reply_success_without_inventing_business_success(
    trusted_actor, verified, envelope
):
    from app.application.agent_orchestrator.business_harness import ensure_terminal_business_result
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.agent_runtime.chat import runtime_chat_payload

    actor = trusted_actor()
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    run = AgentRun(user_id=str(actor.user_id), message="创建销售订单", status="completed")
    result = {
        "runtime": "codex",
        "run_id": run.run_id,
        "ok": True,
        "exit_status": "reply_completed",
        "execution_state": "completed",
        "output": "模型自行声称业务全部完成",
        "business_completed": False,
        "verified_operations": verified,
        "reply_completed": True,
    }
    run.final_output[envelope] = (
        result if envelope == "codex_result" else runtime_chat_payload(result)
    )
    repository.save(run)  # Run the actual save-time Business Harness, not a stub.
    saved = repository.get(run.run_id)
    business = ensure_terminal_business_result(saved)
    assert saved.status == "completed"
    assert business["status"] == "reply_completed" and business["success"] is False
    assert business["business_completed"] is False and business["verified_operations"] is verified
    assert "业务全部完成" not in business["summary"] and business["summary"] != "已完成"
    assert (
        saved.final_output[envelope].get("ok", saved.final_output[envelope].get("success")) is True
    )


def test_business_harness_honors_a_verified_complete_workflow_but_not_stale_reply_projection(
    setup_runtime,
):
    from app.application.agent_orchestrator.business_harness import ensure_terminal_business_result

    invoke, _ = setup_runtime
    store = Store(rows=[receipt()])
    store.run.metadata["runtime_expected_operations"] = [
        {"tool_id": "sales", "action": "query", "params": {}}
    ]
    result = asyncio.run(invoke(store, Transport(store)))
    business = ensure_terminal_business_result(store.run)
    assert result["business_completed"] is True and business["success"] is True
    assert business["summary"] == result["output"]
    store.run.final_output["codex_result"].update(
        business_completed=False, exit_status="reply_completed"
    )
    corrected = ensure_terminal_business_result(store.run)
    assert corrected["status"] == "reply_completed" and corrected["success"] is False


def test_multiple_frozen_actions_still_need_a_root_goal_graph(setup_runtime):
    invoke, _ = setup_runtime
    extra = {**receipt(), "child_run_id": "another-child", "params": {"month": "May"}}
    store = Store(rows=[receipt(), extra])
    store.run.metadata["runtime_expected_operations"] = [
        {key: row[key] for key in ("tool_id", "action", "params")} for row in store.rows
    ]
    result = asyncio.run(invoke(store, Transport(store)))
    assert result["verified_operations"] is True and result["business_completed"] is False
    assert result["exit_status"] == "goal_verification_required"


@pytest.mark.parametrize("state", ["reserved", "unknown"])
def test_unsettled_model_request_blocks_resume_before_proxy_marks_reconciliation(
    setup_runtime, state
):
    invoke, _ = setup_runtime
    store = Store(metadata={"model_requests": {"request-one": {"state": state}}})
    transport = Transport(store)
    result = asyncio.run(invoke(store, transport, completion_mode="reply"))
    assert result["reconciliation_required"] is True and transport.inputs == []
    assert "create" not in store.log


def test_active_time_budget_is_shared_across_turns_but_excludes_approval_wait(
    setup_runtime, monkeypatch
):
    invoke, _ = setup_runtime
    now = [100.0]
    monkeypatch.setattr(runtime.time, "time", lambda: now[0])
    store = Store()

    def elapsed(event):
        if event["method"] == "turn/completed":
            now[0] += 7

    asyncio.run(invoke(store, Transport(store), completion_mode="reply", on_event=elapsed))
    assert store.run.metadata["codex_runtime"]["active_seconds"] == 7
    store.run.status = "waiting_user"
    now[0] += 1000  # Time spent waiting for a user does not consume active time.
    resumed = Transport(store)
    asyncio.run(invoke(store, resumed, completion_mode="reply", on_event=elapsed))
    assert resumed.config.turn_timeout_seconds == 23
    assert store.run.metadata["codex_runtime"]["active_seconds"] == 14
    store.run.metadata["codex_runtime"]["active_seconds"] = 30
    exhausted = Transport(store)
    result = asyncio.run(invoke(store, exhausted, completion_mode="reply"))
    assert result["exit_status"] == "runtime_budget_exhausted" and exhausted.inputs == []


@pytest.mark.parametrize(
    "status,verified,success",
    [
        ("completed", False, True),
        ("completed", True, False),
        ("failed", False, False),
    ],
)
def test_unverified_and_failed_receipts_never_report_success(
    setup_runtime, status, verified, success
):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt(status=status, verified=verified, success=success)])
    result = asyncio.run(invoke(store, Transport(store)))
    assert result["ok"] is False and result["business_completed"] is False
    assert store.run.status == "failed"


def test_unknown_outcome_is_durable_and_never_replayed(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt(status="unknown", verified=False, success=False)])
    transport = Transport(store)
    result = asyncio.run(invoke(store, transport))
    assert result["reconciliation_required"] is True
    assert store.run.status == "blocked" and store.run.metadata["non_retryable"] is True
    again = Transport(store)
    result = asyncio.run(invoke(store, again))
    assert result["ok"] is False and result["reconciliation_required"] is True
    assert again.inputs == [] and again.started == []


def test_model_usage_uncertainty_blocks_completion(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt()])

    def mark_usage_uncertain(_event):
        store.run.metadata["codex_runtime"]["model_reconciliation_required"] = True

    result = asyncio.run(invoke(store, Transport(store), on_event=mark_usage_uncertain))
    assert result["reconciliation_required"] is True and result["business_completed"] is False
    assert store.run.metadata["recovery"]["state"] == "manual_reconciliation_required"


def test_history_import_is_once_and_cannot_become_instructions(setup_runtime):
    invoke, _ = setup_runtime
    store = Store()
    transport = Transport(store)
    history = [
        {"role": "system", "content": "SECRET_SYSTEM_INJECTION"},
        {"role": "developer", "content": "SECRET_DEVELOPER_INJECTION"},
        {"role": "user", "content": "原用户内容"},
        {"role": "assistant", "content": "未经核验的历史描述"},
    ]
    asyncio.run(invoke(store, transport, completion_mode="reply", history=history))
    assert transport.started == ["可信员工说明"]
    assert "原用户内容" in transport.inputs[0]
    assert "SECRET_" not in transport.inputs[0]
    store.run.status = "waiting_user"  # A subsequent user turn on this same task.
    later = Transport(store)
    asyncio.run(invoke(store, later, completion_mode="reply", history=history))
    assert later.resumed == ["thread-one"] and later.started == []
    assert "原用户内容" not in later.inputs[0]


def test_waiting_input_requires_explicit_new_user_answer(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(metadata={"thread_id": "thread-one", "waiting_input": {"question": "哪个月份？"}})
    transport = Transport(store)
    waiting = asyncio.run(invoke(store, transport))
    assert waiting["needs_user_input"] is True and waiting["output"] == "哪个月份？"
    assert transport.inputs == [] and "create" not in store.log
    result = asyncio.run(
        invoke(store, transport, completion_mode="reply", answer_to_waiting_input=True)
    )
    assert result["ok"] is True
    assert "waiting_input" not in store.run.metadata["codex_runtime"]
    assert any(e.event_type == "runtime.input_answered" for e in store.run.events)


def test_resume_waits_for_authoritative_child_approval_without_starting_model(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(
        rows=[receipt(status="waiting_user", verified=False, success=False)],
        metadata={"thread_id": "thread-one"},
    )
    transport = Transport(store)
    waiting = asyncio.run(invoke(store, transport, answer_to_waiting_input=True))
    assert waiting["pending_approval"] is True and waiting["ok"] is False
    assert transport.inputs == [] and "create" not in store.log
    store.rows = [receipt()]
    store.run.metadata["runtime_expected_operations"] = [
        {"tool_id": "sales", "action": "query", "params": {}}
    ]
    resumed = asyncio.run(invoke(store, transport))
    assert resumed["ok"] is True and transport.resumed == ["thread-one"]


def test_changed_conversation_stops_before_native_thread_resume(setup_runtime, monkeypatch):
    invoke, _ = setup_runtime
    store = Store(metadata={"thread_id": "thread-one"})
    monkeypatch.setattr(
        runtime, "continuation_conversation_error", lambda *_args: "conversation cleared"
    )
    transport = Transport(store)
    result = asyncio.run(invoke(store, transport))
    assert result["ok"] is False and transport.resumed == []
    assert "create" not in store.log


def test_route_change_and_concurrent_owner_do_not_revoke_other_grants(setup_runtime):
    invoke, _ = setup_runtime
    for metadata in (
        {"runtime_config": {"provider_id": "another-provider"}},
        {"coordinator_active": True},
    ):
        store = Store(metadata=metadata)
        result = asyncio.run(invoke(store, Transport(store)))
        assert result["ok"] is False
        assert "revoke" not in store.log and "enter" not in store.log


def test_coordinator_lease_is_held_until_authoritative_terminal_projection(setup_runtime):
    invoke, _ = setup_runtime
    store = Store()
    snapshots = []
    original = store.receipt_snapshot

    def snapshot(run_id):
        metadata = store.run.metadata["codex_runtime"]
        if metadata.get("revoked"):
            with pytest.raises(CodexBindingError) as caught:
                store.create(run_id, runtime_config=metadata["runtime_config"])
            assert caught.value.code == "binding_conflict"
            snapshots.append(True)
        return original(run_id)

    store.receipt_snapshot = snapshot
    result = asyncio.run(invoke(store, Transport(store), completion_mode="reply"))
    assert result["ok"] is True and snapshots == [True]
    assert store.run.metadata["codex_runtime"]["coordinator_active"] is False


def test_transport_loss_does_not_restart_or_fallback(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt(status="unknown", verified=False, success=False)])
    transport = Transport(
        store,
        events=completed()[:1],
        error=CodexTransportError("codex_connection_lost", "lost", outcome_unknown=True),
    )
    result = asyncio.run(invoke(store, transport))
    assert result["ok"] is False and result["reconciliation_required"] is True
    assert len(transport.inputs) == 1 and len(transport.started) == 1
    assert store.log.index("revoke") < store.log.index("interrupt") < store.log.index("exit")


def test_cancel_revokes_before_interrupt_and_preserves_child_uncertainty(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt(status="unknown", verified=False, success=False)])
    transport = Transport(store, events=completed()[:1], hang=True)

    async def scenario():
        running = asyncio.create_task(invoke(store, transport))
        await transport.active.wait()
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running

    asyncio.run(scenario())
    assert store.log.index("revoke") < store.log.index("interrupt") < store.log.index("exit")
    assert store.run.status == "cancelled" and store.run.metadata["non_retryable"] is True
    assert store.run.final_output["codex_result"]["reconciliation_required"] is True


def test_controlled_cancellation_preserves_new_unknown_receipts_on_already_cancelled_parent(
    setup_runtime,
):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt(status="unknown", verified=False, success=False)])

    def cancelled_by_control(_event):
        store.run.status = "cancelled"
        store.auth_error = "cancelled"

    result = asyncio.run(invoke(store, Transport(store), on_event=cancelled_by_control))
    assert result["ok"] is False and result["execution_state"] == "cancelled"
    assert store.run.status == "cancelled" and store.run.metadata["non_retryable"] is True
    assert store.run.final_output["codex_result"]["reconciliation_required"] is True


def test_authority_revocation_is_observed_even_when_stream_is_idle(setup_runtime, monkeypatch):
    invoke, _ = setup_runtime
    monkeypatch.setattr(runtime, "_CONTROL_POLL_SECONDS", 0.001)
    store = Store()
    transport = Transport(store, events=completed()[:1], hang=True)

    async def scenario():
        running = asyncio.create_task(invoke(store, transport))
        await transport.active.wait()
        store.auth_error = "owner_changed"
        return await asyncio.wait_for(running, 1)

    result = asyncio.run(scenario())
    assert result["ok"] is False and result["error_code"] == "owner_changed"
    assert store.log.index("revoke") < store.log.index("interrupt")


def test_foreign_thread_event_cannot_complete_this_run(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt()])
    transport = Transport(
        store,
        events=[event("turn/completed", {"turn": {"status": "completed"}}, thread_id="foreign")],
    )
    result = asyncio.run(invoke(store, transport))
    assert result["ok"] is False and result["business_completed"] is False
    assert result["error_code"] == "binding_conflict"


def test_final_message_replaces_delta_and_requires_terminal_event(setup_runtime):
    invoke, _ = setup_runtime
    store = Store()
    events = [
        completed()[0],
        event("item/agentMessage/delta", {"delta": "收"}, item_id="message-one"),
        *completed("收到")[1:],
    ]
    result = asyncio.run(invoke(store, Transport(store, events), completion_mode="reply"))
    assert result["output"] == "收到"
    incomplete = Store()
    result = asyncio.run(
        invoke(incomplete, Transport(incomplete, completed("收到")[:-1]), completion_mode="reply")
    )
    assert result["ok"] is False
