"""Real SQL delivery recovery, original-turn identity and Host/Mod write fences."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import OperationalError

from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher
from app.application.agent_runtime import gateway
from tests.fixtures.backend_ci_isolation import conversation_storage as conversation_storage
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.xiaox_http_runtime import runtime_entry as runtime_entry
from tests.test_application.test_xiaox_queued_runtime import create


def queue_chat(state, monkeypatch, session_id="delivery-restart"):
    from app.application.agent_runtime.chat import runtime_chat_payload
    from app.application.ai_chat.conversation_history import persist_chat_turn
    from app.application.task_conversation_store import TaskConversationStore

    context = {
        **state.actor.context,
        "local_user_id": state.actor.user_id,
        "conversation_id": session_id,
        "turn_id": f"{session_id}-turn",
        "_conversation_revision": 0,
    }
    monkeypatch.setattr(
        "app.domain.shared_services.conversation_service.notify_user", lambda **_: None
    )
    TaskConversationStore().prepare_revision(session_id=session_id, user_id=state.actor.user_id)
    queued = gateway.run_runtime_task(
        task="解释库存含义",
        system_prompt="回答问题",
        runtime_context=context,
        completion_mode="reply",
        start_queued=True,
    )
    assert queued["execution_state"] == "queued", queued
    ack = persist_chat_turn(
        str(state.actor.user_id), "解释库存含义", context, runtime_chat_payload(queued)
    )
    return context, queued, ack


def runtime_waiting(state, monkeypatch, status):
    async def wait(**kwargs):
        state.calls.append(kwargs)
        store, run_id = kwargs["binding_store"], kwargs["run_id"]
        grant = store.create(run_id, runtime_config=kwargs["runtime_config"])
        result = {
            "handler": "agent",
            "runtime": "xiaox",
            "run_id": run_id,
            "ok": False,
            "execution_state": status,
            "exit_status": status,
            "output": f"原任务提示：{status}",
        }

        def commit(parent, metadata):
            parent.status = status
            parent.final_output["xiaox_result"] = dict(result)
            if status == "waiting_user":
                metadata["waiting_input"] = {"question": result["output"]}

        store.update(run_id, commit)
        store.close(run_id, "completed", generation=grant.binding.metadata["generation"])
        return result

    monkeypatch.setattr(gateway, "run_xiaox_agent", wait)


def delivery_offline(*args, **kwargs):
    raise OperationalError("delivery unavailable", {}, Exception("temporary write failure"))


@pytest.mark.parametrize("control", ["retry", "deleted", "revised", "stopped"])
@pytest.mark.parametrize("status", ["completed", "waiting_user", "paused"])
def test_dispatcher_recovers_chat_delivery_after_restart_without_reexecuting(
    runtime_entry, monkeypatch, control, status
):
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.db.models import AIConversation, AIConversationSession
    from app.domain.shared_services.conversation_service import ConversationService

    state = runtime_entry
    context, queued, ack = queue_chat(state, monkeypatch)
    if status != "completed":
        runtime_waiting(state, monkeypatch, status)
    original_settle = ConversationService.settle_queued_reply
    monkeypatch.setattr(ConversationService, "settle_queued_reply", delivery_offline)
    run = state.drain(queued["run_id"])
    assert run.status == status and len(state.calls) == 1
    execution = state.queue.get(run.run_id)
    receipt = run.metadata["runtime_requests"][run.metadata["_xiaox_queued_request"]["request_key"]]
    assert receipt["state"] == "returned" and receipt["result"]["execution_state"] == status
    with state.actor.factory() as db:
        assert db.get(AIConversation, ack["message_ids"][1]).content == queued["output"]
    monkeypatch.setattr(ConversationService, "settle_queued_reply", original_settle)
    if control in {"deleted", "revised"}:
        with state.actor.factory.begin() as db:
            session = (
                db.query(AIConversationSession)
                .filter_by(session_id=context["conversation_id"])
                .one()
            )
            if control == "deleted":
                session.deleted_at = datetime.now(UTC).replace(tzinfo=None)
            else:
                session.revision += 1

    # Recreate the dispatcher and SQL repository: no browser, history GET,
    # producer callback, or in-process delivery retry survives this boundary.
    restored = SQLAlchemyAgentRunRepository(session_factory=state.actor.factory)
    dispatcher = AgentTaskDispatcher(execution_repository=state.queue, run_repository=restored)
    for path in (
        "app.application.agent_orchestrator.verification_recovery.reconcile_pending_verifications",
        "app.application.enterprise_cognition.outcomes.reconcile_pending_outcomes",
        "app.infrastructure.xiaox.receipt_projection.resume_ready_xiaox_runs",
    ):
        monkeypatch.setattr(path, lambda **_: 0)
    if control == "stopped":
        dispatcher._stop.set()
    for _ in range(2):
        dispatcher._last_outcome_recovery = float("-inf")
        dispatcher._recover_outcomes()
        if dispatcher._outcome_worker is not None:
            dispatcher._outcome_worker.join(timeout=5)
            assert not dispatcher._outcome_worker.is_alive()
    with state.actor.factory() as db:
        rows = db.query(AIConversation).order_by(AIConversation.id).all()
        assert [row.id for row in rows] == ack["message_ids"]
        assert rows[1].content == (
            receipt["result"]["output"] if control == "retry" else queued["output"]
        )
        assert json.loads(rows[1].conversation_metadata)["summary"]["status"] == (
            status if control == "retry" else "queued"
        )
    assert restored.get(run.run_id).to_dict() == run.to_dict()
    assert state.queue.get(run.run_id) == execution
    assert execution.execution_count == 1
    assert len(state.calls) == 1


@pytest.mark.parametrize("status", ["waiting_user", "paused"])
@pytest.mark.parametrize("recovered_by", ["maintenance", "history"])
def test_same_input_resume_updates_original_waiting_reply(
    runtime_entry, monkeypatch, status, recovered_by
):
    from app.application.ai_chat.queued_chat_delivery import reconcile_pending_chat_replies
    from app.application.task_conversation_store import TaskConversationStore
    from app.db.models import AIConversation
    from app.infrastructure.tenant_scope import tenant_scope

    state = runtime_entry
    original_runtime = gateway.run_xiaox_agent
    context, queued, ack = queue_chat(state, monkeypatch)
    runtime_waiting(state, monkeypatch, status)
    waiting = state.drain(queued["run_id"])
    original_key = waiting.metadata["_xiaox_queued_request"]["request_key"]
    original_receipt = waiting.metadata["runtime_requests"][original_key]
    with state.actor.factory() as db:
        row = db.get(AIConversation, ack["message_ids"][1])
        assert row.content == original_receipt["result"]["output"]
        assert json.loads(row.conversation_metadata)["summary"]["status"] == status

    monkeypatch.setattr(gateway, "run_xiaox_agent", original_runtime)
    response = state.client.post(
        f"/api/agent/runs/{queued['run_id']}/resume", json={"request_id": "same-input-resume"}
    )
    assert response.status_code == 202, response.text
    pending = state.repository.get(queued["run_id"]).metadata["_xiaox_queued_request"]
    assert pending["task"] == waiting.message and pending["answer_to_waiting_input"] is False
    assert pending["input_data"] == waiting.metadata["_xiaox_input_data"]
    completed = state.drain(queued["run_id"])
    assert completed.status == "completed"
    assert completed.metadata["runtime_requests"][original_key] == original_receipt
    for _ in range(2):
        if recovered_by == "maintenance":
            reconcile_pending_chat_replies(repository=state.repository)
        else:
            with tenant_scope(state.actor.tenant_id):
                history = TaskConversationStore().get_history(
                    session_id=context["conversation_id"],
                    user_id=state.actor.user_id,
                    mod_id=context.get("mod_id", ""),
                    turn_id=context["turn_id"],
                )
            assert history["turn_receipt"]["status"] == "completed"
            assert history["turn_receipt"]["message_id"] == ack["message_ids"][1]
            assert [row["id"] for row in history["messages"]] == ack["message_ids"]
    with state.actor.factory() as db:
        rows = db.query(AIConversation).order_by(AIConversation.id).all()
        assert [row.id for row in rows] == ack["message_ids"]
        assert rows[1].content == completed.final_output["xiaox_result"]["output"]
        summary = json.loads(rows[1].conversation_metadata)["summary"]
        assert summary["status"] == "completed" and summary["turn_id"] == context["turn_id"]
    assert state.repository.get(completed.run_id).to_dict() == completed.to_dict()
    assert len(state.calls) == 2 and state.queue.get(completed.run_id).execution_count == 2


@pytest.mark.parametrize("status", ["blocked", "waiting_user"])
@pytest.mark.parametrize("cancel_at", ["before_read", "before_write"])
def test_delivery_cannot_publish_snapshot_cancelled_after_scan(
    runtime_entry, monkeypatch, status, cancel_at
):
    from app.application.ai_chat.conversation_history import reconcile_queued_chat_reply
    from app.db.models import AIConversation
    from app.domain.shared_services.conversation_service import ConversationService

    state = runtime_entry
    context, queued, ack = queue_chat(state, monkeypatch)
    runtime_waiting(state, monkeypatch, status)
    original_settle = ConversationService.settle_queued_reply
    monkeypatch.setattr(ConversationService, "settle_queued_reply", delivery_offline)
    observed = state.drain(queued["run_id"])
    assert observed.status == status
    with state.actor.factory() as db:
        row = db.get(AIConversation, ack["message_ids"][1])
        original_message = (row.content, row.conversation_metadata)
    monkeypatch.setattr(ConversationService, "settle_queued_reply", original_settle)
    cancellations = []

    def cancel():
        response = state.client.post(f"/api/agent/runs/{observed.run_id}/cancel")
        assert response.status_code == 200, response.text
        cancelled = state.repository.get(observed.run_id)
        assert cancelled.status == "cancelled"
        cancellations.append(cancelled.to_dict())

    if cancel_at == "before_read":
        cancel()
    else:

        def cancel_before_write(self, **kwargs):
            cancel()
            return original_settle(self, **kwargs)

        monkeypatch.setattr(ConversationService, "settle_queued_reply", cancel_before_write)
    assert not reconcile_queued_chat_reply(
        context, context["turn_id"], observed.run_id, run=observed
    )
    assert len(cancellations) == 1
    assert state.repository.get(observed.run_id).to_dict() == cancellations[0]
    with state.actor.factory() as db:
        row = db.get(AIConversation, ack["message_ids"][1])
        assert (row.content, row.conversation_metadata) == original_message
        assert db.query(AIConversation).count() == 2
    assert len(state.calls) == 1 and state.queue.get(observed.run_id).execution_count == 1


def test_delivery_prioritizes_recent_receipts_and_advances_bounded_history(
    runtime_entry, monkeypatch
):
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.ai_chat.queued_chat_delivery import reconcile_pending_chat_replies
    from app.db.models import AIConversation, AIConversationSession
    from app.domain.shared_services.conversation_service import ConversationService

    state = runtime_entry
    original_settle = ConversationService.settle_queued_reply
    monkeypatch.setattr(ConversationService, "settle_queued_reply", delivery_offline)
    deliveries = []
    for name in ("old-invalid", "old-one", "old-two", "latest"):
        context, queued, ack = queue_chat(state, monkeypatch, name)
        run = state.drain(queued["run_id"])
        deliveries.append((context, queued, ack, run))
    with state.actor.factory.begin() as db:
        db.query(AIConversationSession).filter_by(session_id="old-invalid").one().revision += 1
    monkeypatch.setattr(ConversationService, "settle_queued_reply", original_settle)
    restored = SQLAlchemyAgentRunRepository(session_factory=state.actor.factory)
    cursor = {}
    for expected_count, original_index, settled in (
        (1, 0, {3}),
        (1, 1, {1, 3}),
        (1, 2, {1, 2, 3}),
        (0, 3, {1, 2, 3}),
        (0, None, {1, 2, 3}),
    ):
        assert reconcile_pending_chat_replies(repository=restored, cursor=cursor, limit=1) == (
            expected_count
        )
        if original_index is None:
            assert cursor == {}
        else:
            run = deliveries[original_index][3]
            assert cursor == {"updated_at": run.updated_at, "run_id": run.run_id}
        with state.actor.factory() as db:
            assert db.query(AIConversation).count() == 8
            for index, (_, queued, ack, run) in enumerate(deliveries):
                row = db.get(AIConversation, ack["message_ids"][1])
                assert row.content == (
                    run.final_output["xiaox_result"]["output"]
                    if index in settled
                    else queued["output"]
                )
    assert len(state.calls) == 4
    for _, _, _, run in deliveries:
        assert restored.get(run.run_id).to_dict() == run.to_dict()
        assert state.queue.get(run.run_id).execution_count == 1


def test_delivery_and_business_write_use_same_host_then_mod_lock_order(
    runtime_entry, conversation_storage, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from sqlalchemy import event

    from app.application.agent_orchestrator.business_write_guard import (
        worker_claim_scope,
        worker_write_guard,
    )
    from app.application.ai_chat.conversation_history import reconcile_queued_chat_reply
    from app.db.models import AIConversation, AIConversationSession
    from app.domain.shared_services import conversation_service

    state = runtime_entry
    context, queued, ack = queue_chat(state, monkeypatch)
    with monkeypatch.context() as outage:
        outage.setattr(
            conversation_service.ConversationService, "settle_queued_reply", delivery_offline
        )
        completed = state.drain(queued["run_id"])
    business_run = create(state, "concurrent-mod-business")
    claim = state.queue.claim("concurrent-business-worker", lease_seconds=120)
    assert claim.run_id == business_run
    host = state.actor.factory.kw["bind"]
    mod = conversation_storage.kw["bind"]
    assert host is not mod and host.url.database != mod.url.database
    host_locked, delivery_waiting_for_host = Event(), Event()
    original_begin = conversation_service.begin_conversation_write

    def begin(db):
        if db.get_bind() is host:
            delivery_waiting_for_host.set()
        original_begin(db)

    def bounded_lock_wait(connection, *_):
        connection.execute("PRAGMA busy_timeout = 500")

    def business_write():
        with (
            worker_claim_scope(state.repository, claim, "concurrent-business-worker"),
            conversation_storage() as db,
            worker_write_guard(db),
        ):
            host_locked.set()
            assert delivery_waiting_for_host.wait(timeout=3)
            db.query(AIConversationSession).filter_by(session_id=context["conversation_id"]).update(
                {"title": "并发业务更新"}
            )
            db.commit()

    monkeypatch.setattr(conversation_service, "begin_conversation_write", begin)
    event.listen(host, "checkout", bounded_lock_wait)
    event.listen(mod, "checkout", bounded_lock_wait)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            business = pool.submit(business_write)
            assert host_locked.wait(timeout=3)
            try:
                delivered = reconcile_queued_chat_reply(
                    context, context["turn_id"], completed.run_id, run=completed
                )
            finally:
                delivery_waiting_for_host.set()
            business.result(timeout=3)
            assert delivered
    finally:
        event.remove(host, "checkout", bounded_lock_wait)
        event.remove(mod, "checkout", bounded_lock_wait)
    with conversation_storage() as db:
        assert db.query(AIConversation).count() == 2
        assert (
            db.get(AIConversation, ack["message_ids"][1]).content
            == (completed.final_output["xiaox_result"]["output"])
        )
        assert db.query(AIConversationSession).one().title == "并发业务更新"
    assert state.repository.get(completed.run_id).to_dict() == completed.to_dict()
    assert len(state.calls) == 1
