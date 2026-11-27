"""Real SQL queue admission, lease fencing and fixed-runtime recovery boundaries."""

from __future__ import annotations

import asyncio
import copy
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import OperationalError

from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher
from app.application.agent_runtime import gateway
from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest
from app.infrastructure.xiaox.binding import XiaoxBindingStore
from app.infrastructure.xiaox.queued_runtime import execute_queued_runtime
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.xiaox_http_runtime import runtime_entry as runtime_entry


def create(state, request_id="queued-request"):
    response = state.client.post(
        "/api/agent/runs", json={"message": "解释库存含义", "request_id": request_id}
    )
    assert response.status_code == 202, response.text
    assert response.json()["data"]["status"] == "queued"
    return response.json()["data"]["run_id"]


def worker(state, execution, owner):
    AgentTaskDispatcher(
        execution_repository=state.queue, run_repository=state.repository
    )._execute_claim(execution, owner)


def expire(state, run_id):
    from app.db.models.agent import AgentTaskExecutionRecord

    with state.actor.factory.begin() as db:
        row = db.get(AgentTaskExecutionRecord, run_id)
        row.lease_expires_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()


@pytest.mark.parametrize("uncertain", [False, True])
def test_qualification_receipt_only_claims_not_started_when_certain(uncertain):
    from app.application.agent_runtime.chat import runtime_chat_payload

    payload = runtime_chat_payload(
        {
            "ok": False,
            "execution_state": "blocked",
            "failure_stage": "runtime_setup",
            "error_code": "runtime_qualification_evidence_missing",
            "reconciliation_required": uncertain,
        }
    )
    assert payload.get("execution_started") is (None if uncertain else False)
    assert ("未通过运行验收" in payload["response"]) is not uncertain
    assert payload["requires_reconciliation"] is uncertain


@pytest.mark.parametrize("publication", ["completed", "interrupted", "old_history", "old_dedup"])
def test_claimed_queue_worker_settles_chat_without_a_view(runtime_entry, monkeypatch, publication):
    from app.application.agent_runtime.chat import runtime_chat_payload
    from app.application.ai_chat.conversation_history import (
        persist_chat_turn,
        reconcile_queued_chat_reply,
    )
    from app.application.task_conversation_store import task_conversation_store
    from app.db.models import AIConversation
    from app.infrastructure.tenant_scope import tenant_scope
    from app.infrastructure.xiaox.queued_runtime import _ClaimedRuntimeRepository

    state = runtime_entry
    monkeypatch.setattr(
        "app.domain.shared_services.conversation_service.notify_user", lambda **_: None
    )
    context = {
        **state.actor.context,
        "local_user_id": state.actor.user_id,
        "conversation_id": "queued-chat",
        "turn_id": "scoped-queued-chat",
        "_conversation_revision": 0,
    }
    task_conversation_store.prepare_revision(session_id="queued-chat", user_id=state.actor.user_id)
    message = "解释库存含义"
    request = {
        "task": message,
        "system_prompt": "回答问题",
        "runtime_context": context,
        "completion_mode": "reply",
        "start_queued": True,
    }
    queued = gateway.run_runtime_task(**request)
    assert queued.get("execution_state") == "queued", queued.get("error_code")
    ack = persist_chat_turn(
        str(state.actor.user_id), message, context, runtime_chat_payload(queued)
    )

    run_id = queued["run_id"]
    if publication != "completed":

        async def interrupted(**kwargs):
            state.calls.append(kwargs)
            store = kwargs["binding_store"]
            grant = store.create(run_id, runtime_config=kwargs["runtime_config"])

            def commit_unknown(parent, binding):
                parent.status = "blocked"
                parent.metadata.update(
                    non_retryable=True, recovery={"state": "manual_reconciliation_required"}
                )
                binding.update(
                    runtime_status="interrupted", model_requests={"unsettled": {"state": "unknown"}}
                )
                parent.final_output["xiaox_result"] = {
                    "run_id": run_id,
                    "ok": False,
                    "exit_status": "unknown",
                    "execution_state": "unknown",
                    "reconciliation_required": True,
                    "failure_kind": "model_usage_unknown",
                }

            store.update(run_id, commit_unknown)
            store.close(run_id, "interrupted", generation=grant.binding.metadata["generation"])
            raise asyncio.CancelledError

        monkeypatch.setattr(gateway, "run_xiaox_agent", interrupted)

    if publication.startswith("old_"):
        execution = state.queue.claim("legacy-worker", lease_seconds=120)
        run = state.repository.get(run_id)
        pending = run.metadata["_xiaox_queued_request"]
        with pytest.raises(asyncio.CancelledError):
            gateway.run_runtime_task(
                **{
                    **request,
                    "start_queued": False,
                    "runtime_context": {**context, "turn_id": pending["worker_turn_id"]},
                    "run_id": run_id,
                    "_repository": _ClaimedRuntimeRepository(
                        state.repository, execution, "legacy-worker"
                    ),
                }
            )
        assert state.queue.get(run_id).lease_owner == "legacy-worker"
        assert not reconcile_queued_chat_reply(context, context["turn_id"], run_id)
        duplicate = gateway.run_runtime_task(**request)
        assert duplicate["deduplicated"] is True and duplicate["execution_state"] == "queued"
        assert (
            state.repository.get(run_id).metadata["runtime_requests"][pending["request_key"]][
                "state"
            ]
            == "queued"
        )
        state.queue.finish(
            run_id, "legacy-worker", "failed", execution_count=execution.execution_count
        )
        assert not reconcile_queued_chat_reply(
            {**context, "tenant_id": 999}, context["turn_id"], run_id
        )
        if publication == "old_dedup":
            assert gateway.run_runtime_task(**request)["reconciliation_required"] is True
        timestamp = None
        for _ in range(2):
            with tenant_scope(state.actor.tenant_id):
                history = task_conversation_store.get_history(
                    session_id="queued-chat",
                    user_id=state.actor.user_id,
                    turn_id=context["turn_id"],
                )
            assert history["turn_receipt"]["requires_reconciliation"] is True
            assert history["turn_receipt"]["message_id"] == ack["message_ids"][1]
            run = state.repository.get(run_id)
            returned = run.metadata["runtime_requests"][pending["request_key"]]
            assert returned["state"] == "returned" and returned["returned_at"]
            snapshot = (run.updated_at, returned["returned_at"])
            if timestamp is None:
                timestamp = snapshot
            else:
                assert timestamp == snapshot
    else:
        run = state.drain(run_id)

    pending = run.metadata["_xiaox_queued_request"]
    receipt = run.metadata["runtime_requests"][pending["request_key"]]
    if publication == "completed":
        assert run.status == "completed"
        assert receipt["state"] == "returned"
        reply = "库存表示可用产品的数量。"
    else:
        assert run.status == "blocked"
        if publication == "interrupted":
            assert receipt["state"] == "returned" and receipt["returned_at"]
            assert state.queue.get(run_id).last_error_code == "needs_verification"
        duplicate = gateway.run_runtime_task(**request)
        assert duplicate["deduplicated"] is True and duplicate["execution_state"] == "unknown"
        assert duplicate["reconciliation_required"] is True
        assert len(state.calls) == 1
        reply = runtime_chat_payload(duplicate)["response"]
    with state.actor.factory() as db:
        rows = db.query(AIConversation).order_by(AIConversation.id).all()
        assert [row.id for row in rows] == ack["message_ids"]
        assert [(row.role, row.content) for row in rows] == [
            ("user", message),
            ("assistant", reply),
        ]


@pytest.mark.parametrize("legacy_unstarted", [False, True])
def test_http_queue_request_and_worker_turn_have_separate_stable_identities(
    runtime_entry, legacy_unstarted
):
    state = runtime_entry
    run_id = create(state)
    saved = state.repository.get(run_id)
    pending = saved.metadata["_xiaox_queued_request"]
    original = canonical_digest({"turn_id": "queued-request", "owner": saved.user_id})
    worker_id = canonical_digest({"turn_id": pending["worker_turn_id"], "owner": saved.user_id})
    assert pending["request_key"] == original and worker_id != original
    assert saved.metadata["xiaox_runtime"]["generation"] == 0
    assert state.calls == state.servers == []
    duplicate = state.client.post(
        "/api/agent/runs", json={"message": "解释库存含义", "request_id": "queued-request"}
    )
    assert duplicate.status_code == 202
    assert duplicate.json()["runtime_result"]["deduplicated"] is True
    assert state.queue.get(run_id).execution_count == 0
    state.drain(run_id)
    saved = state.repository.get(run_id)
    assert saved.metadata["xiaox_runtime"]["version"] == 1
    assert set(saved.metadata["runtime_requests"]) == {original, worker_id}
    assert saved.metadata["runtime_requests"][original]["result"]["ok"] is True
    assert len(state.calls) == 1 and state.queue.get(run_id).state == "succeeded"


@pytest.mark.parametrize("qualified_at_execution", [False, True])
def test_queue_admission_needs_no_qualification_but_worker_still_requires_it(
    runtime_entry, qualified_at_execution
):
    state = runtime_entry
    qualification = state.settings.qualification_file.read_text()
    state.settings.qualification_file.unlink()
    run_id = create(state)
    saved = state.repository.get(run_id)
    assert saved.metadata["runtime_route"] == state.settings.route.runtime_identity()
    assert state.calls == state.servers == []
    if qualified_at_execution:
        state.settings.qualification_file.write_text(qualification)
    state.drain(run_id)
    if qualified_at_execution:
        assert len(state.calls) == 1 and state.calls[0]["run_id"] == run_id
        assert state.queue.get(run_id).state == "succeeded"
    else:
        assert state.calls == state.servers == []
        assert state.queue.get(run_id).last_error_code == "runtime_policy_blocked"
        assert state.repository.get(run_id).final_output["xiaox_result"]["run_id"] == run_id


@pytest.mark.parametrize("programming_error", [False, True])
def test_failed_queue_insert_rolls_back_the_parent_admission(
    runtime_entry, monkeypatch, programming_error
):
    state = runtime_entry
    error = (
        RuntimeError("synthetic queue write failure")
        if programming_error
        else OperationalError("INSERT INTO agent_task_executions", {}, OSError("queue unavailable"))
    )

    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(state.queue, "enqueue_in_session", fail)
    payload = {"message": "解释库存含义", "request_id": "failed-insert"}
    if programming_error:
        with pytest.raises(RuntimeError) as raised:
            state.client.post("/api/agent/runs", json=payload)
        assert raised.value is error
    else:
        response = state.client.post("/api/agent/runs", json=payload)
        assert response.status_code == 409
    assert state.repository.list_recent() == []
    assert state.calls == state.servers == []


@pytest.mark.parametrize("action", ["pause", "cancel"])
def test_control_after_claim_does_not_let_generation_zero_start(runtime_entry, action):
    state = runtime_entry
    run_id = create(state)
    execution = state.queue.claim("stale-worker", lease_seconds=120)
    assert execution is not None
    controlled = state.client.post(f"/api/agent/runs/{run_id}/{action}")
    assert controlled.status_code == 200, controlled.text
    worker(state, execution, "stale-worker")
    saved = state.repository.get(run_id)
    assert saved.status == ("paused" if action == "pause" else "cancelled")
    assert saved.metadata["xiaox_runtime"]["generation"] == 0
    assert state.calls == state.servers == []


def test_revoked_actor_is_rechecked_before_starting_a_queued_runtime(runtime_entry):
    from app.db.models.user import Session as UserSession

    state = runtime_entry
    run_id = create(state)
    execution = state.queue.claim("revoked-worker", lease_seconds=120)
    with state.actor.factory.begin() as db:
        db.delete(db.get(UserSession, state.actor.session_row_id))
    worker(state, execution, "revoked-worker")
    saved = state.repository.get(run_id)
    assert saved.status == "blocked"
    assert saved.metadata["xiaox_runtime"]["generation"] == 0
    assert state.queue.get(run_id).last_error_code == "owner_changed"
    assert state.calls == state.servers == []


def test_pause_before_worker_admission_can_resume_without_discarding_the_parent(runtime_entry):
    state = runtime_entry
    run_id = create(state)
    assert state.client.post(f"/api/agent/runs/{run_id}/pause").status_code == 200
    resumed = state.client.post(
        f"/api/agent/runs/{run_id}/resume", json={"request_id": "resume-unstarted"}
    )
    assert resumed.status_code == 202, resumed.text
    assert state.calls == state.servers == []
    assert state.drain(run_id).status == "completed"
    assert len(state.calls) == 1 and len(state.repository.list_recent()) == 1


def test_expired_claim_cannot_admit_a_turn_and_fresh_claim_recovers_generation_zero(runtime_entry):
    state = runtime_entry
    run_id = create(state)
    old = state.queue.claim("old-worker", lease_seconds=120)
    expire(state, run_id)
    worker(state, old, "old-worker")
    assert state.calls == state.servers == []
    assert state.repository.get(run_id).metadata["xiaox_runtime"]["generation"] == 0
    fresh = state.queue.claim("new-worker", lease_seconds=120)
    assert fresh.recovery_count == 1 and fresh.execution_count == 2
    worker(state, fresh, "new-worker")
    assert state.repository.get(run_id).status == "completed"
    assert state.queue.get(run_id).state == "succeeded" and len(state.calls) == 1


@pytest.mark.parametrize("queue_result_saved", [False, True])
def test_lost_queue_finish_reads_returned_runtime_result_without_another_turn(
    runtime_entry, queue_result_saved
):
    from app.infrastructure.xiaox.queued_runtime import _ClaimedRuntimeRepository

    state = runtime_entry
    run_id = create(state)
    first = state.queue.claim("first-worker", lease_seconds=120)
    if queue_result_saved:
        result = execute_queued_runtime(state.repository, first, "first-worker")
    else:
        # The gateway persisted its result, then the worker died before publishing
        # that result back to the original queued HTTP request.
        parent = state.repository.get(run_id)
        result = gateway.run_runtime_task(
            run_id=run_id,
            task=parent.message,
            system_prompt=parent.metadata["_xiaox_system_prompt"],
            runtime_context={
                **parent.metadata["runtime_context"],
                "turn_id": parent.metadata["_xiaox_queued_request"]["worker_turn_id"],
            },
            completion_mode="auto",
            _repository=_ClaimedRuntimeRepository(state.repository, first, "first-worker"),
        )
    assert result["ok"] is True and len(state.calls) == 1
    # Simulate process loss after the durable runtime result, before queue.finish.
    expire(state, run_id)
    recovered = state.queue.claim("recovery-worker", lease_seconds=120)
    worker(state, recovered, "recovery-worker")
    assert len(state.calls) == 1
    assert state.queue.get(run_id).state == "succeeded"


@pytest.mark.parametrize("unsettled", ["model", "business", "admitted"])
def test_lost_worker_with_unconfirmed_receipt_never_replays(runtime_entry, unsettled):
    state = runtime_entry
    run_id = create(state)
    original = state.queue.claim("lost-worker", lease_seconds=120)
    saved = state.repository.get(run_id)
    pending = saved.metadata["_xiaox_queued_request"]
    worker_key = canonical_digest({"turn_id": pending["worker_turn_id"], "owner": saved.user_id})
    saved.metadata["runtime_requests"][worker_key] = {"state": "admitted", "digest": "test-only"}
    if unsettled == "model":
        saved.metadata["xiaox_runtime"]["model_requests"] = {"unfinished": {"state": "reserved"}}
    elif unsettled == "business":
        saved.metadata["xiaox_runtime"]["calls"] = {"unfinished": {"state": "claimed"}}
    state.repository.save(saved)
    expire(state, run_id)
    recovered = state.queue.claim("recovery-worker", lease_seconds=120)
    assert recovered.execution_count == original.execution_count + 1
    worker(state, recovered, "recovery-worker")
    saved = state.repository.get(run_id)
    assert saved.status == "blocked" and saved.metadata["non_retryable"] is True
    assert saved.final_output["xiaox_result"]["reconciliation_required"] is True
    assert state.queue.get(run_id).state == "failed"
    assert state.queue.get(run_id).last_error_code == "needs_verification"
    assert state.calls == state.servers == []


def test_pending_child_result_parks_the_queue_instead_of_reporting_worker_failure(
    runtime_entry, monkeypatch
):
    state = runtime_entry

    async def pending_child(**kwargs):
        state.calls.append(kwargs)
        return {
            "ok": False,
            "run_id": kwargs["run_id"],
            "execution_state": "running",
            "exit_status": "running",
        }

    monkeypatch.setattr(gateway, "run_xiaox_agent", pending_child)
    run_id = create(state)
    state.drain(run_id)
    assert state.repository.get(run_id).status == "running"
    execution = state.queue.get(run_id)
    assert execution.state == "waiting_approval" and execution.last_error_code == ""


def test_answer_queued_for_same_parent_preserves_new_input_and_original_scope(
    runtime_entry, monkeypatch
):
    state = runtime_entry
    first_runtime = gateway.run_xiaox_agent

    async def ask(**kwargs):
        state.calls.append(kwargs)
        store = kwargs["binding_store"]
        grant = store.create(kwargs["run_id"], runtime_config=kwargs["runtime_config"])

        def waiting(run, metadata):
            run.status = "waiting_user"
            metadata["waiting_input"] = {"question": "请补充附件"}

        store.update(kwargs["run_id"], waiting)
        store.close(kwargs["run_id"], "completed", generation=grant.binding.metadata["generation"])
        return {
            "ok": False,
            "run_id": kwargs["run_id"],
            "execution_state": "waiting_user",
            "exit_status": "waiting_user",
        }

    monkeypatch.setattr(gateway, "run_xiaox_agent", ask)
    run_id = create(state)
    state.drain(run_id)
    original_context = copy.deepcopy(state.repository.get(run_id).metadata["runtime_context"])
    monkeypatch.setattr(gateway, "run_xiaox_agent", first_runtime)
    reply = state.client.post(
        f"/api/agent/runs/{run_id}/resume",
        json={
            "request_id": "answer-request",
            "message": "使用新附件",
            "attachment_upload_ids": ["new-upload"],
        },
    )
    assert reply.status_code == 202, reply.text
    assert len(state.calls) == 1
    queued = state.repository.get(run_id)
    assert queued.metadata["_xiaox_queued_request"]["input_data"]["attachment_upload_ids"] == [
        "new-upload"
    ]
    assert queued.metadata["runtime_context"] == original_context
    state.drain(run_id)
    assert len(state.calls) == 2
    assert state.calls[-1]["answer_to_waiting_input"] is True
    assert state.calls[-1]["input_data"]["attachment_upload_ids"] == ["new-upload"]
    assert state.calls[-1]["task"] == "使用新附件"
    assert len(state.repository.list_recent()) == 1


@pytest.mark.parametrize("tamper", ["unbound", "tenant", "owner", "parent", "mod"])
def test_parent_queue_claim_does_not_authorize_forged_or_foreign_children(runtime_entry, tamper):
    from app.application.agent_orchestrator.business_write_guard import worker_claim_scope
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.application.agent_orchestrator.tool_permission import begin_idempotent_replay
    from app.application.agent_orchestrator.worker_repository import WorkerLeaseLost

    state = runtime_entry
    run_id = create(state)
    execution = state.queue.claim("parent-worker", lease_seconds=120)
    child = AgentRun(user_id=str(state.actor.user_id), message="test child", run_id="bound-child")
    child.metadata["runtime_context"] = {**state.actor.context, "parent_run_id": run_id}
    if tamper == "tenant":
        child.metadata["runtime_context"]["tenant_id"] = "999"
    elif tamper == "owner":
        child.user_id = "999"
    elif tamper == "parent":
        child.metadata["runtime_context"]["parent_run_id"] = "forged-parent"
    elif tamper == "mod":
        child.metadata["runtime_context"]["_mod_authorization"] = {"mod_id": "foreign-mod"}
    state.repository.save(child)
    parent = state.repository.get(run_id)
    if tamper != "unbound":
        parent.metadata["xiaox_runtime"]["calls"] = {"bound": {"child_run_id": child.run_id}}
    state.repository.save(parent)
    with (
        worker_claim_scope(state.repository, execution, "parent-worker"),
        pytest.raises(WorkerLeaseLost),
    ):
        begin_idempotent_replay(
            {"run_id": child.run_id, "parent_run_id": run_id},
            "products",
            "query",
            {"keyword": "test"},
        )


@pytest.mark.parametrize(
    "marker",
    ["intent", "runtime_type", "ledger", "queue", "result", "prompt", "input", "history"],
)
def test_legacy_queue_never_enters_generic_executor(runtime_entry, marker):
    state = runtime_entry
    run_id = create(state)
    saved = state.repository.get(run_id)
    if marker == "intent":
        saved.intent = "codex.runtime"
    elif marker == "runtime_type":
        saved.metadata["runtime_type"] = "codex"
    elif marker == "ledger":
        saved.metadata["codex_runtime"] = {"calls": {"old": {"state": "unknown"}}}
    elif marker == "queue":
        saved.metadata["_codex_queued_request"] = {"state": "queued"}
    elif marker == "prompt":
        saved.metadata["_codex_system_prompt"] = ""
    elif marker == "input":
        saved.metadata["_codex_input_data"] = None
    elif marker == "history":
        saved.metadata["_codex_history"] = []
    else:
        saved.final_output["codex_result"] = {"output": "original receipt"}
    state.repository.save(saved)
    original = state.repository.get(run_id).to_dict()
    execution = state.queue.claim("legacy-worker", lease_seconds=120)
    assert execution is not None

    def forbidden(*_args, **_kwargs):
        pytest.fail("unreconciled legacy runtime entered generic executor")

    dispatcher = AgentTaskDispatcher(
        execution_repository=state.queue, run_repository=state.repository
    )
    dispatcher._orchestrator_factory = forbidden
    dispatcher._execute_claim(execution, "legacy-worker")
    assert state.repository.get(run_id).to_dict() == original
    assert state.queue.get(run_id).last_error_code == "needs_verification"
    assert state.calls == state.servers == []


def test_legacy_source_cannot_skip_parent_receipt_validation():
    from app.infrastructure.xiaox.receipts import action_parent

    with pytest.raises(PermissionError, match="来源校验"):
        action_parent({"source": "codex_runtime", "parent_run_id": "old"})
